#!/usr/bin/env python3
"""Add safe ZIP archive import for WASM/WAT effect plug-ins to EffectCraft Android."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_ZIP_EFFECT_PLUGIN_IMPORT_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_manifests(root: Path) -> None:
    workspace = root / "Cargo.toml"
    source = workspace.read_text(encoding="utf-8")
    source = replace_once(
        source,
        'wasmi = { version = "2", default-features = false, features = ["std", "validate", "wat", "deterministic", "portable-dispatch"] }\n',
        'wasmi = { version = "2", default-features = false, features = ["std", "validate", "wat", "deterministic", "portable-dispatch"] }\n'
        'zip = { version = "9.1.3", default-features = false, features = ["deflate-flate2", "flate2/rust_backend"] }\n',
        "ZIP archive reader workspace dependency",
    )
    workspace.write_text(source, encoding="utf-8")

    engine_manifest = root / "crates/engine/Cargo.toml"
    source = engine_manifest.read_text(encoding="utf-8")
    source = replace_once(source, "web-time = { workspace = true }\n", "web-time = { workspace = true }\nzip = { workspace = true }\n", "Engine ZIP archive dependency")
    engine_manifest.write_text(source, encoding="utf-8")

    lock = root / "Cargo.lock"
    source = lock.read_text(encoding="utf-8")
    package_start = source.find('name = "effectcraft-engine"\nversion = "0.21.1"\ndependencies = [')
    if package_start < 0:
        raise SystemExit("Could not locate effectcraft-engine package in Cargo.lock")
    package_end = source.find("\n]\n", package_start)
    if package_end < 0:
        raise SystemExit("Could not locate effectcraft-engine dependency list in Cargo.lock")
    block = source[package_start:package_end]
    if '"zip 9.1.3"' not in block:
        block = replace_once(block, ' "web-time",', ' "web-time",\n "zip 9.1.3",', "Cargo.lock engine ZIP dependency")
        source = source[:package_start] + block + source[package_end:]
    # zip 9.1.3 and flate2 are already present in the upstream lockfile.
    lock.write_text(source, encoding="utf-8")


def patch_effect_loader(root: Path) -> None:
    path = root / "crates/engine/src/cmd/effect.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    imports = "use serde_json::{Value, json};\n"
    source = replace_once(
        source,
        imports,
        imports + "use std::io::Read;\nuse std::path::{Component, Path};\n",
        "ZIP reader imports",
    )

    helper = r'''
// EFFECTCRAFT_ANDROID_ZIP_EFFECT_PLUGIN_IMPORT_V1
/// Safely extract only WASM/WAT effect modules from a ZIP into the app's Plug-ins folder.
/// The archive is never allowed to choose an output path: only a validated basename is used.
fn extract_effect_plugin_archive(s: &Session, archive_path: &str) -> Result<Vec<String>> {
    const CMD: &str = "effect.plugins.load";
    const MAX_ENTRIES: usize = 256;
    const MAX_MODULE_BYTES: u64 = 64 * 1024 * 1024;
    const MAX_TOTAL_BYTES: u64 = 256 * 1024 * 1024;

    let config_dir = s.config.as_ref().and_then(|config| config.dir())
        .ok_or_else(|| bad(CMD, "当前存储环境没有可写的插件目录"))?;
    let plugins_dir = config_dir.join("Plug-ins");
    std::fs::create_dir_all(&plugins_dir)
        .map_err(|error| bad(CMD, format!("无法创建插件目录：{error}")))?;

    let archive_file = std::fs::File::open(archive_path)
        .map_err(|error| bad(CMD, format!("无法读取 ZIP 压缩包：{error}")))?;
    let mut archive = zip::ZipArchive::new(archive_file)
        .map_err(|error| bad(CMD, format!("ZIP 压缩包无效或已损坏：{error}")))?;
    if archive.len() > MAX_ENTRIES {
        return Err(bad(CMD, "压缩包文件数量超过 256 个安全上限"));
    }

    let mut imported = Vec::new();
    let mut total_bytes = 0_u64;
    for index in 0..archive.len() {
        let mut entry = archive.by_index(index)
            .map_err(|error| bad(CMD, format!("无法读取 ZIP 条目：{error}")))?;
        if entry.is_dir() {
            continue;
        }

        let entry_name = entry.name().to_string();
        if entry_name.contains('\\') || entry_name.contains('\0') {
            continue;
        }
        let relative = Path::new(&entry_name);
        // Reject absolute paths, parent traversal and platform prefixes. Nested normal
        // folders are allowed, but the extracted destination is always a flat basename.
        if relative.components().any(|component| !matches!(component, Component::Normal(_))) {
            continue;
        }
        let Some(extension) = relative.extension().and_then(|value| value.to_str()) else {
            continue;
        };
        if !extension.eq_ignore_ascii_case("wasm") && !extension.eq_ignore_ascii_case("wat") {
            continue;
        }
        let Some(file_name) = relative.file_name().and_then(|value| value.to_str()) else {
            continue;
        };
        if file_name.is_empty() || file_name.len() > 180 {
            continue;
        }

        let mut bytes = Vec::new();
        (&mut entry).take(MAX_MODULE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|error| bad(CMD, format!("读取插件模块失败：{error}")))?;
        let size = u64::try_from(bytes.len()).unwrap_or(u64::MAX);
        if size > MAX_MODULE_BYTES {
            return Err(bad(CMD, format!("插件模块 {file_name} 超过 64 MB 安全上限")));
        }
        total_bytes = total_bytes.saturating_add(size);
        if total_bytes > MAX_TOTAL_BYTES {
            return Err(bad(CMD, "压缩包解压总量超过 256 MB 安全上限"));
        }
        if bytes.is_empty() {
            continue;
        }

        // Prefix with the archive entry index to avoid collisions with bundled or existing
        // user modules. The name remains stable when the same archive is imported again.
        let destination_name = format!("archive_{index}_{file_name}");
        let destination = plugins_dir.join(&destination_name);
        std::fs::write(&destination, &bytes)
            .map_err(|error| bad(CMD, format!("无法保存插件模块 {file_name}：{error}")))?;
        imported.push(destination.to_string_lossy().to_string());
    }

    if imported.is_empty() {
        return Err(bad(CMD, "这个 ZIP 中没有找到 .wasm 或 .wat 效果插件模块"));
    }
    Ok(imported)
}

'''
    source = replace_once(
        source,
        "/// `effect.plugins.load`: load WebAssembly effect plug-ins (a file, or every `.wasm` in a\n"
        "/// folder) through the host's loader ([`Session::plugin_loader`]).\n",
        helper + "/// `effect.plugins.load`: load WASM/WAT effect plug-ins directly or from a ZIP archive.\n",
        "ZIP archive extraction helper",
    )

    old_files = '''    let files: Vec<String> = match (str_p(p, "path"), str_p(p, "folder")) {
        (Some(path), _) => vec![path.to_string()],
        (None, Some(dir)) => {
            let mut v: Vec<String> = std::fs::read_dir(dir)
                .map_err(|e| bad(c, format!("cannot list {dir}: {e}")))?
                .flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().is_some_and(|x| x.eq_ignore_ascii_case("wasm")))
                .map(|p| p.to_string_lossy().to_string())
                .collect();
            v.sort();
            v
        }
        _ => return Err(bad(c, "give `path` or `folder`")),
    };'''
    new_files = '''    let files: Vec<String> = match (str_p(p, "path"), str_p(p, "folder")) {
        (Some(path), _) if Path::new(path).extension().is_some_and(|extension| extension.eq_ignore_ascii_case("zip")) => {
            extract_effect_plugin_archive(s, path)?
        }
        (Some(path), _) => vec![path.to_string()],
        (None, Some(dir)) => {
            let mut v: Vec<String> = std::fs::read_dir(dir)
                .map_err(|e| bad(c, format!("cannot list {dir}: {e}")))?
                .flatten()
                .map(|e| e.path())
                .filter(|path| path.extension().is_some_and(|extension| extension.eq_ignore_ascii_case("wasm") || extension.eq_ignore_ascii_case("wat")))
                .map(|path| path.to_string_lossy().to_string())
                .collect();
            v.sort();
            v
        }
        _ => return Err(bad(c, "give `path` or `folder`")),
    };'''
    source = replace_once(source, old_files, new_files, "ZIP-aware plugin file selection")
    path.write_text(source, encoding="utf-8")


def patch_picker(root: Path) -> None:
    # Some EffectCraft revisions have a similarly named engine module. Patch the file
    # that actually owns the UI file-dialog mapping instead of selecting by path existence.
    candidates = [
        root / "crates/ui-egui/src/menus/frontend.rs",
        root / "crates/engine/src/cmd/frontend.rs",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        changed = False
        for index, line in enumerate(lines):
            if '"effect.plugins.load"' not in line or "Ask::Open" not in line:
                continue
            if '"zip"' in line:
                print(f"Plugin picker already accepts ZIP archives: {path}")
                return
            if '["wasm", "wat"]' in line:
                lines[index] = line.replace('["wasm", "wat"]', '["wasm", "wat", "zip"]', 1)
            elif '["wasm", "wat", "zip"]' in line:
                print(f"Plugin picker already accepts ZIP archives: {path}")
                return
            else:
                # Keep any future extension added upstream; append ZIP without replacing it.
                import re
                match = re.search(r'Ask::Open\\(&\\[(.*?)\\]\\)', line)
                if not match:
                    continue
                entries = match.group(1)
                lines[index] = line[:match.start(1)] + entries + ', "zip"' + line[match.end(1):]
            changed = True
            break
        if changed:
            path.write_text("".join(lines), encoding="utf-8")
            print(f"Enabled ZIP in the effect plug-in picker: {path}")
            return
    raise SystemExit("Could not locate the effect.plugins.load file-picker mapping in the expected frontend sources.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_manifests(root)
    patch_effect_loader(root)
    patch_picker(root)
    print("The single plug-in import flow now accepts .wasm, .wat and .zip.")
    print("ZIP archives are safely scanned and their WASM/WAT effect modules are extracted to the persistent Plug-ins folder.")
    print("DeepSeek's signed AI ZIP continues through its dedicated Android package installer flow.")


if __name__ == "__main__":
    main()
