#!/usr/bin/env python3
"""Add a real, draggable AE desktop-plug-in migration workflow to EffectCraft Android."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_MIGRATION_UI_V1"


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


RUST_SOURCE = r'''//! Android desktop After Effects plug-in migration and compatibility workflow.
//! The percentage is based on bytes actually decompressed and checked from the selected ZIP.
//! Native desktop binaries are never executed or falsely reported as converted.
use std::{
    fs::File,
    io::Read,
    path::Path,
    sync::mpsc::{self, Receiver, TryRecvError},
    thread,
};

use egui::{pos2, vec2};
use serde_json::{Value, json};
use zip::ZipArchive;

use crate::EffectcraftApp;

const MAX_ENTRIES: usize = 512;
const MAX_TOTAL_BYTES: u64 = 256 * 1024 * 1024;
const MAX_NATIVE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_MODULE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_SCRIPT_BYTES: u64 = 16 * 1024 * 1024;
const MAX_ASSET_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Clone)]
struct Pending {
    path: String,
    file_name: String,
    native_count: usize,
    total_bytes: u64,
    entries: usize,
}

struct ScanResult {
    files_scanned: usize,
    bytes_scanned: u64,
}

struct Finalizing {
    pending: Pending,
    scan: ScanResult,
}

struct Done {
    title: String,
    detail: String,
    successful: bool,
}

enum WorkerMessage {
    Progress { bytes: u64, total: u64, file: String },
    Finished(Result<ScanResult, String>),
}

struct Worker {
    pending: Pending,
    rx: Receiver<WorkerMessage>,
    bytes: u64,
    total: u64,
    current_file: String,
}

pub(crate) struct State {
    pending: Option<Pending>,
    worker: Option<Worker>,
    finalizing: Option<Finalizing>,
    done: Option<Done>,
}

impl Default for State {
    fn default() -> Self {
        Self { pending: None, worker: None, finalizing: None, done: None }
    }
}

/// Called after the Android file picker returns. Only ZIPs containing desktop-native plug-ins
/// open the migration dialog; ordinary WASM/WAT/script ZIPs keep their existing import path.
pub(crate) fn offer(app: &mut EffectcraftApp, path: &str) -> bool {
    if !Path::new(path).extension().is_some_and(|ext| ext.eq_ignore_ascii_case("zip")) {
        return false;
    }
    let Some(pending) = inspect_archive(path) else {
        return false;
    };
    app.plugin_migration = State {
        pending: Some(pending),
        worker: None,
        finalizing: None,
        done: None,
    };
    true
}

fn is_native(name: &str, extension: &str) -> bool {
    ["aex", "dll", "ofx", "so", "dylib", "plugin", "bundle", "prm", "8bf"]
        .contains(&extension)
        || name.to_ascii_lowercase().contains(".plugin/")
        || name.to_ascii_lowercase().contains(".ofx.bundle/")
}

fn kind(name: &str) -> Option<&'static str> {
    let extension = Path::new(name).extension()?.to_str()?.to_ascii_lowercase();
    if extension == "wasm" { Some("module") }
    else if extension == "wat" { Some("module") }
    else if extension == "jsx" { Some("panel") }
    else if extension == "js" { Some("script") }
    else if is_native(name, &extension) { Some("native") }
    else if [
        "cube", "3dl", "lut", "look", "csp", "spi1d", "spi3d", "spimtx", "cc", "ccc", "cdl", "ocio",
        "png", "jpg", "jpeg", "webp", "tif", "tiff", "exr", "ttf", "otf",
        "json", "xml", "txt", "md", "toml", "cmake", "mk", "sh", "py", "gradle",
        "glsl", "frag", "vert", "wgsl", "hlsl", "dctl", "metal",
        "fx", "osl", "h", "hpp", "c", "cpp", "rs", "sbsar",
    ].contains(&extension.as_str()) { Some("asset") }
    else { None }
}

fn per_file_limit(kind: &str) -> u64 {
    match kind {
        "module" => MAX_MODULE_BYTES,
        "panel" | "script" => MAX_SCRIPT_BYTES,
        "native" => MAX_NATIVE_BYTES,
        _ => MAX_ASSET_BYTES,
    }
}

fn inspect_archive(path: &str) -> Option<Pending> {
    let file = File::open(path).ok()?;
    let mut archive = ZipArchive::new(file).ok()?;
    if archive.len() > MAX_ENTRIES {
        return None;
    }
    let mut native_count = 0usize;
    let mut total_bytes = 0u64;
    let mut entries = 0usize;
    for index in 0..archive.len() {
        let entry = archive.by_index(index).ok()?;
        if entry.is_dir() { continue; }
        let name = entry.name().ok()?.into_owned();
        let Some(entry_kind) = kind(&name) else { continue };
        let size = entry.size();
        if size > per_file_limit(entry_kind) {
            return None;
        }
        total_bytes = total_bytes.checked_add(size)?;
        if total_bytes > MAX_TOTAL_BYTES {
            return None;
        }
        entries += 1;
        if entry_kind == "native" {
            native_count += 1;
        }
    }
    if native_count == 0 {
        return None;
    }
    Some(Pending {
        path: path.to_string(),
        file_name: Path::new(path).file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_else(|| "AE 插件包".into()),
        native_count,
        total_bytes,
        entries,
    })
}

fn scan_in_background(pending: Pending, tx: mpsc::Sender<WorkerMessage>) {
    let result = (|| -> Result<ScanResult, String> {
        let file = File::open(&pending.path).map_err(|e| format!("无法读取插件包：{e}"))?;
        let mut archive = ZipArchive::new(file).map_err(|e| format!("插件 ZIP 无效或已损坏：{e}"))?;
        if archive.len() > MAX_ENTRIES {
            return Err("插件包文件数量超过 512 个安全上限".into());
        }
        let total = pending.total_bytes.max(1);
        let mut scanned = 0u64;
        let mut files_scanned = 0usize;
        let mut buffer = [0u8; 64 * 1024];
        let mut last_report = 0u64;

        for index in 0..archive.len() {
            let mut entry = archive.by_index(index).map_err(|e| format!("无法读取 ZIP 条目：{e}"))?;
            if entry.is_dir() { continue; }
            let name = entry.name().map_err(|e| format!("无法读取 ZIP 文件名：{e}"))?.into_owned();
            let Some(entry_kind) = kind(&name) else { continue };
            if entry.size() > per_file_limit(entry_kind) {
                return Err(format!("文件超过安全上限：{name}"));
            }
            files_scanned += 1;
            loop {
                let count = entry.read(&mut buffer).map_err(|e| format!("检查文件 {name} 失败：{e}"))?;
                if count == 0 { break; }
                scanned = scanned.saturating_add(count as u64);
                if scanned.saturating_sub(last_report) >= 256 * 1024 {
                    last_report = scanned;
                    let _ = tx.send(WorkerMessage::Progress {
                        bytes: scanned.min(total),
                        total,
                        file: name.clone(),
                    });
                }
            }
            let _ = tx.send(WorkerMessage::Progress {
                bytes: scanned.min(total),
                total,
                file: name,
            });
        }
        if scanned > MAX_TOTAL_BYTES {
            return Err("插件包解压总量超过 256 MB 安全上限".into());
        }
        Ok(ScanResult { files_scanned, bytes_scanned: scanned })
    })();
    let _ = tx.send(WorkerMessage::Finished(result));
}

fn start_worker(state: &mut State, pending: Pending) {
    let (tx, rx) = mpsc::channel();
    let task = pending.clone();
    thread::spawn(move || scan_in_background(task, tx));
    state.worker = Some(Worker {
        total: pending.total_bytes.max(1),
        pending,
        rx,
        bytes: 0,
        current_file: String::new(),
    });
}

fn array_len(value: &Value, key: &str) -> usize {
    value.get(key).and_then(Value::as_array).map_or(0, Vec::len)
}

fn compatibility_mapping_details(value: &Value) -> Vec<String> {
    value.get("desktop_native_compatibility_matches")
        .or_else(|| value.get("native_compatibility_matches"))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| {
            let source = item.get("source")?.as_str()?;
            let effect = item.get("effect_name")?.as_str()?;
            Some(format!("{source} → {effect}"))
        })
        .collect()
}

fn result_from_import(pending: Pending, scan: ScanResult, result: Result<Value, String>) -> Done {
    let value = match result {
        Ok(value) => value,
        Err(error) => {
            return Done {
                title: "移植失败".into(),
                detail: format!("插件包检查完成（{} 个文件，{} 字节），但 EffectCraft 无法安装其中的兼容组件。\n原因：{error}\n原生 .aex/.dll/.ofx 文件不会在 Android 上执行。", scan.files_scanned, scan.bytes_scanned),
                successful: false,
            };
        }
    };
    let wasm = array_len(&value, "installed");
    let panels = array_len(&value, "panels");
    let scripts = array_len(&value, "desktop_scripts");
    let compatible = array_len(&value, "desktop_native_compatibility_matches")
        .max(array_len(&value, "native_compatibility_matches"));
    let native_remaining = pending.native_count.saturating_sub(compatible);
    let errors = array_len(&value, "errors");
    let skipped = array_len(&value, "desktop_skipped");
    let usable = wasm + panels + scripts + compatible;
    let successful = usable > 0;
    let partial = native_remaining > 0 || errors > 0 || skipped > 0;
    let title = if !successful {
        "移植未成功".to_string()
    } else if partial {
        "部分导入完成".to_string()
    } else {
        "兼容导入完成".to_string()
    };
    let mut detail = format!(
        "已检查 {} 个文件（{} 字节）。\nWASM 效果插件：{} 个\nAE 脚本面板：{} 个\nAE 脚本：{} 个\n内置兼容替代效果：{} 个",
        scan.files_scanned, scan.bytes_scanned, wasm, panels, scripts, compatible
    );
    if native_remaining > 0 {
        detail.push_str(&format!("\n仍需专门移植的电脑版原生插件：{} 个", native_remaining));
    }
    if errors > 0 {
        detail.push_str(&format!("\n导入/兼容错误：{} 项", errors));
    }
    if skipped > 0 {
        detail.push_str(&format!("\n未导入或跳过的文件：{} 个", skipped));
    }
    let mappings = compatibility_mapping_details(&value);
    if !mappings.is_empty() {
        detail.push_str("\n\n已识别的安卓兼容效果：\n");
        detail.push_str(&mappings.iter().take(16).cloned().collect::<Vec<_>>().join("\n"));
        if mappings.len() > 16 {
            detail.push_str(&format!("\n另有 {} 项匹配", mappings.len() - 16));
        }
    }
    detail.push_str("\n\n说明：.aex/.dll/.ofx 等 Windows/macOS 原生插件不能直接在 Android 执行；匹配到的兼容效果是替代实现，不是原厂插件。");
    if successful {
        detail.push_str("\n可加载的 WASM 插件已注册到 EffectCraft；点击 OK 关闭窗口。");
    } else {
        detail.push_str("\n没有发现可在当前 APK 中加载的插件或兼容实现；原始文件仅保留供后续专门移植。");
    }
    Done { title, detail, successful }
}

fn poll_worker(state: &mut State, ctx: &egui::Context) {
    let mut completed: Option<(Pending, Result<ScanResult, String>)> = None;
    let mut disconnected = false;
    if let Some(worker) = state.worker.as_mut() {
        loop {
            match worker.rx.try_recv() {
                Ok(WorkerMessage::Progress { bytes, total, file }) => {
                    worker.bytes = bytes;
                    worker.total = total.max(1);
                    worker.current_file = file;
                    ctx.request_repaint();
                }
                Ok(WorkerMessage::Finished(result)) => {
                    completed = Some((worker.pending.clone(), result));
                    break;
                }
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    disconnected = true;
                    break;
                }
            }
        }
    }
    if let Some((pending, result)) = completed {
        state.worker = None;
        match result {
            Ok(scan) => {
                state.finalizing = Some(Finalizing { pending, scan });
                ctx.request_repaint();
            }
            Err(error) => {
                state.done = Some(Done {
                    title: "移植检查失败".into(),
                    detail: format!("无法完成插件包检查：{error}\n未将原生电脑版插件标记为成功。"),
                    successful: false,
                });
            }
        }
    } else if disconnected {
        state.worker = None;
        state.done = Some(Done {
            title: "移植检查中断".into(),
            detail: "插件检查线程意外中断，未执行安装，也未将插件标记为成功。".into(),
            successful: false,
        });
    }
}

fn finalize(state: &mut State, app: &mut EffectcraftApp) {
    let Some(finalizing) = state.finalizing.take() else { return };
    // The archive has already been decompressed and checked off the UI thread. The original
    // EffectCraft loader performs the actual validation, registration and persistent install.
    let installed = app.session.execute(
        "effect.plugins.load",
        json!({"path": finalizing.pending.path}),
    ).map_err(|e| e.to_string());
    state.done = Some(result_from_import(finalizing.pending, finalizing.scan, installed));
}

pub(crate) fn show(app: &mut EffectcraftApp, root: &mut egui::Ui) {
    let ctx = root.ctx().clone();
    let finalize_from_previous_frame = app.plugin_migration.finalizing.is_some();
    poll_worker(&mut app.plugin_migration, &ctx);
    if finalize_from_previous_frame {
        finalize(&mut app.plugin_migration, app);
    }

    let mut start = false;
    let mut cancel = false;
    if let Some(pending) = app.plugin_migration.pending.as_ref() {
        let mut open = true;
        egui::Window::new("AE 电脑版插件移植")
            .id(egui::Id::new("effectcraft-ae-migration-confirm"))
            .order(egui::Order::Foreground)
            .movable(true)
            .collapsible(false)
            .resizable(false)
            .default_pos(ctx.content_rect().center() - vec2(170.0, 90.0))
            .default_width(330.0)
            .open(&mut open)
            .show(&ctx, |ui| {
                ui.label(format!("检测到 {} 个电脑版原生插件文件。", pending.native_count));
                ui.label(format!("文件包：{}", pending.file_name));
                ui.add_space(6.0);
                ui.label("点击开始后，EffectCraft 会检查插件包、导入可兼容的 WASM/AE 脚本与面板，并查找内置兼容替代效果。");
                ui.label("原生 .aex/.dll/.ofx 不能直接在 Android 执行；不支持的插件会明确列为未移植。");
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    if ui.button("取消").clicked() { cancel = true; }
                    if ui.button("开始移植").clicked() { start = true; }
                });
            });
        if !open || cancel {
            app.plugin_migration.pending = None;
        } else if start {
            if let Some(pending) = app.plugin_migration.pending.take() {
                start_worker(&mut app.plugin_migration, pending);
            }
        }
    }

    let mut close_done = false;
    if let Some(done) = app.plugin_migration.done.as_ref() {
        let mut open = true;
        egui::Window::new("AE 插件移植结果")
            .id(egui::Id::new("effectcraft-ae-migration-result"))
            .order(egui::Order::Foreground)
            .movable(true)
            .collapsible(false)
            .resizable(false)
            .default_pos(ctx.content_rect().center() - vec2(180.0, 120.0))
            .default_width(350.0)
            .open(&mut open)
            .show(&ctx, |ui| {
                ui.heading(&done.title);
                ui.label(&done.detail);
                if done.successful {
                    ui.colored_label(egui::Color32::from_rgb(40, 160, 100), "可用兼容组件已加入 EffectCraft。");
                }
                ui.add_space(8.0);
                if ui.button("OK").clicked() { close_done = true; }
            });
        if close_done || !open {
            app.plugin_migration.done = None;
        }
    } else if let Some(worker) = app.plugin_migration.worker.as_ref() {
        let fraction = (worker.bytes.min(worker.total) as f64 / worker.total.max(1) as f64) as f32;
        let percent = (fraction * 100.0).round() as u8;
        egui::Window::new("AE 插件移植进度")
            .id(egui::Id::new("effectcraft-ae-migration-progress"))
            .order(egui::Order::Foreground)
            .movable(true)
            .collapsible(false)
            .resizable(false)
            .default_pos(ctx.content_rect().center() - vec2(170.0, 90.0))
            .default_width(330.0)
            .show(&ctx, |ui| {
                ui.label("正在读取、解压并检查插件包内容…");
                ui.add(egui::ProgressBar::new(fraction).desired_width(280.0).show_percentage());
                ui.strong(format!("{percent}%"));
                if !worker.current_file.is_empty() {
                    ui.small(format!("当前文件：{}", worker.current_file));
                }
                ui.small("百分比根据实际读取并检查的文件字节数计算。");
            });
        ctx.request_repaint_after(std::time::Duration::from_millis(100));
    } else if app.plugin_migration.finalizing.is_some() {
        egui::Window::new("AE 插件移植")
            .id(egui::Id::new("effectcraft-ae-migration-finalizing"))
            .order(egui::Order::Foreground)
            .movable(true)
            .collapsible(false)
            .resizable(false)
            .default_pos(ctx.content_rect().center() - vec2(170.0, 70.0))
            .default_width(330.0)
            .show(&ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.spinner();
                    ui.label("检查完成，正在验证并安装兼容插件…");
                });
                ui.small("只有实际通过 EffectCraft 加载验证的组件才会报告为成功。");
            });
        ctx.request_repaint();
    }
}
'''


def patch(root: Path) -> None:
    ui = root / "crates/ui-egui"
    manifest = ui / "Cargo.toml"
    source = manifest.read_text(encoding="utf-8")
    source = once(source, "image = { workspace = true }\n",
                  "image = { workspace = true }\nzip = { workspace = true }\n",
                  "UI ZIP reader dependency")
    manifest.write_text(source, encoding="utf-8")

    lib = ui / "src/lib.rs"
    source = lib.read_text(encoding="utf-8")
    source = once(source, "pub mod prefs_live;\n",
                  "pub mod prefs_live;\npub(crate) mod plugin_migration;\n",
                  "plugin migration module")
    field_anchor = "    pub(crate) crypto_probe_busy: Arc<std::sync::atomic::AtomicBool>,\n"
    source = once(source, field_anchor,
                  field_anchor + "    /// Desktop AE plug-in migration workflow and truthful progress/result dialogs.\n    pub(crate) plugin_migration: plugin_migration::State,\n",
                  "plugin migration app state")
    lib.write_text(source, encoding="utf-8")

    app = ui / "src/app.rs"
    source = app.read_text(encoding="utf-8")
    source = once(source, "            crypto_probe_busy: Default::default(),\n",
                  "            crypto_probe_busy: Default::default(),\n            plugin_migration: plugin_migration::State::default(),\n",
                  "plugin migration app initialization")
    app.write_text(source, encoding="utf-8")

    header = ui / "src/header.rs"
    source = header.read_text(encoding="utf-8")
    source = once(source, "    right_side(app, ui, &p, rect, x, cy);\n}",
                  "    right_side(app, ui, &p, rect, x, cy);\n    crate::plugin_migration::show(app, ui);\n}",
                  "plugin migration dialog rendering")
    header.write_text(source, encoding="utf-8")

    frontend = ui / "src/menus/frontend.rs"
    source = frontend.read_text(encoding="utf-8")
    anchor = "    p.insert(key.to_string(), v);\n"
    interception = """    p.insert(key.to_string(), v);
    // EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_MIGRATION_INTERCEPT_V1
    if id == "effect.plugins.load"
        && let Some(path) = p.get("path").and_then(Value::as_str)
        && crate::plugin_migration::offer(app, path)
    {
        return Ok(json!({"dialog": "plugin.migration"}));
    }
"""
    source = once(source, anchor, interception, "desktop plug-in migration confirmation interception")
    frontend.write_text(source, encoding="utf-8")

    migration = ui / "src/plugin_migration.rs"
    if migration.exists():
        existing = migration.read_text(encoding="utf-8")
        if MARKER not in existing:
            raise SystemExit("plugin_migration.rs already exists without the migration marker; refusing to overwrite.")
    migration.write_text("// " + MARKER + "\n" + RUST_SOURCE, encoding="utf-8")
    print("Added centered draggable AE plug-in migration, byte-based progress, real loader validation, and truthful result/OK dialogs.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch(root)


if __name__ == "__main__":
    main()
