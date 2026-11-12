from pathlib import Path
import os

root = Path(os.environ["EFFECTCRAFT_DIR"])
header_path = root / "crates/ui-egui/src/header.rs"
header = header_path.read_text()

draft_marker = """    let (mut format, mut fps, mut resolution, mut bitrate_mbps, mut ai_interpolation, mut ai_upscale) = ui.ctx().data(|d| {
        d.get_temp::<(String, f64, String, f64, bool, bool)>(draft_id)
            .unwrap_or_else(|| ("h264".to_string(), 0.0, "1080".to_string(), 12.0, false, false))
    });
    let comp_name = app.session.active_comp_id()"""
draft_replacement = """    let (mut format, mut fps, mut resolution, mut bitrate_mbps, mut ai_interpolation, mut ai_upscale) = ui.ctx().data(|d| {
        d.get_temp::<(String, f64, String, f64, bool, bool)>(draft_id)
            .unwrap_or_else(|| ("h264".to_string(), 0.0, "1080".to_string(), 12.0, false, false))
    });
    let preflight_error_id = open_id.with("preflight-error");
    let mut preflight_error = ui.ctx().data(|d| d.get_temp::<Option<String>>(preflight_error_id).flatten());
    let warning_id = open_id.with("preflight-warning-open");
    let mut warning_open = ui.ctx().data(|d| d.get_temp::<bool>(warning_id).unwrap_or(false));
    let force_export_id = open_id.with("force-export-once");
    let mut force_export = ui.ctx().data(|d| d.get_temp::<bool>(force_export_id).unwrap_or(false));
    let previous_settings = (format.clone(), fps, resolution.clone(), bitrate_mbps, ai_interpolation, ai_upscale);
    let comp_name = app.session.active_comp_id()"""
if "let previous_settings = (format.clone(), fps, resolution.clone(), bitrate_mbps, ai_interpolation, ai_upscale);" not in header:
    if draft_marker not in header:
        raise SystemExit("Could not find AI export dialog state for device preflight")
    header = header.replace(draft_marker, draft_replacement, 1)

label_old = '            ui.label(comp_name.as_deref().unwrap_or("请先打开一个合成工程"));'
label_new = label_old + """
            if let Some(message) = preflight_error.as_deref() {
                ui.colored_label(Color32::from_rgb(220, 65, 65), message);
            }"""
if label_new not in header:
    if label_old not in header:
        raise SystemExit("Could not find project label in export dialog")
    header = header.replace(label_old, label_new, 1)

old_check = """            let upscale_input_too_large = ai_upscale && (check_width > 2048 || check_height > 2048);
            if upscale_input_too_large
                || !effectcraft_export_memory_ok(check_width, check_height, effective_fps, ai_interpolation, ai_upscale)
            {
                app.ui.status = if upscale_input_too_large {
                    "Real-ESRGAN ×4 当前输入尺寸超过 2048 像素，请降低输入分辨率或关闭 AI 超分".to_string()
                } else {
                    "系统可用内存暂时过低，已暂停本次导出以避免 Android 强制结束应用；释放后台内存后可重试。EffectCraft 不设置固定运行内存上限。".to_string()
                };
            } else {"""
new_check = """            let (source_fps, duration_seconds) = app.session.active_comp()
                .map(|active| (active.frame_rate.as_f64(), active.duration.seconds()))
                .unwrap_or((30.0, 1.0));
            let mut block_export = false;
            if !force_export {
                if let Some(message) = effectcraft_export_device_preflight(
                    check_width, check_height, effective_fps, source_fps, duration_seconds,
                    format.as_str(), ai_interpolation, ai_upscale
                ) {
                    preflight_error = Some(message);
                    warning_open = true;
                    block_export = true;
                }
            }
            if !block_export {
                preflight_error = None;
                warning_open = false;
                force_export = false;"""
if new_check not in header:
    if old_check not in header:
        raise SystemExit("Could not replace the original export preflight with unified device checks")
    header = header.replace(old_check, new_check, 1)

cancel_old = """    if cancel {
        open = false;
    }"""
cancel_new = """    if (format.clone(), fps, resolution.clone(), bitrate_mbps, ai_interpolation, ai_upscale) != previous_settings {
        preflight_error = None;
        warning_open = false;
    }
    if cancel {
        open = false;
        preflight_error = None;
        warning_open = false;
        force_export = false;
    }"""
