#!/usr/bin/env python3
"""Add draggable, progress-tracked migration UI for desktop AE ZIP plug-ins."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_AE_PLUGIN_MIGRATION_PROGRESS_V1"

MODULE = r'''//! Draggable After Effects desktop-plug-in migration flow for Android.
use std::{
    fs::File,
    io::Read,
    path::Path,
    sync::{
        atomic::{AtomicUsize, Ordering},
        mpsc::{self, Receiver, TryRecvError},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};

use egui::{pos2, Id, Order};
use serde_json::{json, Value};
use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};

use crate::EffectcraftApp;

const MAX_ENTRIES: usize = 512;
const MAX_TOTAL_BYTES: u64 = 256 * 1024 * 1024;
const MAX_ENTRY_BYTES: u64 = 64 * 1024 * 1024;
const SCAN_PROGRESS_MAX: usize = 9_000;

pub(crate) enum ImportState {
    Confirm { path: String, native_count: usize },
    Running {
        path: String,
        progress: Arc<AtomicUsize>,
        receiver: Receiver<Result<ScanReport, String>>,
    },
    ProgressComplete {
        title: String,
        message: String,
        success: bool,
        since: Instant,
    },
    Result { title: String, message: String, success: bool },
}

struct ScanReport {
    file_count: usize,
    native_count: usize,
    native_names: Vec<String>,
    total_bytes: u64,
}

/// Called when the existing effect.plugins.load picker returns a ZIP. Only desktop
/// archives containing native plug-in binaries are diverted into the migration dialog.
pub(crate) fn intercept_if_native(app: &mut EffectcraftApp, path: &str) -> bool {
    // The migration dialog calls the same original loader after its scan. While the dialog is
    // active, let that internal call pass straight through instead of opening itself again.
    if app.plugin_import.is_some() {
        return false;
    }
    let source = Path::new(path);
    let is_zip = source.extension().is_some_and(|ext| ext.eq_ignore_ascii_case("zip"));
    let import_path = if is_zip {
        let Ok(file) = File::open(path) else { return false };
        let Ok(mut archive) = ZipArchive::new(file) else { return false };
        let mut native_count = 0usize;
        for index in 0..archive.len() {
            let Ok(entry) = archive.by_index(index) else { continue };
            if entry.is_dir() { continue; }
            let Ok(entry_name) = entry.name() else { continue };
            let entry_name = entry_name.into_owned();
            let name = entry_name.to_ascii_lowercase();
            let extension = Path::new(&entry_name).extension().and_then(|value| value.to_str()).unwrap_or_default().to_ascii_lowercase();
            let is_native = ["aex", "dll", "ofx", "so", "dylib", "plugin", "bundle", "prm", "8bf"].contains(&extension.as_str())
                || name.contains(".plugin/") || name.contains(".ofx.bundle/");
            if is_native { native_count += 1; }
        }
        if native_count == 0 { return false; }
        (path.to_string(), native_count)
    } else {
        // Also accept a single native desktop plug-in file from the Android picker.
        let extension = source.extension().and_then(|value| value.to_str()).unwrap_or_default().to_ascii_lowercase();
        if !["aex", "dll", "ofx", "so", "dylib", "plugin", "bundle", "prm", "8bf"].contains(&extension.as_str()) {
            return false;
        }
        let Ok(metadata) = std::fs::metadata(path) else { return false };
        if metadata.len() == 0 || metadata.len() > MAX_ENTRY_BYTES { return false; }
        let Some(file_name) = source.file_name().map(|v| v.to_string_lossy().into_owned()) else { return false };
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let temp_path = std::env::temp_dir().join(format!("effectcraft-desktop-plugin-{stamp}.zip"));
        let Ok(mut input) = File::open(path) else { return false };
        let Ok(output) = File::create(&temp_path) else { return false };
        let mut writer = ZipWriter::new(output);
        if writer.start_file(&file_name, SimpleFileOptions::default()).is_err()
            || std::io::copy(&mut input, &mut writer).is_err()
            || writer.finish().is_err()
        {
            let _ = std::fs::remove_file(&temp_path);
            return false;
        }
        (temp_path.to_string_lossy().into_owned(), 1)
    };
    app.plugin_import = Some(ImportState::Confirm {
        path: import_path.0,
        native_count: import_path.1,
    });
    true
}

fn spawn_scan(path: String) -> ImportState {
    let progress = Arc::new(AtomicUsize::new(0));
    let worker_progress = Arc::clone(&progress);
    let worker_path = path.clone();
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let result = scan_archive(&worker_path, &worker_progress);
        let _ = sender.send(result);
    });
    ImportState::Running { path, progress, receiver }
}

/// Read and validate the actual ZIP entries off the UI thread. The progress value measures
/// uncompressed bytes scanned, not elapsed time or a cosmetic timer.
fn scan_archive(path: &str, progress: &AtomicUsize) -> Result<ScanReport, String> {
    let file = File::open(path).map_err(|error| format!("无法读取插件压缩包：{error}"))?;
    let mut archive = ZipArchive::new(file).map_err(|error| format!("插件 ZIP 无效或已损坏：{error}"))?;
    if archive.len() > MAX_ENTRIES {
        return Err(format!("压缩包包含 {} 个条目，超过安全上限 {MAX_ENTRIES}", archive.len()));
    }

    let mut total_bytes = 0u64;
    for index in 0..archive.len() {
        let entry = archive.by_index(index).map_err(|error| format!("读取 ZIP 目录失败：{error}"))?;
        if entry.is_dir() { continue; }
        let entry_name = entry.name().map(|name| name.into_owned()).map_err(|error| format!("读取 ZIP 文件名失败：{error}"))?;
        let size = entry.size();
        if size > MAX_ENTRY_BYTES {
            return Err(format!("文件 {entry_name} 超过 64 MB 单文件安全上限"));
        }
        total_bytes = total_bytes.checked_add(size).ok_or_else(|| "插件包大小计算溢出".to_string())?;
        if total_bytes > MAX_TOTAL_BYTES {
            return Err("插件包解压总量超过 256 MB 安全上限".into());
        }
    }

    let mut file_count = 0usize;
    let mut native_count = 0usize;
    let mut native_names = Vec::new();
    let mut completed_bytes = 0u64;
    let mut buffer = [0u8; 64 * 1024];
    let entries = archive.len();
    for index in 0..entries {
        let mut entry = archive.by_index(index).map_err(|error| format!("读取 ZIP 文件失败：{error}"))?;
        if entry.is_dir() { continue; }
        file_count += 1;
        let entry_name = entry.name().map(|name| name.into_owned()).map_err(|error| format!("读取 ZIP 文件名失败：{error}"))?;
        let lower = entry_name.to_ascii_lowercase();
        let extension = Path::new(&entry_name).extension().and_then(|value| value.to_str()).unwrap_or_default().to_ascii_lowercase();
        let is_native = ["aex", "dll", "ofx", "so", "dylib", "plugin", "bundle", "prm", "8bf"].contains(&extension.as_str())
            || lower.contains(".plugin/") || lower.contains(".ofx.bundle/");
        if is_native {
            native_count += 1;
            if native_names.len() < 8 { native_names.push(entry_name.clone()); }
        }
        loop {
            let read = entry.read(&mut buffer).map_err(|error| format!("扫描 {entry_name} 失败：{error}"))?;
            if read == 0 { break; }
            completed_bytes = completed_bytes.saturating_add(read as u64);
            if completed_bytes > MAX_TOTAL_BYTES {
                return Err("实际解压数据超过 256 MB 安全上限".into());
            }
            let value = if total_bytes > 0 {
                ((completed_bytes.saturating_mul(SCAN_PROGRESS_MAX as u64) / total_bytes).min(SCAN_PROGRESS_MAX as u64)) as usize
            } else if entries > 0 {
                (((index + 1) * SCAN_PROGRESS_MAX) / entries).min(SCAN_PROGRESS_MAX)
            } else { SCAN_PROGRESS_MAX };
            progress.store(value, Ordering::Release);
        }
    }
    progress.store(SCAN_PROGRESS_MAX, Ordering::Release);
    Ok(ScanReport { file_count, native_count, native_names, total_bytes })
}

fn value_count(value: &Value, key: &str) -> usize {
    value.get(key).and_then(Value::as_array).map_or(0, |items| items.len())
}

fn result_summary(scan: &ScanReport, value: &Value) -> (String, String, bool) {
    let wasm = value_count(value, "loaded");
    let wat = value.get("wat_result").map_or(0, |item| value_count(item, "loaded"));
    let panels = value_count(value, "panels");
    let scripts = value_count(value, "desktop_scripts");
    let assets = value_count(value, "desktop_assets");
    let matched = value_count(value, "desktop_native_compatibility_matches");
    let native_unmatched = scan.native_count.saturating_sub(matched);
    let errors = value_count(value, "errors");
    let skipped = value_count(value, "desktop_skipped");
    let installed = wasm + wat + panels + scripts;
    let success = installed > 0 || matched > 0;

    let mut lines = vec![format!("已扫描 {} 个文件，共 {:.1} MB。", scan.file_count, scan.total_bytes as f64 / (1024.0 * 1024.0))];
    lines.push(format!("可用模块：WASM {wasm} 个、WAT {wat} 个、AE 面板 {panels} 个、脚本 {scripts} 个。"));
    if assets > 0 { lines.push(format!("另行保存素材/源码 {assets} 个。")); }
    if matched > 0 {
        lines.push(format!("匹配到 {matched} 个内置兼容效果。它们是兼容重实现/近似效果，不是原厂 AE 插件。"));
        if let Some(items) = value.get("desktop_native_compatibility_matches").and_then(Value::as_array) {
            for item in items.iter().take(16) {
                let source = item.get("source").and_then(Value::as_str).unwrap_or("电脑插件");
                let effect = item.get("effect_name").and_then(Value::as_str).unwrap_or("安卓兼容效果");
                lines.push(format!("{source} → {effect}"));
            }
            if items.len() > 16 { lines.push(format!("另有 {} 项效果映射。", items.len() - 16)); }
        }
    }
    if let Some(items) = value.get("desktop_native_metadata").and_then(Value::as_array) {
        let mut shown = 0usize;
        for item in items.iter().take(8) {
            let file = item.get("file").and_then(Value::as_str).unwrap_or("电脑插件");
            let strings = item.get("strings").and_then(Value::as_array)
                .map(|values| values.iter().filter_map(Value::as_str).take(8).collect::<Vec<_>>().join(" | "))
                .unwrap_or_default();
            if !strings.is_empty() {
                lines.push(format!("原插件元数据/参数线索 [{file}]：{strings}"));
                shown += 1;
            }
        }
        if shown > 0 {
            lines.push("以上字符串是静态分析线索，不代表已生成可调参数控件；需要针对对应效果继续移植。".into());
        }
    }
    let has_rsmb_compatibility = value
        .get("desktop_native_compatibility_matches")
        .and_then(Value::as_array)
        .is_some_and(|matches| matches.iter().any(|item| {
            item.get("effect_id").and_then(Value::as_str)
                == Some("org.effectcraft.compat.rsmb-motion-blur")
        }));
    if has_rsmb_compatibility {
        lines.push("RSMB 已匹配到“RSMB 风格方向模糊（非原版）”。它已加入效果列表，但不会自动添加到图层；请先把该效果添加到当前图层，再在右侧控件调整方向角度、模糊距离和效果强度。".into());
    }
    if native_unmatched > 0 {
        lines.push(format!("还有 {native_unmatched} 个电脑版原生插件无法自动移植；原件已归档，不会在 Android 上执行。"));
        if !scan.native_names.is_empty() {
            lines.push(format!("检测到的原生文件：{}。", scan.native_names.join("、")));
        }
    }
    if errors > 0 { lines.push(format!("有 {errors} 项兼容模块安装错误，请查看插件导入报告。")); }
    if skipped > 0 { lines.push(format!("有 {skipped} 个不支持或超限文件已跳过。")); }
    if let Some(report) = value.get("compatibility_report").and_then(Value::as_str) {
        lines.push(format!("详细报告：{report}"));
    }
    if !success {
        lines.insert(1, "没有安装任何可运行的兼容插件；仅保存原始文件不算移植成功。".into());
        ("移植失败".into(), lines.join("\n"), false)
    } else if native_unmatched > 0 || errors > 0 || skipped > 0 {
        ("移植部分完成".into(), lines.join("\n"), true)
    } else {
        ("移植成功".into(), lines.join("\n"), true)
    }
}

/// Draw the draggable confirmation, live progress, and final OK windows.
pub(crate) fn show(app: &mut EffectcraftApp, ctx: &egui::Context) {
    enum Action {
        Start(String),
        Cancel,
        Scanned(String, Result<ScanReport, String>),
        Close,
        Promote(String, String, bool),
    }
    let mut action: Option<Action> = None;

    if let Some(state) = app.plugin_import.as_mut() {
        match state {
            ImportState::Confirm { path, native_count } => {
                let mut open = true;
                let mut start = false;
                let mut cancel = false;
                let screen = ctx.content_rect();
                egui::Window::new("AE 电脑版插件移植")
                    .id(Id::new("effectcraft-ae-migration-confirm"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(false)
                    .default_width(330.0)
                    .default_pos(pos2(screen.center().x - 165.0, screen.center().y - 110.0))
                    .open(&mut open)
                    .show(ctx, |ui| {
                        ui.heading("检测到需要移植的电脑版插件");
                        ui.label(format!("发现 {native_count} 个 .aex / .dll / .ofx 等原生插件文件。"));
                        ui.add_space(4.0);
                        ui.label("点击开始后会扫描压缩包、检查安全性，并安装 EffectCraft 能兼容的模块或替代效果。无法兼容的原生插件会保留原件，不会伪装成已移植。 ");
                        ui.add_space(10.0);
                        ui.horizontal(|ui| {
                            if ui.button("取消").clicked() { cancel = true; }
                            if ui.button("开始移植").clicked() { start = true; }
                        });
                    });
                if start { action = Some(Action::Start(path.clone())); }
                else if cancel || !open { action = Some(Action::Cancel); }
            }
            ImportState::Running { path, progress, receiver } => {
                let fraction = (progress.load(Ordering::Acquire).min(SCAN_PROGRESS_MAX) as f32) / 10_000.0;
                let percent = (fraction * 100.0).round() as u32;
                let mut received = None;
                match receiver.try_recv() {
                    Ok(result) => received = Some(result),
                    Err(TryRecvError::Disconnected) => received = Some(Err("移植扫描线程意外中断".into())),
                    Err(TryRecvError::Empty) => {}
                }
                let screen = ctx.content_rect();
                egui::Window::new("AE 插件移植进度")
                    .id(Id::new("effectcraft-ae-migration-progress"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(false)
                    .default_width(330.0)
                    .default_pos(pos2(screen.center().x - 165.0, screen.center().y - 75.0))
                    .show(ctx, |ui| {
                        ui.label("正在扫描插件文件并检查可移植内容…");
                        ui.add(egui::ProgressBar::new(fraction).text(format!("{percent}%")));
                        ui.small("进度根据实际读取和解压的文件数据更新；完成扫描后会安装兼容模块。");
                    });
                ctx.request_repaint_after(Duration::from_millis(100));
                if let Some(result) = received { action = Some(Action::Scanned(path.clone(), result)); }
            }
            ImportState::ProgressComplete { title: _, message: _, success: _, since } => {
                let screen = ctx.content_rect();
                egui::Window::new("AE 插件移植进度")
                    .id(Id::new("effectcraft-ae-migration-progress"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(false)
                    .default_width(330.0)
                    .default_pos(pos2(screen.center().x - 165.0, screen.center().y - 75.0))
                    .show(ctx, |ui| {
                        ui.label("兼容模块安装与注册完成。");
                        ui.add(egui::ProgressBar::new(1.0).text("100%"));
                    });
                if since.elapsed() >= Duration::from_millis(180) {
                    if let ImportState::ProgressComplete { title, message, success, .. } = state {
                        action = Some(Action::Promote(title.clone(), message.clone(), *success));
                    }
                } else {
                    ctx.request_repaint_after(Duration::from_millis(80));
                }
            }
            ImportState::Result { title, message, success } => {
                let mut open = true;
                let mut close = false;
                let screen = ctx.content_rect();
                egui::Window::new(title.as_str())
                    .id(Id::new("effectcraft-ae-migration-result"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(false)
                    .default_width(340.0)
                    .default_pos(pos2(screen.center().x - 170.0, screen.center().y - 120.0))
                    .open(&mut open)
                    .show(ctx, |ui| {
                        ui.label(if *success { "插件移植处理已完成。" } else { "本次没有移植出可运行的兼容插件。" });
                        ui.add_space(6.0);
                        egui::ScrollArea::vertical().max_height(190.0).show(ui, |ui| {
                            ui.label(message.as_str());
                        });
                        ui.add_space(8.0);
                        if ui.button("OK").clicked() { close = true; }
                    });
                if close || !open { action = Some(Action::Close); }
            }
        }
    }

    match action {
        Some(Action::Start(path)) => app.plugin_import = Some(spawn_scan(path)),
        Some(Action::Cancel | Action::Close) => app.plugin_import = None,
        Some(Action::Scanned(path, result)) => match result {
            Err(error) => {
                app.plugin_import = Some(ImportState::Result { title: "移植失败".into(), message: error, success: false });
            }
            Ok(scan) => {
                // The existing importer validates and installs each supported module through
                // the original sandboxed Wasmi/script routes. 100% is displayed only after it returns.
                let temporary_archive = Path::new(&path).file_name()
                    .is_some_and(|name| name.to_string_lossy().starts_with("effectcraft-desktop-plugin-"));
                let import_result = crate::menus::invoke(app, ctx, "effect.plugins.load", json!({"path": path.clone()}));
                if temporary_archive {
                    let _ = std::fs::remove_file(&path);
                }
                match import_result {
                    Ok(value) => {
                        let (title, message, success) = result_summary(&scan, &value);
                        if success {
                            app.plugin_import = Some(ImportState::ProgressComplete { title, message, success, since: Instant::now() });
                        } else {
                            app.plugin_import = Some(ImportState::Result { title, message, success });
                        }
                    }
                    Err(error) => app.plugin_import = Some(ImportState::Result { title: "移植失败".into(), message: error, success: false }),
                }
            }
        },
        Some(Action::Promote(title, message, success)) => app.plugin_import = Some(ImportState::Result { title, message, success }),
        None => {}
    }
}
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")

    ui = root / "crates/ui-egui"
    lib_path = ui / "src/lib.rs"
    app_path = ui / "src/app.rs"
    header_path = ui / "src/header.rs"
    frontend_path = ui / "src/menus/frontend.rs"
    cargo_path = ui / "Cargo.toml"
    for path in (lib_path, app_path, header_path, frontend_path, cargo_path):
        if not path.is_file():
            raise SystemExit(f"Missing expected EffectCraft source file: {path}")

    module_path = ui / "src/plugin_migration.rs"
    if module_path.exists() and MARKER not in module_path.read_text(encoding="utf-8"):
        raise SystemExit(f"Refusing to overwrite an unexpected file: {module_path}")
    module_path.write_text(MODULE.replace("//! Draggable", "//! " + MARKER + "\n//! Draggable", 1), encoding="utf-8")

    source = lib_path.read_text(encoding="utf-8")
    source = replace_once(source, "mod pointer_wrap;\n", "mod pointer_wrap;\n#[cfg(not(target_arch = \"wasm32\"))]\nmod plugin_migration;\n", "migration module declaration")
    source = replace_once(
        source,
        "    pub(crate) dialog_state: panels::dialogs::DialogState,\n",
        "    pub(crate) dialog_state: panels::dialogs::DialogState,\n    #[cfg(not(target_arch = \"wasm32\"))]\n    pub(crate) plugin_import: Option<plugin_migration::ImportState>,\n",
        "migration state field",
    )
    lib_path.write_text(source, encoding="utf-8")

    source = app_path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "            dialog_state: Default::default(),\n",
        "            dialog_state: Default::default(),\n            #[cfg(not(target_arch = \"wasm32\"))]\n            plugin_import: None,\n",
        "migration state initialization",
    )
    app_path.write_text(source, encoding="utf-8")

    source = header_path.read_text(encoding="utf-8")
    migration_draw = "    #[cfg(not(target_arch = \"wasm32\"))]\n    crate::plugin_migration::show(app, ui.ctx());\n"
    if migration_draw not in source:
        patched_tail = (
            "    right_side(app, ui, &p, rect, x, cy);\n"
            "    export_dialog(app, ui);\n"
            "    export_progress_dialog(app, ui);\n}"
        )
        original_tail = "    right_side(app, ui, &p, rect, x, cy);\n}"
        if source.count(patched_tail) == 1:
            source = source.replace(patched_tail, patched_tail[:-1] + migration_draw + "}", 1)
        elif source.count(original_tail) == 1:
            source = source.replace(original_tail, original_tail[:-1] + migration_draw + "}", 1)
        else:
            raise SystemExit("migration windows draw call: expected one original or export-patched header tail")
    header_path.write_text(source, encoding="utf-8")

    source = frontend_path.read_text(encoding="utf-8")
    anchor = "    // Save (untitled) becomes Save As.\n    let id = if id == \"file.save\" { \"file.saveAs\" } else { id };\n"
    replacement = """    // EFFECTCRAFT_ANDROID_AE_PLUGIN_MIGRATION_PROGRESS_V1
    // Desktop ZIPs containing native AE binaries get a draggable migration confirmation
    // before the existing safe importer is invoked.
    #[cfg(not(target_arch = \"wasm32\"))]
    if id == \"effect.plugins.load\" {
        if let Some(path) = p.get(\"path\").and_then(Value::as_str) {
            if crate::plugin_migration::intercept_if_native(app, path) {
                return Ok(json!({\"dialog\": \"desktop-plugin-migration\"}));
            }
        }
    }
    // Save (untitled) becomes Save As.
    let id = if id == \"file.save\" { \"file.saveAs\" } else { id };\n"""
    source = replace_once(source, anchor, replacement, "desktop ZIP migration interception")
    frontend_path.write_text(source, encoding="utf-8")

    source = cargo_path.read_text(encoding="utf-8")
    if "zip = { workspace = true }" not in source:
        source = replace_once(source, "web-time = { workspace = true }\n", "web-time = { workspace = true }\nzip = { workspace = true }\n", "ZIP scan dependency")
        cargo_path.write_text(source, encoding="utf-8")

    # The APK workflow uses Cargo.lock with --locked; record the UI crate's new ZIP dependency.
    lock_path = root / "Cargo.lock"
    lock_source = lock_path.read_text(encoding="utf-8")
    package_start = lock_source.find('name = "effectcraft-ui-egui"\nversion = "0.21.1"\ndependencies = [')
    if package_start < 0:
        raise SystemExit("Could not locate effectcraft-ui-egui in Cargo.lock")
    package_end = lock_source.find("\n]\n", package_start)
    if package_end < 0:
        raise SystemExit("Could not locate effectcraft-ui-egui dependency list in Cargo.lock")
    dependency_block = lock_source[package_start:package_end]
    if '"zip 9.1.3"' not in dependency_block:
        dependency_block = replace_once(
            dependency_block,
            ' "web-time",',
            ' "web-time",\n "zip 9.1.3",',
            "Cargo.lock UI ZIP dependency",
        )
        lock_source = lock_source[:package_start] + dependency_block + lock_source[package_end:]
        lock_path.write_text(lock_source, encoding="utf-8")

    print("Added the draggable AE migration confirmation, real ZIP scan progress, 100% completion state, and final OK result window.")
    print("Only archives containing native desktop plug-in files enter this flow; ordinary WASM/WAT ZIP imports keep the original path.")


if __name__ == "__main__":
    main()
