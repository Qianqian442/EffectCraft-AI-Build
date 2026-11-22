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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum MigrationMode {
    AutoBest,
    CpuTranslation,
    ForceCompatibility,
    AggressivePort,
    ManualBackend,
}

impl MigrationMode {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::AutoBest => "自动推荐",
            Self::CpuTranslation => "转译",
            Self::ForceCompatibility => "强行兼容（内部阶段，不单独显示）",
            Self::AggressivePort => "反编译+暴力移植+强行兼容",
            Self::ManualBackend => "高级导入",
        }
    }

    pub(crate) fn description(self) -> &'static str {
        match self {
            Self::AutoBest => "分析插件格式、架构、依赖和可用候选路线；优先推荐已接入且通过实测的路线，没有通过测试的路线不会被标记为可用。",
            Self::CpuTranslation => "展示该插件适用的 CPU 转译候选路线，包括各路线的运行环境、前置条件和实测状态；未接入的路线只列为候选。",
            Self::ForceCompatibility => "组合路线内部的兼容处理阶段；不作为独立选项显示。",
            Self::AggressivePort => "按顺序尝试：反编译/静态重构分析 → 强行兼容（运行库、宿主接口、像素格式与渲染回退）→ 前述路线失败后再进行暴力移植兜底。每一阶段都必须记录真实执行状态；未接入或未通过测试的阶段明确标记为未完成，不得伪报成功。",
            Self::ManualBackend => "高级导入：分析后展示该插件全部适用的转译后端、所需运行环境和实测状态，供你比较与指定；尚未接入的后端只记录选择意向。",
        }
    }
}

pub(crate) enum ImportState {
    Confirm { path: String, native_count: usize, mode: MigrationMode },
    Running {
        path: String,
        mode: MigrationMode,
        progress: Arc<AtomicUsize>,
        receiver: Receiver<Result<ScanReport, String>>,
    },
    ProgressComplete {
        title: String,
        message: String,
        success: bool,
        since: Instant,
    },
    RouteSelection {
        title: String,
        message: String,
        success: bool,
        groups: Vec<NativeRouteGroup>,
        selected_routes: Vec<String>,
        path: String,
        temporary_archive: bool,
    },
    AexRuntimeTesting {
        title: String,
        message: String,
        success: bool,
        request_id: String,
        path: String,
        temporary_archive: bool,
    },
    Result { title: String, message: String, success: bool },
}

struct ScanReport {
    file_count: usize,
    native_count: usize,
    native_names: Vec<String>,
    total_bytes: u64,
}

#[derive(Clone)]
struct NativeRouteOption {
    id: String,
    backend: String,
    prerequisites: String,
    notes: String,
    status: String,
    score: Option<f64>,
}

#[derive(Clone)]
struct NativeRouteGroup {
    file: String,
    binary_format: String,
    architecture: String,
    routes: Vec<NativeRouteOption>,
    compatibility_profiles: Vec<String>,
}

fn route_groups(value: &Value) -> Vec<NativeRouteGroup> {
    value.get("desktop_native_metadata")
        .and_then(Value::as_array)
        .map(|items| items.iter().map(|item| {
            let routes = item.get("candidate_routes")
                .and_then(Value::as_array)
                .map(|routes| routes.iter().map(|route| NativeRouteOption {
                    id: route.get("id").and_then(Value::as_str).unwrap_or("").to_string(),
                    backend: route.get("backend").and_then(Value::as_str).unwrap_or("未命名路线").to_string(),
                    prerequisites: route.get("prerequisites").and_then(Value::as_str).unwrap_or("未提供前置条件").to_string(),
                    notes: route.get("notes").and_then(Value::as_str).unwrap_or("").to_string(),
                    status: route.get("status").and_then(Value::as_str).unwrap_or("未执行").to_string(),
                    score: route.get("score").and_then(Value::as_f64),
                }).collect())
                .unwrap_or_default();
            let compatibility_profiles = item.get("forced_compatibility_profiles")
                .and_then(Value::as_array)
                .map(|profiles| profiles.iter().map(|profile| {
                    let name = profile.get("name").and_then(Value::as_str).unwrap_or("兼容方案");
                    let actions = profile.get("actions").and_then(Value::as_array)
                        .map(|items| items.iter().filter_map(Value::as_str).collect::<Vec<_>>().join("；"))
                        .unwrap_or_default();
                    if actions.is_empty() { name.to_string() } else { format!("{name}：{actions}") }
                }).collect())
                .unwrap_or_default();
            NativeRouteGroup {
                file: item.get("file").and_then(Value::as_str).unwrap_or("电脑插件").to_string(),
                binary_format: item.get("binary_format").and_then(Value::as_str).unwrap_or("原生文件").to_string(),
                architecture: item.get("architecture").and_then(Value::as_str).unwrap_or("架构未知").to_string(),
                routes,
                compatibility_profiles,
            }
        }).collect())
        .unwrap_or_default()
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
        mode: MigrationMode::AutoBest,
    });
    true
}