if cancel_new not in header:
    if cancel_old not in header:
        raise SystemExit("Could not add export preflight warning reset")
    header = header.replace(cancel_old, cancel_new, 1)

draft_store = 'd.insert_temp(draft_id, (format, fps, resolution, bitrate_mbps, ai_interpolation, ai_upscale));'
draft_store_new = draft_store + '\n        d.insert_temp(preflight_error_id, preflight_error);\n        d.insert_temp(warning_id, warning_open);\n        d.insert_temp(force_export_id, force_export);'
if draft_store_new not in header:
    if header.count(draft_store) != 1:
        raise SystemExit("Could not persist preflight dialog warning state")
    header = header.replace(draft_store, draft_store_new, 1)

warning_ui = r"""
    if warning_open {
        let mut adjust_parameters = false;
        let mut force_now = false;
        egui::Window::new("导出提示")
            .id(open_id.with("preflight-warning-window"))
            .order(egui::Order::Foreground)
            .movable(true)
            .collapsible(false)
            .resizable(false)
            .default_width(300.0)
            .default_pos(ui.ctx().content_rect().center() - vec2(150.0, 92.0))
            .show(ui.ctx(), |ui| {
                ui.label("参数过高，手机性能不足，请调整参数再试。");
                if let Some(message) = preflight_error.as_deref() { ui.small(message); }
                ui.small("强行导出可能导致导出失败、应用卡顿或闪退。");
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    if ui.button("调整参数").clicked() { adjust_parameters = true; }
                    if ui.button("强行导出").clicked() { force_now = true; }
                });
            });
        if adjust_parameters { warning_open = false; preflight_error = None; }
        if force_now { warning_open = false; preflight_error = None; force_export = true; }
    }
"""
submit_old = "    let mut submit = false;"
submit_new = "    let mut submit = force_export;"
if submit_new not in header:
    if submit_old not in header:
        raise SystemExit("Could not add one-shot force-export state")
    header = header.replace(submit_old, submit_new, 1)

store_anchor = """    ui.ctx().data_mut(|d| {
        d.insert_temp(open_id, open);
        d.insert_temp(draft_id, (format, fps, resolution, bitrate_mbps, ai_interpolation, ai_upscale));"""
if "egui::Window::new(\"导出提示\")" not in header:
    if header.count(store_anchor) != 1:
        raise SystemExit("Could not find the export dialog state-save block for warning popup")
    header = header.replace(store_anchor, warning_ui + "\n" + store_anchor, 1)
