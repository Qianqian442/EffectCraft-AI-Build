#!/usr/bin/env python3
"""Add safe desktop plugin package inspection and install compatible AE extensions."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_PACKAGE_IMPORT_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_effect_loader(root: Path) -> None:
    path = root / "crates/engine/src/cmd/effect.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Desktop plugin package import is already patched.")
        return

    helper = r'''
// EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_PACKAGE_IMPORT_V1
/// Inspect a desktop plug-in ZIP and install only formats EffectCraft can safely host.
/// Native .aex/.dll/.ofx binaries are preserved for analysis but are never executed.
fn install_desktop_plugin_archive(s: &mut Session, archive_path: &str) -> Result<Value> {
    const CMD: &str = "effect.plugins.load";
    const MAX_ENTRIES: usize = 512;
    const MAX_TOTAL_BYTES: u64 = 256 * 1024 * 1024;
    const MAX_MODULE_BYTES: u64 = 64 * 1024 * 1024;
    const MAX_SCRIPT_BYTES: u64 = 16 * 1024 * 1024;
    const MAX_ASSET_BYTES: u64 = 32 * 1024 * 1024;
    const MAX_NATIVE_BYTES: u64 = 64 * 1024 * 1024;

    let cfg = s.config.clone()
        .ok_or_else(|| bad(CMD, "当前会话没有可写的插件目录"))?;
    let root = cfg.dir()
        .ok_or_else(|| bad(CMD, "当前存储环境没有可访问的插件目录"))?;
    let plugins_dir = root.join(PLUGINS_DIR);
    std::fs::create_dir_all(&plugins_dir)
        .map_err(|error| bad(CMD, format!("无法创建插件目录：{error}")))?;

    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let staging = plugins_dir.join("Import-Staging").join(format!("desktop_{stamp}"));
    let install_dir = staging.join("install");
    let wat_dir = staging.join("wat");
    let assets_dir = plugins_dir.join("Imported-Assets").join(format!("desktop_{stamp}"));
    let originals_dir = plugins_dir.join("Desktop-Originals").join(format!("desktop_{stamp}"));

    let archive_file = std::fs::File::open(archive_path)
        .map_err(|error| bad(CMD, format!("无法读取插件 ZIP：{error}")))?;
    let mut archive = zip::ZipArchive::new(archive_file)
        .map_err(|error| bad(CMD, format!("插件 ZIP 无效或已损坏：{error}")))?;
    if archive.len() > MAX_ENTRIES {
        return Err(bad(CMD, "插件包文件数量超过 512 个安全上限"));
    }

    let mut total_bytes = 0_u64;
    let mut wasm_count = 0_usize;
    let mut wat_count = 0_usize;
    let mut panel_count = 0_usize;
    let mut script_names: Vec<String> = Vec::new();
    let mut asset_names: Vec<String> = Vec::new();
    let mut native_names: Vec<String> = Vec::new();
    let mut skipped_names: Vec<String> = Vec::new();

    for index in 0..archive.len() {
        let mut entry = archive.by_index(index)
            .map_err(|error| bad(CMD, format!("无法读取 ZIP 条目：{error}")))?;
        if entry.is_dir() {
            continue;
        }
        let entry_name = entry.name()
            .map_err(|error| bad(CMD, format!("无法读取 ZIP 文件名：{error}")))?
            .to_owned();
        if entry_name.contains('\\') || entry_name.contains('\0') {
            skipped_names.push(entry_name);
            continue;
        }
        let relative = Path::new(&entry_name);
        if relative.components().any(|component| !matches!(component, Component::Normal(_))) {
            skipped_names.push(entry_name);
            continue;
        }
        if entry_name.split('/').any(|part| part.starts_with('.') || part.eq_ignore_ascii_case("__MACOSX")) {
            continue;
        }
        let Some(file_name) = relative.file_name().and_then(|name| name.to_str()) else {
            skipped_names.push(entry_name);
            continue;
        };
        if file_name.is_empty() || file_name.len() > 180 {
            skipped_names.push(entry_name);
            continue;
        }
        let extension = relative.extension().and_then(|value| value.to_str())
            .unwrap_or_default().to_ascii_lowercase();

        let kind = if extension == "wasm" { "wasm" }
            else if extension == "wat" { "wat" }
            else if extension == "jsx" { "panel" }
            else if extension == "js" { "script" }
            else if ["aex", "dll", "ofx", "so", "dylib", "plugin", "bundle", "prm", "8bf"].contains(&extension.as_str())
                || entry_name.to_ascii_lowercase().contains(".plugin/")
                || entry_name.to_ascii_lowercase().contains(".ofx.bundle/") { "native" }
            else if ["cube", "3dl", "lut", "look", "png", "jpg", "jpeg", "webp", "tif", "tiff", "exr",
                     "ttf", "otf", "json", "xml", "txt", "md", "glsl", "frag", "vert", "wgsl",
                     "fx", "osl", "h", "hpp", "c", "cc", "cpp", "rs", "sbsar"].contains(&extension.as_str()) { "asset" }
            else if extension == "jsxbin" { "encoded_script" }
            else { "unknown" };

        if kind == "unknown" {
            continue;
        }
        if kind == "encoded_script" {
            skipped_names.push(format!("{file_name}（JSXBIN 未支持）"));
            continue;
        }

        let max_bytes = match kind {
            "wasm" | "wat" => MAX_MODULE_BYTES,
            "panel" | "script" => MAX_SCRIPT_BYTES,
            "native" => MAX_NATIVE_BYTES,
            _ => MAX_ASSET_BYTES,
        };
        let mut bytes = Vec::new();
        (&mut entry).take(max_bytes + 1)
            .read_to_end(&mut bytes)
            .map_err(|error| bad(CMD, format!("读取 {file_name} 失败：{error}")))?;
        let size = u64::try_from(bytes.len()).unwrap_or(u64::MAX);
        if size > max_bytes {
            skipped_names.push(format!("{file_name}（超过单文件安全上限）"));
            continue;
        }
        total_bytes = total_bytes.saturating_add(size);
        if total_bytes > MAX_TOTAL_BYTES {
            return Err(bad(CMD, "插件包可提取文件总量超过 256 MB 安全上限"));
        }
        if bytes.is_empty() {
            continue;
        }

        let destination_name = format!("archive_{index}_{file_name}");
        if !super::scripts::is_bare_name(&destination_name)
            || (cfg!(windows) && super::scripts::windows_unsafe_name(&destination_name)) {
            skipped_names.push(format!("{file_name}（文件名不安全）"));
            continue;
        }

        match kind {
            "wasm" | "panel" => {
                std::fs::create_dir_all(&install_dir)
                    .map_err(|error| bad(CMD, format!("无法创建插件临时目录：{error}")))?;
                std::fs::write(install_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法暂存 {file_name}：{error}")))?;
                if kind == "wasm" { wasm_count += 1; } else { panel_count += 1; }
            }
            "wat" => {
                std::fs::create_dir_all(&wat_dir)
                    .map_err(|error| bad(CMD, format!("无法创建 WAT 临时目录：{error}")))?;
                std::fs::write(wat_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法暂存 {file_name}：{error}")))?;
                wat_count += 1;
            }
            "script" => {
                let code = String::from_utf8(bytes)
                    .map_err(|_| bad(CMD, format!("{file_name} 不是 UTF-8 脚本文本，未安装")))?;
                cfg.write(&format!("{}/{destination_name}", super::scripts::SCRIPTS_DIR), &code)
                    .map_err(|error| bad(CMD, format!("无法安装 AE 脚本 {file_name}：{error}")))?;
                script_names.push(destination_name);
            }
            "asset" => {
                std::fs::create_dir_all(&assets_dir)
                    .map_err(|error| bad(CMD, format!("无法创建素材目录：{error}")))?;
                std::fs::write(assets_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法保存素材 {file_name}：{error}")))?;
                asset_names.push(destination_name);
            }
            "native" => {
                std::fs::create_dir_all(&originals_dir)
                    .map_err(|error| bad(CMD, format!("无法创建电脑版插件存档目录：{error}")))?;
                std::fs::write(originals_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法保存原始插件 {file_name}：{error}")))?;
                native_names.push(destination_name);
            }
            _ => {}
        }
    }

    if wasm_count == 0 && wat_count == 0 && panel_count == 0
        && script_names.is_empty() && asset_names.is_empty() && native_names.is_empty() {
        return Err(bad(CMD, "压缩包内没有找到可识别的 WASM、AE 脚本、素材或电脑版插件文件"));
    }

    if !script_names.is_empty() {
        s.scripts_changed();
    }

    let mut installed_wasm = Vec::<String>::new();
    let mut loaded_wasm = Vec::<Value>::new();
    let mut installed_panels = Vec::<String>::new();
    let mut compatibility_errors = Vec::<Value>::new();
    let mut install_entries = if install_dir.is_dir() {
        std::fs::read_dir(&install_dir)
            .map_err(|error| bad(CMD, format!("无法读取插件暂存目录：{error}")))?
            .filter_map(std::result::Result::ok)
            .map(|entry| entry.path())
            .collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    install_entries.sort();

    for source in install_entries {
        let extension = source.extension().and_then(|value| value.to_str()).unwrap_or_default();
        let source_text = source.to_string_lossy().to_string();
        let file_name = source.file_name().map(|value| value.to_string_lossy().to_string()).unwrap_or_default();
        if extension.eq_ignore_ascii_case("wasm") {
            match s.execute("effect.plugins.load", json!({"path": source_text})) {
                Ok(result) => {
                    // Keep only modules that the host successfully validates and loads.
                    // A unique name avoids replacing an existing effect on a later import.
                    let target_name = format!("desktop_{stamp}_{}.wasm", installed_wasm.len());
                    let target = plugins_dir.join(&target_name);
                    match std::fs::copy(&source, &target) {
                        Ok(_) => {
                            installed_wasm.push(target_name);
                            loaded_wasm.push(result);
                        }
                        Err(error) => {
                            let _ = std::fs::remove_file(&target);
                            compatibility_errors.push(json!({"file": file_name, "error": format!("插件已载入本次会话，但无法保存供下次启动使用：{error}")}));
                        }
                    }
                }
                Err(error) => compatibility_errors.push(json!({"file": file_name, "error": error.to_string()})),
            }
        } else if extension.eq_ignore_ascii_case("jsx") {
            match s.execute("file.installScriptUIPanel", json!({"path": source_text})) {
                Ok(_) => installed_panels.push(file_name),
                Err(error) => compatibility_errors.push(json!({"file": file_name, "error": error.to_string()})),
            }
        }
    }

    let mut loaded_wat = Vec::<Value>::new();
    if wat_dir.is_dir() {
        let mut wat_files = std::fs::read_dir(&wat_dir)
            .map_err(|error| bad(CMD, format!("无法读取 WAT 插件暂存目录：{error}")))?
            .filter_map(std::result::Result::ok)
            .map(|entry| entry.path())
            .collect::<Vec<_>>();
        wat_files.sort();
        for source in wat_files {
            let file_name = source.file_name().map(|value| value.to_string_lossy().to_string()).unwrap_or_default();
            match s.execute("effect.plugins.load", json!({"path": source.to_string_lossy()})) {
                Ok(result) => {
                    let target_name = format!("desktop_{stamp}_{}.wat", loaded_wat.len());
                    let target = plugins_dir.join(&target_name);
                    match std::fs::copy(&source, &target) {
                        Ok(_) => loaded_wat.push(result),
                        Err(error) => {
                            let _ = std::fs::remove_file(&target);
                            compatibility_errors.push(json!({"file": file_name, "error": format!("WAT 已载入本次会话，但无法保存供下次启动使用：{error}")}));
                        }
                    }
                }
                Err(error) => compatibility_errors.push(json!({"file": file_name, "error": error.to_string()})),
            }
        }
    }

    let install_result = json!({
        "installed": installed_wasm,
        "panels": installed_panels,
        "loaded": loaded_wasm,
        "errors": compatibility_errors
    });
    let wat_result = json!({"loaded": loaded_wat, "errors": []});
    let report_dir = plugins_dir.join("Import-Reports");
    std::fs::create_dir_all(&report_dir)
        .map_err(|error| bad(CMD, format!("无法创建插件分析报告目录：{error}")))?;
    let report_path = report_dir.join(format!("desktop-import-{stamp}.txt"));
    let script_count = script_names.len();
    let asset_count = asset_names.len();
    let native_count = native_names.len();
    let skipped_count = skipped_names.len();
    let report = format!(
        "EffectCraft 电脑版插件包分析报告\n时间戳：{stamp}\n\n已安装 WASM 效果插件：{wasm_count}\n已安装 JSX 面板：{panel_count}\n已导入 JS 脚本：{script_count}\n已归档素材/源码：{asset_count}\n已保存电脑版原生插件原件：{native_count}\n跳过文件：{skipped_count}\n\n说明：只有 WASM/WAT 与 EffectCraft 兼容的 AE 脚本/面板会进入对应导入流程。\n.aex/.dll/.ofx/.plugin 等原生二进制仅保存为待移植原件，不会在 Android 上执行。\n.cube/.3dl/LUT、纹理、字体和源代码仅作为素材归档；并不表示它们已自动变成可运行效果。\nWASM/JSX 与素材存档目录位于：{}\n电脑版原生插件原件目录位于：{}\n",
        assets_dir.display(), originals_dir.display()
    );
    std::fs::write(&report_path, report)
        .map_err(|error| bad(CMD, format!("无法保存插件分析报告：{error}")))?;

    if let Some(object) = install_result.as_object_mut() {
        object.insert("desktop_scripts".into(), json!(script_names));
        object.insert("desktop_assets".into(), json!(asset_names));
        object.insert("desktop_native_requires_port".into(), json!(native_names));
        object.insert("desktop_skipped".into(), json!(skipped_names));
        object.insert("wat_result".into(), wat_result);
        object.insert("compatibility_report".into(), json!(report_path.to_string_lossy()));
    }
    let mut notice = format!(
        "电脑插件包已分析：WASM {wasm_count} 个、JSX 面板 {panel_count} 个、JS 脚本 {script_count} 个、素材 {asset_count} 个"
    );
    if native_count > 0 {
        notice.push_str(&format!("；另有 {native_count} 个电脑原生插件需要移植，未在安卓执行"));
    }
    if skipped_count > 0 {
        notice.push_str(&format!("；跳过 {skipped_count} 个不支持或超限文件"));
    }
    notice.push_str(&format!("；报告已保存：{}", report_path.display()));
    s.toast(notice);
    Ok(install_result)
}

'''
    marker = "/// " + chr(96) + "effect.plugins.load" + chr(96) + ": load WASM/WAT effect plug-ins directly or from a ZIP archive.\n"
    source = replace_once(source, marker, helper + marker, "desktop package analyzer insertion")

    anchor = '''    let loader = s.plugin_loader.ok_or_else(|| EngineError::Other("WebAssembly effect plug-ins are not available in this build".into()))?;
    let files: Vec<String> = match (str_p(p, "path"), str_p(p, "folder")) {'''
    replacement = '''    let loader = s.plugin_loader.ok_or_else(|| EngineError::Other("WebAssembly effect plug-ins are not available in this build".into()))?;
    if let Some(path) = str_p(p, "path")
        && Path::new(path).extension().is_some_and(|extension| extension.eq_ignore_ascii_case("zip"))
    {
        return install_desktop_plugin_archive(s, path);
    }
    let files: Vec<String> = match (str_p(p, "path"), str_p(p, "folder")) {'''
    source = replace_once(source, anchor, replacement, "ZIP route to desktop package installer")
    path.write_text(source, encoding="utf-8")
    print("Added safe desktop ZIP inspection, WASM/JSX bundle installation, JS script import and native-binary staging.")


def patch_toolbar(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_IMPORT_MENU_V1" in source:
        print("Desktop AE script choice is already present in the unified import menu.")
        return

    old_state = "    let mut import_wasm = false;\n    let mut import_ai = false;\n"
    new_state = old_state + "    let mut import_script = false;\n"
    source = replace_once(source, old_state, new_state, "toolbar import state")

    old_button = '''                if popup.button("DeepSeek AI 插件 ZIP").clicked() {
                    import_ai = true;
                }
                popup.label("电脑版 AE 原生插件 .aex 不能直接在 Android 运行");'''
    new_button = '''                if popup.button("DeepSeek AI 插件 ZIP").clicked() {
                    import_ai = true;
                }
                // EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_IMPORT_MENU_V1
                if popup.button("AE 脚本 / ScriptUI 面板 (.jsx/.js)").clicked() {
                    import_script = true;
                }
                popup.label("电脑插件 ZIP 可自动装入 WASM、JSX 和脚本；原生 .aex/.dll/.ofx 需要移植");'''
    source = replace_once(source, old_button, new_button, "desktop script menu item")

    old_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_ai;\n"
    new_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_ai && !import_script;\n"
    source = replace_once(source, old_close, new_close, "desktop script menu close state")

    old_ai = '''    if import_ai {
        match crate::open_ai_plugin_import_from_toolbar() {
            Ok(()) => app.ui.status = "请选择 DeepSeek AI 插件 ZIP；随后按 Android 系统提示确认安装。".into(),
            Err(error) => app.ui.status = error,
        }
    }
'''
    new_ai = old_ai + '''    if import_script {
        match crate::menus::invoke(app, ui.ctx(), "file.installScript", json!({})) {
            Ok(_) => app.ui.status = "AE 脚本已导入；可在 文件 → 脚本 中使用。".into(),
            Err(error) => app.ui.status = error,
        }
    }
'''
    source = replace_once(source, old_ai, new_ai, "AE script installer route")
    path.write_text(source, encoding="utf-8")
    print("Added AE .jsx/.js import through EffectCraft's original script installer inside the one unified toolbar entry.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_effect_loader(root)
    patch_toolbar(root)
    print("Desktop plug-in ZIPs now install compatible WASM modules and JSX panels, import JS scripts, archive portable resources, and preserve native binaries for later porting.")
    print("No desktop native binary is executed by the Android app.")


if __name__ == "__main__":
    main()