fn spawn_scan(path: String, mode: MigrationMode) -> ImportState {
    let progress = Arc::new(AtomicUsize::new(0));
    let worker_progress = Arc::clone(&progress);
    let worker_path = path.clone();
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let result = scan_archive(&worker_path, &worker_progress);
        let _ = sender.send(result);
    });
    ImportState::Running { path, mode, progress, receiver }
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

fn result_summary(scan: &ScanReport, value: &Value, mode: MigrationMode) -> (String, String, bool) {
    let wasm = value_count(value, "loaded");
    let wat = value.get("wat_result").map_or(0, |item| value_count(item, "loaded"));
    let panels = value_count(value, "panels");
    let scripts = value_count(value, "desktop_scripts");
    let assets = value_count(value, "desktop_assets");
    let matched = value_count(value, "desktop_native_compatibility_matches");
    // A filename/effect-name match is only a substitute-effect hint, never proof that
    // the original desktop binary has been translated or hosted successfully.
    let native_translated = value.get("desktop_native_metadata")
        .and_then(Value::as_array)
        .map(|items| items.iter().filter(|item| {
            item.get("translation_executed").and_then(Value::as_bool) == Some(true)
                && item.get("trial_execution_status").and_then(Value::as_str) == Some("passed")
                && item.get("selected_route").is_some()
        }).count())
        .unwrap_or(0);
    let native_unmatched = scan.native_count.saturating_sub(native_translated);
    let errors = value_count(value, "errors");
    let skipped = value_count(value, "desktop_skipped");
    let installed = wasm + wat + panels + scripts;
    let success = installed > 0 || native_translated > 0;

    let mut lines = vec![
        format!("本次选择的移植方式：{}。", mode.label()),
        format!("已扫描 {} 个文件，共 {:.1} MB。", scan.file_count, scan.total_bytes as f64 / (1024.0 * 1024.0)),
    ];
    lines.push(format!("方式说明：{}", mode.description()));
    lines.push("注意：当前构建已加入方式选择和报告记录；Box64/Box86/FEX/QEMU/Wine 的实际运行时试跑、后端手动切换和暴力二进制重建引擎尚未集成，不会伪称已执行。".into());
    lines.push(format!("可用模块：WASM {wasm} 个、WAT {wat} 个、AE 面板 {panels} 个、脚本 {scripts} 个。"));
    if assets > 0 { lines.push(format!("另行保存素材/源码 {assets} 个。")); }
    if matched > 0 {
        lines.push(format!("匹配到 {matched} 个内置兼容替代效果。它们不是原厂 AE 插件，也不计入原生插件移植成功数量。"));
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
        // Show every detected native plug-in and every candidate route; do not hide
        // additional routes behind a short preview limit.
        for item in items.iter() {
            let file = item.get("file").and_then(Value::as_str).unwrap_or("电脑插件");
            let binary_format = item.get("binary_format").and_then(Value::as_str).unwrap_or("原生文件");
            let architecture = item.get("architecture").and_then(Value::as_str).unwrap_or("架构未知");
            lines.push(format!("原生文件 [{file}]：{binary_format} / {architecture}"));
            let backend = item.get("translation_backend").and_then(Value::as_str).unwrap_or("未确定");
            let target = item.get("target_abi").and_then(Value::as_str).unwrap_or("ARM64 / arm64-v8a");
            let status = item.get("translation_status").and_then(Value::as_str).unwrap_or("尚未执行 CPU 转译");
            let host = item.get("host_adapter").and_then(Value::as_str).unwrap_or("需适配插件宿主接口");
            lines.push(format!("CPU 转译路线：{backend} → {target}；{status}。"));
            lines.push(format!("插件宿主桥接：{host}。"));
            if let Some(selected) = item.get("selected_route") {
                let backend = selected.get("backend").and_then(Value::as_str).unwrap_or("最佳候选");
                let score = item.get("trial_score").and_then(Value::as_f64).unwrap_or(0.0);
                lines.push(format!("自动选优结果：{backend}；实测完整度 {:.1}/100。", score));
                lines.push("该方案只有在宿主接口、参数、预览/最终渲染、取消和稳定性硬性测试全部通过后才会被选中。".into());
            } else {
                lines.push("自动选优结果：暂无；当前没有真实运行并通过硬性测试的电脑原生插件转译方案。".into());
            }
            if let Some(routes) = item.get("candidate_routes").and_then(Value::as_array) {
                if !routes.is_empty() {
                    let names = routes.iter().filter_map(|route| route.get("backend").and_then(Value::as_str))
                        .collect::<Vec<_>>().join(" → ");
                    lines.push(format!("候选路线顺序（逐个试跑后比较）：{names}。"));
                    for route in routes.iter() {
                        let backend = route.get("backend").and_then(Value::as_str).unwrap_or("候选后端");
                        let status = route.get("status").and_then(Value::as_str).unwrap_or("未执行");
                        let score = route.get("score").and_then(Value::as_f64);
                        if let Some(score) = score {
                            lines.push(format!("试跑结果 {backend}：{status}；完整度评分 {:.1}/100。", score));
                        } else {
                            lines.push(format!("试跑结果 {backend}：{status}；尚无实测评分。"));
                        }
                    }
                    lines.push("只有实际运行并通过硬性测试的候选路线，才允许进入自动导入排名。".into());
                }
            }
            if let Some(profiles) = item.get("forced_compatibility_profiles").and_then(Value::as_array) {
                let names = profiles.iter().filter_map(|profile| profile.get("name").and_then(Value::as_str))
                    .collect::<Vec<_>>().join("、");
                if !names.is_empty() {
                    lines.push(format!("强制兼容候选方案：{names}。当前只记录方案，未对必需 API 作伪造或绕过授权。"));
                }
            }
            let strings = item.get("strings").and_then(Value::as_array)
                .map(|values| values.iter().filter_map(Value::as_str).take(8).collect::<Vec<_>>().join(" | "))
                .unwrap_or_default();
            if !strings.is_empty() {
                lines.push(format!("元数据/参数文字线索：{strings}"));
            }
            shown += 1;
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
        if scan.native_count > 0 {
            lines.insert(1, "已完成电脑插件架构与候选路线分析；尚无原生插件通过真实转译、宿主接口、参数和渲染测试。内置相似效果仅为替代方案，不算原插件移植。".into());
            ("已分析，原插件待移植".into(), lines.join("\n"), false)
        } else {
            lines.insert(1, "没有安装任何可运行的兼容插件；仅保存素材或脚本文件不算移植成功。".into());
            ("移植失败".into(), lines.join("\n"), false)
        }
    } else if native_unmatched > 0 || errors > 0 || skipped > 0 {
        if installed > 0 {
            ("部分内容已导入，电脑原生插件仍待移植".into(), lines.join("\n"), true)
        } else {
            ("电脑原生插件仍待移植".into(), lines.join("\n"), false)
        }
    } else {
        ("移植成功".into(), lines.join("\n"), true)
    }
}

/// Draw the draggable confirmation, live progress, and final OK windows.
pub(crate) fn show(app: &mut EffectcraftApp, ctx: &egui::Context) {
    enum Action {
        Start(String, MigrationMode),
        Cancel,
        Scanned(String, MigrationMode, Result<ScanReport, String>),
        Close,
        Promote(String, String, bool),
        RoutesConfirmed(String, String, bool, Vec<NativeRouteGroup>, Vec<String>, String, bool),
        AexTestComplete(String, String, bool, String, String, bool),
    }
    let mut action: Option<Action> = None;

    if let Some(state) = app.plugin_import.as_mut() {
        match state {
            ImportState::Confirm { path, native_count, mode } => {
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
                        ui.label("选择本次电脑插件移植方式；可按需切换，不会强制固定使用某一种转译器。");
                        ui.label("扫描完成后，结果页会展示检测到的每个插件的全部适用路线，不省略候选项。");
                        ui.radio_value(mode, MigrationMode::AutoBest, MigrationMode::AutoBest.label());
                        ui.radio_value(mode, MigrationMode::CpuTranslation, MigrationMode::CpuTranslation.label());
                        ui.radio_value(mode, MigrationMode::ManualBackend, MigrationMode::ManualBackend.label());
                        ui.radio_value(mode, MigrationMode::AggressivePort, MigrationMode::AggressivePort.label());
                        ui.small(mode.description());
                        ui.add_space(6.0);
                        ui.label("当前版本会分析架构、列出路线并保留原件；尚未接入的运行时/宿主接口会显示待实现，不会伪报成功。");
                        ui.add_space(10.0);
                        ui.horizontal(|ui| {
                            if ui.button("取消").clicked() { cancel = true; }
                            if ui.button("按此方式开始").clicked() { start = true; }
                        });
                    });
                if start { action = Some(Action::Start(path.clone(), *mode)); }
                else if cancel || !open { action = Some(Action::Cancel); }
            }
            ImportState::Running { path, mode, progress, receiver } => {
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
                if let Some(result) = received { action = Some(Action::Scanned(path.clone(), *mode, result)); }
            }
            ImportState::RouteSelection { title, message, success, groups, selected_routes, path, temporary_archive } => {
                let mut open = true;
                let mut confirm = false;
                let screen = ctx.content_rect();
                egui::Window::new("选择电脑插件移植路线")
                    .id(Id::new("effectcraft-ae-migration-route-selection"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(true)
                    .default_width(390.0)
                    .default_pos(pos2(screen.center().x - 195.0, screen.center().y - 190.0))
                    .open(&mut open)
                    .show(ctx, |ui| {
                        ui.heading("选择自动优选或手动指定路线");
                        ui.label("下面完整列出每个电脑插件适用的路线，不会只显示部分候选项。每个插件可单独选择。");
                        ui.add_space(6.0);
                        egui::ScrollArea::vertical().max_height(390.0).show(ui, |ui| {
                            for (index, group) in groups.iter().enumerate() {
                                ui.group(|ui| {
                                    ui.strong(&group.file);
                                    ui.small(format!("{} · {}", group.binary_format, group.architecture));
                                    if let Some(choice) = selected_routes.get_mut(index) {
                                        ui.radio_value(
                                            choice,
                                            String::new(),
                                            "自动优选：真实试跑后选择完整度最高且通过测试的路线",
                                        );
                                        if group.routes.is_empty() {
                                            ui.label("当前未识别到可直接尝试的 CPU 转译路线。");
                                        }
                                        for route in group.routes.iter() {
                                            let label = if let Some(score) = route.score {
                                                format!("{}（{} · {:.1}/100）", route.backend, route.status, score)
                                            } else {
                                                format!("{}（{} · 暂无实测分数）", route.backend, route.status)
                                            };
                                            ui.radio_value(choice, route.id.clone(), label);
                                            ui.small(format!("前置条件：{}", route.prerequisites));
                                            if !route.notes.is_empty() {
                                                ui.small(format!("说明：{}", route.notes));
                                            }
                                        }
                                    }
                                    if !group.compatibility_profiles.is_empty() {
                                        ui.separator();
                                        ui.strong("强制兼容 / 暴力移植子方案（全部展示）");
                                        for profile in group.compatibility_profiles.iter() {
                                            ui.small(format!("• {profile}"));
                                        }
                                    }
                                });
                                ui.add_space(6.0);
                            }
                        });
                        ui.add_space(6.0);
                        ui.small("AEX 原生插件可在已安装的隔离 Windows 环境中实测 FEXCore / Box64；Remill、Ghidra、Box86、QEMU 等其他路线仍按各自状态显示，不会伪报已执行。");
                        ui.add_space(8.0);
                        if ui.button("确认选择并查看移植报告").clicked() { confirm = true; }
                    });
                if confirm || !open {
                    action = Some(Action::RoutesConfirmed(
                        title.clone(),
                        message.clone(),
                        *success,
                        groups.clone(),
                        selected_routes.clone(),
                        path.clone(),
                        *temporary_archive,
                    ));
                }
            }
            ImportState::AexRuntimeTesting { title, message, success, request_id, path, temporary_archive } => {
                let status = match crate::poll_windows_compat_runtime_install(request_id) {
                    Ok(Some(value)) => value,
                    Ok(None) => "正在等待隔离 AEX 宿主返回状态…".to_string(),
                    Err(error) => format!("ERROR: {error}"),
                };
                let finished = status.starts_with("EXIT:") || status.starts_with("ERROR:");
                let screen = ctx.content_rect();
                egui::Window::new("Adobe AEX 原生插件实测")
                    .id(Id::new("effectcraft-aex-runtime-testing"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(true)
                    .default_width(370.0)
                    .default_pos(pos2(screen.center().x - 185.0, screen.center().y - 110.0))
                    .show(ctx, |ui| {
                        ui.label("正在隔离测试插件加载、参数往返与重复 CPU 帧渲染。");
                        ui.add_space(6.0);
                        ui.spinner();
                        egui::ScrollArea::vertical().max_height(220.0).show(ui, |ui| {
                            ui.label(status.as_str());
                        });
                    });
                if finished {
                    action = Some(Action::AexTestComplete(
                        title.clone(), message.clone(), *success, status, path.clone(), *temporary_archive
                    ));
                } else {
                    ctx.request_repaint_after(Duration::from_millis(300));
                }
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
        Some(Action::Start(path, mode)) => {
            app.ui.status = "已开始扫描电脑插件；正在识别架构和可用路线…".into();
            app.plugin_import = Some(spawn_scan(path, mode));
        }
        Some(Action::Cancel) => {
            app.ui.status = "已取消电脑插件移植；未执行本次导入。".into();
            app.plugin_import = None;
        }
        Some(Action::Close) => {
            app.ui.status = "已关闭电脑插件移植报告。".into();
            app.plugin_import = None;
        }
        Some(Action::Scanned(path, mode, result)) => match result {
            Err(error) => {
                app.plugin_import = Some(ImportState::Result { title: "移植失败".into(), message: error, success: false });
            }
            Ok(scan) => {
                // The existing importer validates and installs each supported module through
                // the original sandboxed Wasmi/script routes. 100% is displayed only after it returns.
                let temporary_archive = Path::new(&path).file_name()
                    .is_some_and(|name| name.to_string_lossy().starts_with("effectcraft-desktop-plugin-"));
                let import_result = crate::menus::invoke(app, ctx, "effect.plugins.load", json!({"path": path.clone()}));
                match import_result {
                    Ok(value) => {
                        let (title, message, success) = result_summary(&scan, &value, mode);
                        let groups = route_groups(&value);
                        if !groups.is_empty() {
                            let selected_routes = vec![String::new(); groups.len()];
                            app.plugin_import = Some(ImportState::RouteSelection {
                                title,
                                message,
                                success,
                                groups,
                                selected_routes,
                                path: path.clone(),
                                temporary_archive,
                            });
                        } else {
                            if temporary_archive { let _ = std::fs::remove_file(&path); }
                            if success {
                                app.plugin_import = Some(ImportState::ProgressComplete { title, message, success, since: Instant::now() });
                            } else {
                                app.plugin_import = Some(ImportState::Result { title, message, success });
                            }
                        }
                    }
                    Err(error) => {
                        if temporary_archive { let _ = std::fs::remove_file(&path); }
                        app.plugin_import = Some(ImportState::Result { title: "移植失败".into(), message: error, success: false });
                    }
                }
            }
        },
        Some(Action::Promote(title, message, success)) => {
            app.ui.status = "电脑插件扫描和兼容内容处理已完成；请查看结果报告。".into();
            app.plugin_import = Some(ImportState::Result { title, message, success });
        },
        Some(Action::RoutesConfirmed(title, message, success, groups, selected_routes, path, temporary_archive)) => {
            app.ui.status = "已完成路线选择；正在启动适用的隔离 AEX 实测…".into();
            let mut final_message = message;
            final_message.push_str("\n\n本次路线选择记录：");
            let mut chosen_backend: Option<&str> = None;
            let mut backend_conflict = false;
            let mut has_aex = false;
            for (index, group) in groups.iter().enumerate() {
                let selected = selected_routes.get(index).map(String::as_str).unwrap_or("");
                has_aex |= Path::new(&group.file).extension().is_some_and(|ext| ext.eq_ignore_ascii_case("aex"));
                if selected.is_empty() {
                    if let Some(best) = group.routes.iter().find(|route| route.status == "passed" && route.score.is_some()) {
                        final_message.push_str(&format!("\n{}：自动优选为 {}（实测 {:.1}/100）。", group.file, best.backend, best.score.unwrap_or_default()));
                    } else {
                        final_message.push_str(&format!("\n{}：选择自动比较；对已接入的 AEX 后端将进行真实试跑。", group.file));
                    }
                    continue;
                }
                if let Some(route) = group.routes.iter().find(|route| route.id == selected) {
                    final_message.push_str(&format!("\n{}：你指定了 {}；当前状态：{}。", group.file, route.backend, route.status));
                    final_message.push_str("该选择目前记录为优先路线，不代表已执行转译或已安装。");
                    let preference = if route.id.contains("fex") { Some("fexcore") }
                        else if route.id.contains("box64") { Some("box64") }
                        else { None };
                    if let Some(preference) = preference {
                        if chosen_backend.is_some_and(|existing| existing != preference) { backend_conflict = true; }
                        chosen_backend = Some(preference);
                    } else {
                        backend_conflict = true;
                        final_message.push_str("该路线目前没有连接到 Android AEX 实测器。");
                    }
                } else {
                    backend_conflict = true;
                    final_message.push_str(&format!("\n{}：手动路线 ID 未识别，暂不执行。", group.file));
                }
            }
            if has_aex && !backend_conflict {
                let preference = chosen_backend.unwrap_or("auto");
                match crate::start_windows_compat_aex_test_with_backend(&path, preference) {
                    Ok(request_id) => {
                        app.plugin_import = Some(ImportState::AexRuntimeTesting {
                            title, message: final_message, success, request_id, path, temporary_archive
                        });
                    }
                    Err(error) => {
                        if temporary_archive { let _ = std::fs::remove_file(&path); }
                        final_message.push_str(&format!("\n\nAEX 隔离实测未能启动：{error}"));
                        app.plugin_import = Some(ImportState::Result { title, message: final_message, success });
                    }
                }
            } else {
                if temporary_archive { let _ = std::fs::remove_file(&path); }
                if has_aex && backend_conflict {
                    final_message.push_str("\n\n本次手动选择包含尚未接入 AEX 实测器的路线，未冒充执行；请改选自动比较、FEXCore 或 Box64 后端。");
                } else {
                    final_message.push_str("\n\n本次文件没有可交给 AEX 原生宿主的 .aex 项，已保留原件并完成静态分析。");
                }
                app.plugin_import = Some(ImportState::Result { title, message: final_message, success });
            }
        },
        Some(Action::AexTestComplete(title, message, success, status, path, temporary_archive)) => {
            if temporary_archive { let _ = std::fs::remove_file(&path); }
            let passed = status.starts_with("EXIT:0");
            let partial = status.starts_with("EXIT:2");
            let mut final_message = message;
            final_message.push_str("\n\nAdobe AEX 隔离实测结果：\n");
            final_message.push_str(&status);
            if passed {
                final_message.push_str("\n实测通过：本次包内所有检测到的 AEX 至少有一条已接入路线通过加载、参数往返和重复 CPU 帧渲染。");
            } else if partial {
                final_message.push_str("\n部分通过：仍有 AEX 插件未通过；不能将整包标记为完全移植。");
            } else {
                final_message.push_str("\n未通过或运行环境未就绪；原始插件文件仍保留，可修复后重试。");
            }
            app.ui.status = if passed { "AEX 隔离实测通过".into() } else { "AEX 隔离实测结束；请查看详细报告".into() };
            app.plugin_import = Some(ImportState::Result {
                title,
                message: final_message,
                success: success || passed || partial,
            });
        }
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
    package_start = lock_source.find('name = "effectcraft-ui-egui"\n')
    if package_start < 0:
        raise SystemExit("Could not locate effectcraft-ui-egui in Cargo.lock")
    package_version_start = lock_source.find('version = "', package_start)
    package_version_end = lock_source.find('"', package_version_start + len('version = "'))
    if package_version_start < 0 or package_version_end < 0:
        raise SystemExit("Could not read effectcraft-ui-egui version in Cargo.lock")
    package_dependencies_start = lock_source.find("dependencies = [", package_version_end)
    if package_dependencies_start < 0:
        raise SystemExit("Could not locate effectcraft-ui-egui dependency list in Cargo.lock")
    package_start = lock_source.rfind('name = "effectcraft-ui-egui"\n', 0, package_dependencies_start)
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
