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

    // Extract visible ASCII and UTF-16LE strings without loading or executing the binary.
    // AE PiPL resources carry effect names, categories and match-name identifiers; plug-in
    // binaries may also retain parameter labels and UI text as readable strings.
    fn readable_plugin_strings(bytes: &[u8]) -> Vec<String> {
        fn push_run(output: &mut Vec<String>, run: &mut Vec<u8>) {
            if run.len() >= 4 && output.len() < 160 {
                let value = String::from_utf8_lossy(run).trim().to_string();
                if !value.is_empty() && !output.contains(&value) {
                    output.push(value.chars().take(180).collect());
                }
            }
            run.clear();
        }
        let mut output = Vec::new();
        let mut ascii = Vec::new();
        for byte in bytes.iter().copied() {
            if (0x20..=0x7e).contains(&byte) { ascii.push(byte); }
            else { push_run(&mut output, &mut ascii); }
        }
        push_run(&mut output, &mut ascii);
        let mut wide = Vec::new();
        for pair in bytes.chunks_exact(2) {
            let unit = u16::from_le_bytes([pair[0], pair[1]]);
            if (0x20..=0x7e).contains(&unit) { wide.push(unit as u8); }
            else { push_run(&mut output, &mut wide); }
        }
        push_run(&mut output, &mut wide);
        output
    }

    fn native_binary_info(bytes: &[u8]) -> (&'static str, &'static str) {
        if bytes.len() >= 2 && &bytes[..2] == b"MZ" {
            if bytes.len() >= 0x40 {
                let offset = u32::from_le_bytes([bytes[0x3c], bytes[0x3d], bytes[0x3e], bytes[0x3f]]) as usize;
                if let Some(header) = bytes.get(offset..offset.saturating_add(6)) {
                    if header.len() >= 6 && &header[..4] == b"PE\0\0" {
                        let machine = u16::from_le_bytes([header[4], header[5]]);
                        let arch = match machine {
                            0x014c => "32 位 x86",
                            0x8664 => "64 位 x86",
                            0xaa64 => "64 位 ARM",
                            0x01c4 => "32 位 ARM",
                            0x0200 => "英特尔安腾 64 位",
                            _ => "未知可执行文件架构",
                        };
                        return ("Windows 可执行文件", arch);
                    }
                }
            }
            return ("Windows 程序或动态库", "架构未识别");
        }
        if bytes.len() >= 20 && &bytes[..4] == b"\x7fLinux 可执行文件" {
            let machine = if bytes[5] == 2 {
                u16::from_be_bytes([bytes[18], bytes[19]])
            } else {
                u16::from_le_bytes([bytes[18], bytes[19]])
            };
            let arch = match machine {
                3 => "32 位 x86",
                40 => "32 位 ARM",
                62 => "64 位 x86",
                183 => "64 位 ARM",
                243 => "RISC-V 架构",
                _ => "未知 Linux 可执行文件架构",
            };
            return ("Linux 可执行文件", arch);
        }
        if bytes.len() >= 4 {
            let magic = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
            return match magic {
                0xfeedface => ("苹果系统原生文件", "32 位大端"),
                0xcefaedfe => ("苹果系统原生文件", "32 位小端"),
                0xfeedfacf => ("苹果系统原生文件", "64 位大端"),
                0xcffaedfe => ("苹果系统原生文件", "64 位小端"),
                0xcafebabe | 0xbebafeca | 0xcafebabf | 0xbfbafeca => ("苹果通用原生文件", "包含多种架构"),
                _ => ("未知原生文件", "架构未识别"),
            };
        }
        ("未知原生文件", "架构未识别")
    }

    // Match only effects for which this APK actually ships an Android reimplementation.
    // Probe both package paths and readable strings embedded in native plug-in binaries.
    fn desktop_native_compatibility(source: &str, probe: &str) -> Option<Value> {
        let token = probe.to_ascii_lowercase()
            .replace('_', "")
            .replace('-', "")
            .replace(' ', "")
            .replace('.', "");
        let (effect_id, effect_name, note) = if token.contains("rsmb") {
            ("org.effectcraft.compat.rsmb-motion-blur", "方向运动模糊（兼容效果）",
             "安卓方向运动模糊兼容效果；不包含电脑版原版运动矢量估算功能")
        } else if token.contains("sglowaura") || token.contains("sapphireglowaura") || token.contains("glowaura") {
            ("org.effectcraft.sapphire.compat.glow-aura", "蓝宝石光晕氛围",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sglow") || token.contains("sapphireglow") {
            ("org.effectcraft.sapphire.compat.glow", "蓝宝石光晕",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("slensflare") || token.contains("sapphirelensflare") {
            ("org.effectcraft.sapphire.compat.lensflare", "蓝宝石镜头光斑",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sblur") || token.contains("sapphireblur") {
            ("org.effectcraft.sapphire.compat.blur", "蓝宝石模糊",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sdistort") || token.contains("sapphiredistort") {
            ("org.effectcraft.sapphire.compat.distort", "蓝宝石扭曲",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sstylize") || token.contains("sapphirestylize") {
            ("org.effectcraft.sapphire.compat.stylize", "蓝宝石风格化",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sglint") || token.contains("sapphireglint") {
            ("org.effectcraft.sapphire.compat.glint", "蓝宝石星芒",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("srays") || token.contains("sapphirerays") {
            ("org.effectcraft.sapphire.compat.rays", "蓝宝石光线",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("shalftone") || token.contains("sapphirehalftone") {
            ("org.effectcraft.sapphire.compat.halftone", "蓝宝石半色调",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("spixelsort") || token.contains("sapphirepixelsort") {
            ("org.effectcraft.sapphire.compat.pixelsort", "蓝宝石像素排序",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else {
            return None;
        };
        Some(json!({
            "source": source,
            "effect_id": effect_id,
            "effect_name": effect_name,
            "note": note
        }))
    }

    fn push_unique_native_mapping(mappings: &mut Vec<Value>, mapping: Value) {
        let source = mapping.get("source").cloned();
        let effect_id = mapping.get("effect_id").cloned();
        // Keep separate source files visible even when several files map to the same Android
        // effect module (for example, a plug-in binary plus an auxiliary native component).
        if !mappings.iter().any(|existing| {
            existing.get("source") == source.as_ref()
                && existing.get("effect_id") == effect_id.as_ref()
        }) {
            mappings.push(mapping);
        }
    }

    let cfg = s.config.clone()
        .ok_or_else(|| bad(CMD, "当前会话没有可写的插件目录"))?;
    let root = cfg.dir()
        .ok_or_else(|| bad(CMD, "当前存储环境没有可访问的插件目录"))?;
    let plugins_dir = root.join("Plug-ins");
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
    let mut native_mappings: Vec<Value> = Vec::new();
    let mut native_metadata: Vec<Value> = Vec::new();
    let mut skipped_names: Vec<String> = Vec::new();

    for index in 0..archive.len() {
        let mut entry = archive.by_index(index)
            .map_err(|error| bad(CMD, format!("无法读取 ZIP 条目：{error}")))?;
        if entry.is_dir() {
            continue;
        }
        let entry_name = entry.name()
            .map_err(|error| bad(CMD, format!("无法读取 ZIP 文件名：{error}")))?
            .into_owned();
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
            else if ["cube", "3dl", "lut", "look", "csp", "spi1d", "spi3d", "spimtx", "cc", "ccc", "cdl", "ocio",
                     "png", "jpg", "jpeg", "webp", "tif", "tiff", "exr", "ttf", "otf",
                     "json", "xml", "txt", "md", "toml", "plist", "rsrc", "r", "rc", "strings", "manifest",
                     "yaml", "yml", "ini", "config", "pdb", "map", "cmake", "mk", "sh", "py", "gradle",
                     "glsl", "frag", "vert", "wgsl", "hlsl", "dctl", "metal",
                     "fx", "osl", "h", "hpp", "c", "cpp", "rs", "sbsar"].contains(&extension.as_str()) { "asset" }
            else if extension == "jsxbin" { "asset" }
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
                // Read common package manifests for effect identifiers when the binary filename
                // is generic (for example, a bundle named simply "Plugin.aex").
                if ["json", "xml", "txt", "md", "toml", "plist", "rsrc", "r", "rc", "strings", "manifest", "yaml", "yml", "ini", "config", "pdb", "map", "jsxbin"].contains(&extension.as_str()) {
                    let metadata = String::from_utf8_lossy(&bytes);
                    let metadata_strings = readable_plugin_strings(&bytes);
                    let metadata_probe = format!("{}\n{}", metadata, metadata_strings.join("\n"));
                    if let Some(mapping) = desktop_native_compatibility(&entry_name, &metadata_probe) {
                        push_unique_native_mapping(&mut native_mappings, mapping);
                    }
                    if !metadata_strings.is_empty() {
                        native_metadata.push(json!({
                            "file": entry_name,
                            "strings": metadata_strings.iter().take(64).collect::<Vec<_>>()
                        }));
                    }
                }
                asset_names.push(destination_name);
            }
            "native" => {
                std::fs::create_dir_all(&originals_dir)
                    .map_err(|error| bad(CMD, format!("无法创建电脑版插件存档目录：{error}")))?;
                std::fs::write(originals_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法保存原始插件 {file_name}：{error}")))?;
                native_names.push(destination_name);
                // Inspect PiPL-adjacent names and strings embedded in the binary. This is static
                // metadata extraction only: native code is never loaded or executed.
                let embedded_strings = readable_plugin_strings(&bytes);
                let embedded_text = embedded_strings.join("\n");
                if let Some(mapping) = desktop_native_compatibility(&entry_name, &entry_name)
                    .or_else(|| desktop_native_compatibility(&entry_name, &embedded_text))
                {
                    push_unique_native_mapping(&mut native_mappings, mapping);
                }
                let (binary_format, architecture) = native_binary_info(&bytes);
                native_metadata.push(json!({
                    "file": entry_name,
                    "binary_format": binary_format,
                    "architecture": architecture,
                    "strings": embedded_strings.iter().take(64).collect::<Vec<_>>()
                }));
            }
            _ => {}
        }
    }

    if wasm_count == 0 && wat_count == 0 && panel_count == 0
        && script_names.is_empty() && asset_names.is_empty() && native_names.is_empty() {
        return Err(bad(CMD, "压缩包内没有找到可识别的效果模块、特效软件脚本、素材或电脑插件文件"));
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
                            compatibility_errors.push(json!({"file": file_name, "error": format!("模块文本已载入本次会话，但无法保存供下次启动使用：{error}")}));
                        }
                    }
                }
                Err(error) => compatibility_errors.push(json!({"file": file_name, "error": error.to_string()})),
            }
        }
    }

    let compatibility_match_count = native_mappings.len();
    let compatibility_summary = native_mappings.iter().map(|item| {
        format!(
            "{} → {}：{}",
            item["source"].as_str().unwrap_or(""),
            item["effect_name"].as_str().unwrap_or("兼容效果"),
            item["note"].as_str().unwrap_or("")
        )
    }).collect::<Vec<_>>().join("\n");
    let metadata_summary = native_metadata.iter().map(|item| {
        let file = item.get("file").and_then(Value::as_str).unwrap_or("电脑版插件");
        let format = item.get("binary_format").and_then(Value::as_str).unwrap_or("metadata");
        let architecture = item.get("architecture").and_then(Value::as_str).unwrap_or("");
        let strings = item.get("strings").and_then(Value::as_array)
            .map(|values| values.iter().filter_map(Value::as_str).take(24).collect::<Vec<_>>().join(" | "))
            .unwrap_or_default();
        format!("\n[{file}] {format} / {architecture}\n{strings}")
    }).collect::<Vec<_>>().join("\n");
    let mut install_result = json!({
        "installed": installed_wasm,
        "panels": installed_panels,
        "loaded": loaded_wasm,
        "errors": compatibility_errors,
        "native_compatibility_matches": native_mappings.clone()
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
        "电脑插件包分析报告\n时间：{stamp}\n\n已安装效果模块：{wasm_count}\n已安装脚本交互面板：{panel_count}\n已导入脚本文件：{script_count}\n已归档素材和源码：{asset_count}\n已保存电脑原生插件原件：{native_count}\n已匹配内置兼容效果：{compatibility_match_count}\n{compatibility_summary}\n\n从电脑原生插件中提取的可读信息和参数线索：{metadata_summary}\n跳过文件：{skipped_count}\n\n说明：只有效果模块、模块文本，以及本应用兼容的脚本和面板会进入对应导入流程。\n.aex/.dll/.ofx/.plugin 等原生二进制仅保存为待移植原件，不会在安卓设备上执行。若文件名匹配到内置兼容效果，报告会列出替代效果；替代效果并非原厂插件。\n.cube 文件可通过内置“应用颜色查找表”效果加载；.3dl/.csp/.spi1d/.spi3d/.spimtx/.cc/.ccc/.cdl 和 .ocio 等色彩配置文件保留给内置色彩管理与文件变换流程读取。插件资源信息、.r、.rc、.rsrc、.plist 属性清单文件和已编译脚本文件会归档并提取可读字符串用于后续移植分析，但不会直接执行。纹理、字体和源码会作为素材保存，不会自动变成可运行插件。\n效果模块、脚本面板和素材存档目录位于：{}\n电脑版原生插件原件目录位于：{}\n",
        assets_dir.display(), originals_dir.display()
    );
    std::fs::write(&report_path, report)
        .map_err(|error| bad(CMD, format!("无法保存插件分析报告：{error}")))?;

    if let Some(object) = install_result.as_object_mut() {
        object.insert("desktop_scripts".into(), json!(script_names));
        object.insert("desktop_assets".into(), json!(asset_names));
        object.insert("desktop_native_requires_port".into(), json!(native_names));
        object.insert("desktop_native_compatibility_matches".into(), json!(native_mappings));
        object.insert("desktop_native_metadata".into(), json!(native_metadata));
        object.insert("desktop_skipped".into(), json!(skipped_names));
        object.insert("wat_result".into(), wat_result);
        object.insert("compatibility_report".into(), json!(report_path.to_string_lossy()));
    }
    let mut notice = format!(
        "电脑插件包分析完成：效果模块 {wasm_count} 个、脚本交互面板 {panel_count} 个、脚本文件 {script_count} 个、素材 {asset_count} 个"
    );
    if native_count > 0 {
        notice.push_str(&format!("；另有 {native_count} 个电脑原生插件需要移植，未在安卓执行"));
    }
    if compatibility_match_count > 0 {
        notice.push_str(&format!("；另匹配到 {compatibility_match_count} 个内置兼容效果"));
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
    marker = "EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_IMPORT_MENU_V1"
    if marker in source:
        print("Desktop AE script choice is already present in the unified import menu.")
        return

    # The menu no longer imports a separate DeepSeek APK/ZIP. It now only imports effect
    # plug-ins; the embedded DeepSeek model manager is opened from the AI assistant itself.
    state_with_ai = "    let mut import_wasm = false;\n    let mut import_ai = false;\n"
    state_without_ai = "    let mut import_wasm = false;\n"
    if state_with_ai in source:
        source = replace_once(
            source, state_with_ai,
            state_with_ai + "    let mut import_script = false;\n    let mut import_panel = false;\n",
            "toolbar import state",
        )
        keep_ai_flag = True
    elif state_without_ai in source:
        source = replace_once(
            source, state_without_ai,
            state_without_ai + "    let mut import_script = false;\n    let mut import_panel = false;\n",
            "toolbar import state",
        )
        keep_ai_flag = False
    else:
        raise SystemExit("Could not locate the WASM plug-in import state in the toolbar.")

    wasm_button = '''                if popup.button("导入电脑插件包或效果模块文件（.wasm、.wat、.zip）").clicked() {
                    import_wasm = true;
                }
'''
    script_buttons = '''                // EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_IMPORT_MENU_V1
                if popup.button("特效软件脚本（.jsx、.js）").clicked() {
                    import_script = true;
                }
                if popup.button("脚本交互面板（.jsx）").clicked() {
                    import_panel = true;
                }
'''
    source = replace_once(source, wasm_button, wasm_button + script_buttons, "desktop script menu item")

    if keep_ai_flag:
        old_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_ai;\n"
        new_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_ai && !import_script && !import_panel;\n"
    else:
        old_close = "        menu_open = popup_open && !close_menu && !import_wasm;\n"
        new_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_script && !import_panel;\n"
    source = replace_once(source, old_close, new_close, "desktop script menu close state")

    route_anchor = "    x + 84.0\n"
    routes = '''    if import_script {
        match crate::menus::invoke(app, ui.ctx(), "file.installScript", json!({})) {
            Ok(_) => app.ui.status = "脚本文件已导入；可在“文件 → 脚本”中使用。".into(),
            Err(error) => app.ui.status = error,
        }
    }
    if import_panel {
        match crate::menus::invoke(app, ui.ctx(), "file.installScriptUIPanel", json!({})) {
            Ok(_) => app.ui.status = "脚本交互面板已导入；可在“窗口”菜单中打开。".into(),
            Err(error) => app.ui.status = error,
        }
    }
'''
    source = replace_once(source, route_anchor, routes + route_anchor, "AE script installer route")
    path.write_text(source, encoding="utf-8")
    print("Added AE .jsx/.js import through EffectCraft's original script installer inside the unified plug-in entry.")


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