helpers = r'''
/// EFFECTCRAFT_ANDROID_EXPORT_DEVICE_PREFLIGHT_V2
/// Multi-factor Android export preflight. Unknown OS readings do not falsely reject an export.
fn effectcraft_export_memory_capacity_ok(width: u32, height: u32, fps: f64, ai_interpolation: bool, ai_upscale: bool) -> bool {
    #[cfg(target_os = "android")]
    {
        const MIB: u64 = 1024 * 1024;
        const GIB: u64 = 1024 * MIB;
        let Ok(meminfo) = std::fs::read_to_string("/proc/meminfo") else { return true; };
        let Some(memory) = effectcraft_engine::sysinfo::parse_meminfo(&meminfo) else { return true; };
        let pixels = (width as u64).saturating_mul(height as u64);
        let mut min_total = if pixels >= 7_000_000 { 6 * GIB }
            else if pixels >= 3_000_000 { 4 * GIB }
            else if pixels >= 1_500_000 { 3 * GIB }
            else { 2 * GIB };
        if ai_interpolation || ai_upscale {
            min_total = min_total.saturating_add(512 * MIB);
        }
        let bytes_per_pixel = if ai_upscale { 40 } else if ai_interpolation { 28 } else { 12 };
        let fps_reserve = if fps >= 240.0 { 384 * MIB }
            else if fps >= 120.0 { 256 * MIB }
            else if fps >= 60.0 { 128 * MIB }
            else { 64 * MIB };
        let required_available = 384 * MIB + pixels.saturating_mul(bytes_per_pixel) + fps_reserve;
        memory.total >= min_total && memory.available >= required_available
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = (width, height, fps, ai_interpolation, ai_upscale);
        true
    }
}

fn effectcraft_android_ai_vulkan_available() -> Option<bool> {
    #[cfg(target_os = "android")]
    {
        let worker = std::env::var("EFFECTCRAFT_AI_VIDEO_WORKER_PATH").ok()?;
        let output = std::process::Command::new(worker).arg("--probe").output().ok()?;
        if !output.status.success() { return None; }
        let text = String::from_utf8_lossy(&output.stdout);
        return text.lines()
            .find_map(|line| line.strip_prefix("gpu_count=")?.parse::<u32>().ok())
            .map(|count| count > 0);
    }
    #[cfg(not(target_os = "android"))]
    { None }
}

fn effectcraft_android_cpu_temperature_c() -> Option<f64> {
    #[cfg(target_os = "android")]
    {
        let entries = std::fs::read_dir("/sys/class/thermal").ok()?;
        let mut hottest: Option<f64> = None;
        for entry in entries.flatten() {
            let path = entry.path();
            if !entry.file_name().to_string_lossy().starts_with("thermal_zone") { continue; }
            let kind = std::fs::read_to_string(path.join("type")).unwrap_or_default().to_lowercase();
            if !kind.contains("cpu") && !kind.contains("gpu") && !kind.contains("soc") { continue; }
            let Ok(raw) = std::fs::read_to_string(path.join("temp")) else { continue; };
            let Ok(value) = raw.trim().parse::<f64>() else { continue; };
            let celsius = if value > 1000.0 { value / 1000.0 } else { value };
            if (10.0..=150.0).contains(&celsius) {
                hottest = Some(hottest.map_or(celsius, |current| current.max(celsius)));
            }
        }
        return hottest;
    }
    #[cfg(not(target_os = "android"))]
    { None }
}

fn effectcraft_export_device_preflight(
    width: u32,
    height: u32,
    fps: f64,
    source_fps: f64,
    duration_seconds: f64,
    format: &str,
    ai_interpolation: bool,
    ai_upscale: bool,
) -> Option<String> {
    #[cfg(target_os = "android")]
    {
        const MIB: u64 = 1024 * 1024;
        let fail = |reason: &str| Some(format!(
            "参数过高，手机性能不足，无法导出，请降低参数再试。\n检测原因：{reason}"
        ));
        if width == 0 || height == 0 || width > 8192 || height > 8192 {
            return fail("所选画面尺寸超出当前导出引擎支持范围");
        }
        if !matches!(format, "h264" | "hevc" | "av1" | "webm" | "prores") {
            return fail("当前安装包没有对应的视频编码器");
        }
        if !fps.is_finite() || fps <= 0.0 || fps > 240.0 {
            return fail("帧率参数无效或超过 240 FPS");
        }
        if ai_interpolation && fps <= source_fps + 0.001 {
            return fail("启用 AI 插帧时，导出帧率必须高于工程原始帧率");
        }
        if (ai_interpolation || ai_upscale) && (width > 2048 || height > 2048) {
            return fail("当前本地 RIFE / Real-ESRGAN 模型单边输入上限为 2048 像素，请降低分辨率或关闭 AI 处理");
        }
        // This check covers both total RAM and currently available RAM. Keep the
        // preflight tolerant when Android does not expose readable /proc/meminfo.
        if !effectcraft_export_memory_capacity_ok(width, height, fps, ai_interpolation, ai_upscale) {
            return fail("系统总内存或当前可用内存不足以安全处理所选分辨率、帧率和 AI 负载");
        }

        let cores = effectcraft_engine::sysinfo::cpu_cores();
        let pixels = (width as u64).saturating_mul(height as u64);
        let heavy_codec = matches!(format, "av1" | "prores");
        if cores <= 2 && (pixels > 921_600 || fps > 60.0 || ai_interpolation || ai_upscale || heavy_codec) {
            return fail("检测到可用 CPU 核心数不超过 2，当前导出参数负载过高");
        }
        if cores < 4 && (fps >= 240.0 || (ai_interpolation && fps >= 120.0)
            || (ai_upscale && pixels > 1_500_000) || (heavy_codec && pixels >= 3_000_000)) {
            return fail("检测到 CPU 核心数不足以稳定处理当前高帧率、AI 或高负载编码任务");
        }

        if ai_interpolation || ai_upscale {
            let worker = std::env::var("EFFECTCRAFT_AI_VIDEO_WORKER_PATH").ok();
            if worker.as_deref().is_none_or(|path| !std::path::Path::new(path).is_file()) {
                return fail("本地 AI 视频引擎未安装或不可执行");
            }
            if ai_interpolation {
                let model = std::env::var("EFFECTCRAFT_RIFE_MODEL_PATH").ok()
                    .map(|path| std::path::PathBuf::from(path).join("flownet.bin").is_file()).unwrap_or(false);
                if !model { return fail("未找到本地 RIFE 4.6 模型文件"); }
            }
            if ai_upscale {
                let model = std::env::var("EFFECTCRAFT_ESRGAN_MODEL_PATH").ok()
                    .map(|path| std::path::Path::new(&path).is_file()).unwrap_or(false);
                if !model { return fail("未找到本地 Real-ESRGAN 模型文件"); }
            }
            if effectcraft_android_ai_vulkan_available() != Some(true)
                && cores < 4 && (pixels > 921_600 || fps >= 120.0 || ai_upscale) {
                return fail("未检测到可用 Vulkan GPU，且 CPU 核心数不足以承担本次 AI 处理");
            }
        }

        if let Some(temp) = effectcraft_android_cpu_temperature_c() {
            if temp >= 85.0 {
                return fail("检测到手机 CPU / GPU 温度过高，请先让手机降温后再导出");
            }
        }

        if let Some(storage_dir) = std::env::var("EFFECTCRAFT_AI_MODEL_PATH").ok()
            .and_then(|path| std::path::PathBuf::from(path).parent().map(|p| p.to_path_buf())) {
            if let Ok(output) = std::process::Command::new("df").arg("-Pk").arg(&storage_dir).output() {
                if output.status.success() {
                    let report = String::from_utf8_lossy(&output.stdout);
                    if let Some((_, available)) = effectcraft_engine::sysinfo::parse_df(&report) {
                        let bitrate = match format {
                            "h264" => 16_000_000_u64,
                            "hevc" => 12_000_000_u64,
                            "av1" => 10_000_000_u64,
                            "webm" => 12_000_000_u64,
                            "prores" => 100_000_000_u64,
                            _ => 16_000_000_u64,
                        };
                        let duration = if duration_seconds.is_finite() { duration_seconds.clamp(1.0, 86_400.0) } else { 1.0 };
                        let scale = if ai_upscale { 1.8 } else { 1.3 };
                        let estimate = (duration * bitrate as f64 / 8.0 * scale).ceil() as u64;
                        let required = estimate.saturating_add(256 * MIB);
                        if available < required {
                            return fail(&format!(
                                "应用存储空间不足：当前约 {} MB，预计至少需要 {} MB",
                                available / MIB, required / MIB
                            ));
                        }
                    }
                }
            }
        }
        None
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = (width, height, fps, source_fps, duration_seconds, format, ai_interpolation, ai_upscale);
        None
    }
}
'''
if "fn effectcraft_export_device_preflight(" not in header:
    header = header.rstrip() + "\n\n" + helpers.strip() + "\n"
elif "EFFECTCRAFT_ANDROID_EXPORT_DEVICE_PREFLIGHT_V2" not in header:
    raise SystemExit("A preflight helper exists without the expected marker; refusing to overwrite it")

dimension_helper = r'''
/// Preserve source aspect ratio while converting the selected export resolution
/// to even dimensions. Supports landscape, portrait and square compositions.
fn effectcraft_export_dimensions(source_width: u32, source_height: u32, resolution: &str) -> (u32, u32) {
    let target_height = match resolution {
        "480" => 480_u32,
        "720" => 720_u32,
        "1080" => 1080_u32,
        "1440" => 1440_u32,
        "2160" => 2160_u32,
        _ => return (source_width.max(2) & !1, source_height.max(2) & !1),
    };
    let source_width = source_width.max(1);
    let source_height = source_height.max(1);
    let scaled_width = ((source_width as f64 * target_height as f64)
        / source_height as f64)
        .round()
        .clamp(2.0, 8192.0) as u32;
    let width = (scaled_width.max(2) & !1).max(2);
    (width, target_height)
}
'''
if "fn effectcraft_export_dimensions(" not in header:
    header = header.rstrip() + "\n\n" + dimension_helper.strip() + "\n"
if "fn effectcraft_export_dimensions(" not in header:
    raise SystemExit("Export dimensions helper is still missing after the repair.")

header_path.write_text(header)
print("Added comprehensive Android export device checks.")

# The final generated header must contain both export helper functions.
