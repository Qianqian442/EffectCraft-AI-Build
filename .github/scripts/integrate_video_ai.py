from pathlib import Path
import os
import shutil

root = Path(os.environ["EFFECTCRAFT_DIR"])
rife_root = Path(os.environ["RIFE_SOURCE_DIR"])
esrgan_root = Path(os.environ["ESRGAN_SOURCE_DIR"])
template = Path(__file__).with_name("ai_video_export.rs")

# Install the Rust bridge in the actual exporter crate.
export_src = root / "crates/export/src"
ai_target = export_src / "ai_video.rs"
ai_source = template.read_text()
if ai_target.exists() and ai_target.read_text() != ai_source:
    raise SystemExit("Refusing to overwrite a different existing ai_video.rs")
ai_target.write_text(ai_source)

export_lib = export_src / "lib.rs"
s = export_lib.read_text()
if "mod ai_video;" not in s:
    marker = "mod encode;\n"
    if marker not in s:
        raise SystemExit("Could not find export module declarations")
    export_lib.write_text(s.replace(marker, marker + "mod ai_video;\n", 1))

# The export options are serialized with each OutputModule, so old project files retain false defaults.
project_file = root / "crates/project/src/render_queue.rs"
s = project_file.read_text()
field = "    pub include_project_link: bool,"
fields = field + "\n    /// Run RIFE 4.6 locally to synthesize intermediate video frames.\n    pub ai_frame_interpolation: bool,\n    /// Run local Real-ESRGAN x4 super-resolution after output crop/resize.\n    pub ai_upscale: bool,"
if "pub ai_frame_interpolation: bool" not in s:
    if field not in s:
        raise SystemExit("Could not find OutputModule AI insertion point")
    s = s.replace(field, fields, 1)
default = "            include_project_link: true,"
if "            ai_frame_interpolation: false," not in s:
    if default not in s:
        raise SystemExit("Could not find OutputModule default insertion point")
    s = s.replace(default, default + "\n            ai_frame_interpolation: false,\n            ai_upscale: false,", 1)
size_old = "        self.format.coded_size(w, h)"
size_new = """        let (w, h) = self.format.coded_size(w, h);
        if self.ai_upscale {
            (w.saturating_mul(4).min(8192), h.saturating_mul(4).min(8192))
        } else {
            (w, h)
        }"""
if size_new not in s:
    if size_old not in s:
        raise SystemExit("Could not find OutputModule::output_size return")
    s = s.replace(size_old, size_new, 1)
summary_old = """        match self.format {
            OutputFormat::H264 => format!("H.264 · {} kbps", self.bitrate_kbps),
            OutputFormat::ProRes => format!(
                "{} · {ch}",
                if self.channels == Channels::Rgba && !self.prores_profile.is_4444() { "Apple ProRes 4444" } else { self.prores_profile.label() }
            ),
            OutputFormat::Hevc | OutputFormat::Av1 => format!("{} · {}", self.format.label(), self.codec_summary()),
            OutputFormat::WebM if self.webm_codec == WebmVideoCodec::Av1 => {
                format!("WebM (AV1 + Opus {} kbps) · {}", self.opus_bitrate_kbps, self.codec_summary())
            }
            f => format!("{} · {ch}", f.label()),
        }"""
summary_new = """        let base = match self.format {
            OutputFormat::H264 => format!("H.264 · {} kbps", self.bitrate_kbps),
            OutputFormat::ProRes => format!(
                "{} · {ch}",
                if self.channels == Channels::Rgba && !self.prores_profile.is_4444() { "Apple ProRes 4444" } else { self.prores_profile.label() }
            ),
            OutputFormat::Hevc | OutputFormat::Av1 => format!("{} · {}", self.format.label(), self.codec_summary()),
            OutputFormat::WebM if self.webm_codec == WebmVideoCodec::Av1 => {
                format!("WebM (AV1 + Opus {} kbps) · {}", self.opus_bitrate_kbps, self.codec_summary())
            }
            f => format!("{} · {ch}", f.label()),
        };
        let mut ai = Vec::new();
        if self.ai_frame_interpolation { ai.push("RIFE 4.6 插帧"); }
        if self.ai_upscale { ai.push("Real-ESRGAN ×4"); }
        if ai.is_empty() { base } else { format!("{base} · {}", ai.join(" · ")) }"""
if summary_new not in s:
    if summary_old not in s:
        raise SystemExit("Could not find OutputModule::summary match")
    s = s.replace(summary_old, summary_new, 1)
describe_marker = """        if self.channels == Channels::Rgba {
            v.insert(3, ("Color", format!("{:?}", self.alpha_mode)));
        }"""
describe_new = describe_marker + """
        if self.ai_frame_interpolation {
            v.push(("AI Frame Interpolation", "RIFE 4.6 · Local".into()));
        }
        if self.ai_upscale {
            v.push(("AI Super Resolution", "Real-ESRGAN x4 · Local".into()));
        }"""
if "AI Super Resolution" not in s:
    if describe_marker not in s:
        raise SystemExit("Could not find OutputModule::describe insertion point")
    s = s.replace(describe_marker, describe_new, 1)
project_file.write_text(s)

# Persist the two flags through the Render Queue command API.
engine_file = root / "crates/engine/src/cmd/render_queue.rs"
s = engine_file.read_text()
marker = '    if let Some(l) = b_p(p, "includeProjectLink") {\n        om.include_project_link = l;\n    }'
addition = marker + """
    if let Some(enabled) = b_p(p, "aiFrameInterpolation") {
        om.ai_frame_interpolation = enabled;
        any = true;
    }
    if let Some(enabled) = b_p(p, "aiUpscale") {
        om.ai_upscale = enabled;
        any = true;
    }"""
if "b_p(p, \"aiFrameInterpolation\")" not in s:
    if marker not in s:
        raise SystemExit("Could not find OutputModule boolean option insertion point")
    s = s.replace(marker, addition, 1)
engine_file.write_text(s)

# Install the native worker sources in the checkout used for this build.
native_dir = root / "native" / "effectcraft-ai-video"
native_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(__file__).parents[1] / "native/effectcraft_ai_video_worker.cpp", native_dir / "effectcraft_ai_video_worker.cpp")
shutil.copy2(Path(__file__).parents[1] / "native/CMakeLists.txt", native_dir / "CMakeLists.txt")

# Patch Real-ESRGAN ncnn's reference class so it uses Vulkan when present and a tiled CPU path otherwise.
esrgan_cpp = esrgan_root / "src/realesrgan.cpp"
esrgan = esrgan_cpp.read_text()
old_ctor = """    net.opt.use_vulkan_compute = true;
    net.opt.use_fp16_packed = true;
    net.opt.use_fp16_storage = true;
    net.opt.use_fp16_arithmetic = false;
    net.opt.use_int8_storage = true;
    net.opt.use_int8_arithmetic = false;

    net.set_vulkan_device(gpuid);"""
new_ctor = """    const bool use_vulkan = gpuid >= 0;
    net.opt.use_vulkan_compute = use_vulkan;
    net.opt.use_fp16_packed = use_vulkan;
    net.opt.use_fp16_storage = use_vulkan;
    net.opt.use_fp16_arithmetic = false;
    net.opt.use_int8_storage = use_vulkan;
    net.opt.use_int8_arithmetic = false;

    if (use_vulkan) {
        net.set_vulkan_device(gpuid);
    }"""
if new_ctor not in esrgan:
    if old_ctor not in esrgan:
        raise SystemExit("Could not locate Real-ESRGAN Vulkan constructor block")
    esrgan = esrgan.replace(old_ctor, new_ctor, 1)

old_dtor = """    bicubic_2x->destroy_pipeline(net.opt);
    delete bicubic_2x;

    bicubic_3x->destroy_pipeline(net.opt);
    delete bicubic_3x;

    bicubic_4x->destroy_pipeline(net.opt);
    delete bicubic_4x;"""
new_dtor = """    if (bicubic_2x) {
        if (net.opt.use_vulkan_compute) bicubic_2x->destroy_pipeline(net.opt);
        delete bicubic_2x;
    }
    if (bicubic_3x) {
        if (net.opt.use_vulkan_compute) bicubic_3x->destroy_pipeline(net.opt);
        delete bicubic_3x;
    }
    if (bicubic_4x) {
        if (net.opt.use_vulkan_compute) bicubic_4x->destroy_pipeline(net.opt);
        delete bicubic_4x;
    }"""
if new_dtor not in esrgan:
    if old_dtor not in esrgan:
        raise SystemExit("Could not locate Real-ESRGAN destructor")
    esrgan = esrgan.replace(old_dtor, new_dtor, 1)

start = "    // initialize preprocess and postprocess pipeline\n"
end = "    return 0;\n}\n\nint RealESRGAN::process("
if "if (net.opt.use_vulkan_compute) {\n    // initialize preprocess" not in esrgan:
    a = esrgan.find(start)
    b = esrgan.find(end, a)
    if a < 0 or b < 0:
        raise SystemExit("Could not locate Real-ESRGAN GPU pipeline initialization")
    block = esrgan[a:b]
    indented = "".join("    " + line if line.strip() else line for line in block.splitlines(True))
    esrgan = esrgan[:a] + "    if (net.opt.use_vulkan_compute) {\n" + indented + "    }\n\n" + esrgan[b:]

cpu_branch = """    if (!net.opt.use_vulkan_compute) {
        if (channels != 3) return -1;
        const int tile = std::max(32, tilesize);
        const int pad = std::max(0, prepadding);
        const int out_w = w * scale;
        for (int y = 0; y < h; y += tile) {
            const int core_h = std::min(tile, h - y);
            const int y0 = std::max(0, y - pad);
            const int y1 = std::min(h, y + core_h + pad);
            for (int x = 0; x < w; x += tile) {
                const int core_w = std::min(tile, w - x);
                const int x0 = std::max(0, x - pad);
                const int x1 = std::min(w, x + core_w + pad);
                const int tile_w = x1 - x0;
                const int tile_h = y1 - y0;
                const unsigned char* src = pixeldata + (static_cast<size_t>(y0) * w + x0) * 3;
                ncnn::Mat input = ncnn::Mat::from_pixels(src, ncnn::Mat::PIXEL_RGB, tile_w, tile_h, w * 3);
                // The ncnn model consumes normalized RGB in [0, 1], while from_pixels returns [0, 255].
                for (int channel = 0; channel < 3; channel++) {
                    float* values = input.channel(channel);
                    for (int p = 0; p < tile_w * tile_h; p++) values[p] *= (1.f / 255.f);
                }
                ncnn::Extractor ex = net.create_extractor();
                ex.input("data", input);
                ncnn::Mat result;
                if (ex.extract("output", result) != 0 || result.empty()) return -1;
                std::vector<unsigned char> tile_pixels(static_cast<size_t>(result.w) * result.h * 3);
                const float* output_planes[3] = { result.channel(0), result.channel(1), result.channel(2) };
                for (int py = 0; py < result.h; py++) {
                    for (int px = 0; px < result.w; px++) {
                        const size_t dst = (static_cast<size_t>(py) * result.w + px) * 3;
                        const size_t src_index = static_cast<size_t>(py) * result.w + px;
                        for (int channel = 0; channel < 3; channel++) {
                            const float value = output_planes[channel][src_index] * 255.f;
                            tile_pixels[dst + channel] = static_cast<unsigned char>(std::clamp(value, 0.f, 255.f) + 0.5f);
                        }
                    }
                }
                const int crop_x = (x - x0) * scale;
                const int crop_y = (y - y0) * scale;
                const int copy_w = core_w * scale;
                const int copy_h = core_h * scale;
                if (crop_x + copy_w > result.w || crop_y + copy_h > result.h) return -1;
                for (int row = 0; row < copy_h; row++) {
                    const unsigned char* from = tile_pixels.data()
                        + (static_cast<size_t>(crop_y + row) * result.w + crop_x) * 3;
                    unsigned char* to = static_cast<unsigned char*>(outimage.data)
                        + (static_cast<size_t>(y * scale + row) * out_w + x * scale) * 3;
                    std::memcpy(to, from, static_cast<size_t>(copy_w) * 3);
                }
            }
        }
        return 0;
    }

"""
process_marker = "    const int channels = inimage.elempack;\n"
if cpu_branch not in esrgan:
    if process_marker not in esrgan:
        raise SystemExit("Could not find Real-ESRGAN process entry point")
    esrgan = esrgan.replace(process_marker, process_marker + "\n" + cpu_branch, 1)
if '#include <cstring>' not in esrgan:
    esrgan = esrgan.replace('#include <algorithm>\n', '#include <algorithm>\n#include <cstring>\n', 1)
esrgan_cpp.write_text(esrgan)

# Wire the inference functions into the actual frame pipeline. A small rolling source-frame cache
# avoids rendering the same 30 fps source frame eight times when exporting at 240 fps.
pipeline_file = root / "crates/export/src/pipeline.rs"
s = pipeline_file.read_text()
if "ai_source_frames: Mutex<std::collections::BTreeMap<i64, Image>>" not in s:
    old_fields = "    written: Mutex<Vec<String>>,\n}"
    new_fields = "    written: Mutex<Vec<String>>,\n    ai_error: Mutex<Option<String>>,\n    ai_source_frames: Mutex<std::collections::BTreeMap<i64, Image>>,\n}"
    if old_fields not in s:
        raise SystemExit("Could not add AI processing state to export context")
    s = s.replace(old_fields, new_fields, 1)

old_new = "Cx { job, project, cache, frame_times, overflowed: Mutex::new(vec![]), written: Mutex::new(vec![]) }"
new_new = "Cx { job, project, cache, frame_times, overflowed: Mutex::new(vec![]), written: Mutex::new(vec![]), ai_error: Mutex::new(None), ai_source_frames: Mutex::new(std::collections::BTreeMap::new()) }"
if new_new not in s:
    if old_new not in s:
        raise SystemExit("Could not initialize AI processing state")
    s = s.replace(old_new, new_new, 1)

old_frame = """        let img = match self.job.settings.sample(comp, i) {
            FrameSample::Progressive(t) => self.render_at(t).await,
            FrameSample::Fields { first, second, upper_first } => {
                let a = self.render_at(first).await;
                if second == first { a } else { interleave(&a, &self.render_at(second).await, upper_first) }
            }
        };
        let img = self.crop_resize(img);"""
new_frame = """        let sample = self.job.settings.sample(comp, i);
        let output_rate = self.job.settings.rate(comp).as_f64();
        let source_rate = comp.frame_rate.as_f64();
        if self.job.output.ai_frame_interpolation && output_rate <= source_rate + 0.001 {
            self.record_ai_error("RIFE AI 插帧需要把导出帧率设置得高于工程帧率（例如 240 FPS）".into());
        }
        let img = if self.job.output.ai_frame_interpolation && output_rate > source_rate + 0.001 {
            if let FrameSample::Progressive(output_time) = sample {
                let position = (output_time.seconds() * source_rate).max(0.0);
                let floor_position = position.floor();
                let max_source = ((comp.duration.seconds() * source_rate).ceil() as i64 - 1).max(0);
                let first_index = (floor_position as i64).clamp(0, max_source);
                let fraction = (position - floor_position).clamp(0.0, 1.0) as f32;
                if fraction > 0.001 && first_index < max_source {
                    let first = self.cached_source_frame(comp, first_index).await;
                    let second = self.cached_source_frame(comp, first_index + 1).await;
                    match crate::ai_video::interpolate(&first, &second, fraction, comp.background) {
                        Ok(frame) => frame,
                        Err(error) => {
                            self.record_ai_error(error);
                            first
                        }
                    }
                } else {
                    self.cached_source_frame(comp, first_index).await
                }
            } else {
                self.render_sample(sample).await
            }
        } else {
            self.render_sample(sample).await
        };
        let img = self.crop_resize(img);
        let img = if self.job.output.ai_upscale {
            if img.width > 2048 || img.height > 2048 {
                self.record_ai_error("Real-ESRGAN ×4 为避免超出设备内存限制，输入画面单边不能超过 2048 像素".into());
                img
            } else {
            match crate::ai_video::upscale(&img, comp.background) {
                Ok(frame) => frame,
                Err(error) => {
                    self.record_ai_error(error);
                    img
                }
            }
            }
        } else {
            img
        };"""
if new_frame not in s:
    if old_frame not in s:
        raise SystemExit("Could not find Cx::frame_async rendering block")
    s = s.replace(old_frame, new_frame, 1)

insert_before = "    /// Output frame `i` as the H.264 export's 4:2:0 planes"
helper = """    async fn render_sample(&self, sample: FrameSample) -> Image {
        match sample {
            FrameSample::Progressive(t) => self.render_at(t).await,
            FrameSample::Fields { first, second, upper_first } => {
                let a = self.render_at(first).await;
                if second == first { a } else { interleave(&a, &self.render_at(second).await, upper_first) }
            }
        }
    }

    async fn cached_source_frame(&self, comp: &Comp, index: i64) -> Image {
        if let Some(frame) = self.ai_source_frames.lock().unwrap_or_else(|e| e.into_inner()).get(&index).cloned() {
            return frame;
        }
        let frame = self.render_at(comp.frame_rate.tick_of(index)).await;
        let mut cache = self.ai_source_frames.lock().unwrap_or_else(|e| e.into_inner());
        cache.retain(|&k, _| k >= index.saturating_sub(1));
        cache.insert(index, frame.clone());
        frame
    }

    fn record_ai_error(&self, error: String) {
        let mut slot = self.ai_error.lock().unwrap_or_else(|e| e.into_inner());
        if slot.is_none() {
            *slot = Some(error);
        }
    }

    pub(crate) fn take_ai_error(&self) -> Option<String> {
        self.ai_error.lock().unwrap_or_else(|e| e.into_inner()).take()
    }

"""
if "async fn cached_source_frame" not in s:
    if insert_before not in s:
        raise SystemExit("Could not find insertion point for AI frame cache helpers")
    s = s.replace(insert_before, helper + insert_before, 1)

# AI exports are deliberately sequential: a single persistent model worker owns inference state,
# and the rolling two-frame cache prevents duplicate source renders.
frame_loop = "    pub async fn frames<T: Send>(&self, comp: &Comp, ks: Vec<u64>, f: impl Fn(u64, Image) -> T + Sync + Send) -> Vec<T> {\n"
serial = frame_loop + """        if self.job.output.ai_frame_interpolation || self.job.output.ai_upscale {
            let mut out = Vec::with_capacity(ks.len());
            for k in ks {
                let img = self.frame_async(comp, k).await;
                out.push(f(k, img));
            }
            return out;
        }
"""
if "if self.job.output.ai_frame_interpolation || self.job.output.ai_upscale {" not in s:
    if frame_loop not in s:
        raise SystemExit("Could not add sequential AI frame processing")
    s = s.replace(frame_loop, serial, 1)

# The optimized H.264 YUV path bypasses Cx::frame_async, so route AI jobs around it.
h264_gate = """        if self.job.output.ai_frame_interpolation || self.job.output.ai_upscale {
            return ks.into_iter().map(|k| fallback(k, self.frame(comp, k))).collect();
        }
"""
if h264_gate not in s:
    h264_signature = "    pub(crate) fn h264_frames<T: Send>("
    h264_start = s.find(h264_signature)
    h264_body = s.find("    ) -> Vec<T> {\n", h264_start)
    if h264_start < 0 or h264_body < 0:
        raise SystemExit("Could not locate Cx::h264_frames body for AI routing")
    h264_insert = h264_body + len("    ) -> Vec<T> {\n")
    s = s[:h264_insert] + h264_gate + s[h264_insert:]

yuv_marker = "        let om = self.job.output;\n        let scale = self.job.settings.effective_scale(comp);"
yuv_new = "        let om = self.job.output;\n        if om.ai_frame_interpolation || om.ai_upscale { return None; }\n        let scale = self.job.settings.effective_scale(comp);"
if yuv_new not in s:
    if yuv_marker not in s:
        raise SystemExit("Could not disable direct-YUV export for AI jobs")
    s = s.replace(yuv_marker, yuv_new, 1)

pipeline_file.write_text(s)

# Fail the export and remove its partial file if the local inference process/model fails.
export_lib = root / "crates/export/src/lib.rs"
s = export_lib.read_text()
old = """    let mut r = export_with(&cx, progress, t0).await;
    drop(render);
    if matches!(r, Err(ExportError::Cancelled)) {"""
new = """    let mut r = export_with(&cx, progress, t0).await;
    drop(render);
    if let Some(error) = cx.take_ai_error() {
        let cleanup = cx.remove_cancelled_outputs();
        let detail = cleanup.err().map(|e| format!("{error}; additionally, {e}")).unwrap_or(error);
        return Err(ExportError::Encode(format!("本地视频 AI 处理失败：{detail}")));
    }
    if matches!(r, Err(ExportError::Cancelled)) {"""
if new not in s:
    if old not in s:
        raise SystemExit("Could not insert AI export failure handling")
    s = s.replace(old, new, 1)
export_lib.write_text(s)

# Patch the centered export dialog created by patch_export_dialog.py.
header = root / "crates/ui-egui/src/header.rs"
h = header.read_text()
draft_old = """    let (mut format, mut fps, mut resolution) = ui.ctx().data(|d| {
        d.get_temp::<(String, f64, String)>(draft_id)
            .unwrap_or_else(|| ("h264".to_string(), 0.0, "1080".to_string()))
    });"""
draft_new = """    let (mut format, mut fps, mut resolution, mut ai_interpolation, mut ai_upscale) = ui.ctx().data(|d| {
        d.get_temp::<(String, f64, String, bool, bool)>(draft_id)
            .unwrap_or_else(|| ("h264".to_string(), 0.0, "1080".to_string(), false, false))
    });"""
if draft_new not in h:
    if draft_old not in h:
        raise SystemExit("Could not find export dialog draft state")
    h = h.replace(draft_old, draft_new, 1)

ui_marker = """            ui.add_space(4.0);
            ui.label("最高可选 240 FPS；实际渲染速度取决于工程素材和设备性能。");"""
ui_new = """            ui.add_space(6.0);
            ui.separator();
            ui.label("本地 AI 视频处理");
            ui.checkbox(&mut ai_interpolation, "AI 插帧（RIFE 4.6）");
            ui.checkbox(&mut ai_upscale, "AI 画质增强（Real-ESRGAN ×4）");
            if ai_interpolation {
                ui.label("建议将帧率设为 240 FPS；仅对原始帧之间的时间点进行神经网络插帧。");
            }
            if ai_upscale {
                ui.label("超分输出为 4 倍尺寸；会显著增加处理时间与文件大小。");
            }
            ui.add_space(4.0);
            ui.label("最高可选 240 FPS；实际帧率和处理速度受素材及设备性能影响。");"""
if ui_new not in h:
    if ui_marker not in h:
        raise SystemExit("Could not find export dialog AI options insertion point")
    h = h.replace(ui_marker, ui_new, 1)

params_old = """            let mut params = json!({"comp": comp.0, "format": format});
            if fps > 0.0 {"""
params_new = """            let mut params = json!({
                "comp": comp.0,
                "format": format,
                "aiFrameInterpolation": ai_interpolation,
                "aiUpscale": ai_upscale
            });
            if fps > 0.0 {"""
if params_new not in h:
    if params_old not in h:
        raise SystemExit("Could not pass AI options to renderQueue.add")
    h = h.replace(params_old, params_new, 1)

draft_save_old = 'd.insert_temp(draft_id, (format, fps, resolution));'
draft_save_new = 'd.insert_temp(draft_id, (format, fps, resolution, ai_interpolation, ai_upscale));'
if draft_save_new not in h:
    if draft_save_old not in h:
        raise SystemExit("Could not persist AI options in export dialog state")
    h = h.replace(draft_save_old, draft_save_new, 1)
export_guard_helpers = r'''
/// Convert a requested vertical resolution to even pixel dimensions while preserving
/// the source aspect ratio. This supports landscape, portrait, and square compositions.
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

/// Do not impose an application-specific runtime memory ceiling.
/// Only defer an export when Android reports critically low system-wide free memory.
fn effectcraft_export_memory_ok(
    _width: u32,
    _height: u32,
    _fps: f64,
    ai_interpolation: bool,
    ai_upscale: bool,
) -> bool {
    #[cfg(target_os = "android")]
    {
        let meminfo = match std::fs::read_to_string("/proc/meminfo") {
            Ok(value) => value,
            Err(_) => return true,
        };
        let available_kb = meminfo.lines().find_map(|line| {
            let mut fields = line.split_whitespace();
            if fields.next()? == "MemAvailable:" {
                fields.next()?.parse::<u64>().ok()
            } else {
                None
            }
        });
        let available_kb = match available_kb {
            Some(value) => value,
            None => return true,
        };
        // This is a critical-low-memory safety reserve, not a maximum for EffectCraft.
        // Normal exports may use as much memory as Android makes available to the process.
        let critical_floor_kb: u64 = if ai_interpolation || ai_upscale {
            384 * 1024
        } else {
            160 * 1024
        };
        available_kb >= critical_floor_kb
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = (ai_interpolation, ai_upscale);
        true
    }
}
'''
helper_split_marker = "/// Do not impose an application-specific runtime memory ceiling."
helper_split = export_guard_helpers.index(helper_split_marker)
dimension_helper = export_guard_helpers[:helper_split].strip()
memory_helper = export_guard_helpers[helper_split:].strip()
missing_helpers = []
if "fn effectcraft_export_dimensions(" not in h:
    missing_helpers.append(dimension_helper)
if "fn effectcraft_export_memory_ok(" not in h:
    missing_helpers.append(memory_helper)
if missing_helpers:
    h = h.rstrip() + "\n\n" + "\n\n".join(missing_helpers) + "\n"

preflight_old = """            let ctx = ui.ctx().clone();
            match crate::menus::invoke(app, &ctx, "renderQueue.add", params) {"""
preflight_new = """            let (check_width, check_height) = app.session.active_comp()
                .map(|active| effectcraft_export_dimensions(active.width, active.height, &resolution))
                .unwrap_or((1920, 1080));
            let effective_fps = if fps > 0.0 {
                fps
            } else {
                app.session.active_comp().map(|active| active.frame_rate.as_f64()).unwrap_or(30.0)
            };
            let upscale_input_too_large = ai_upscale && (check_width > 2048 || check_height > 2048);
            if upscale_input_too_large
                || !effectcraft_export_memory_ok(check_width, check_height, effective_fps, ai_interpolation, ai_upscale)
            {
                app.ui.status = if upscale_input_too_large {
                    "Real-ESRGAN ×4 当前输入尺寸超过 2048 像素，请降低输入分辨率或关闭 AI 超分".to_string()
                } else {
                    "系统可用内存暂时过低，已暂停本次导出以避免 Android 强制结束应用；释放后台内存后可重试。EffectCraft 不设置固定运行内存上限。".to_string()
                };
            } else {
                let ctx = ui.ctx().clone();
                match crate::menus::invoke(app, &ctx, "renderQueue.add", params) {"""
if preflight_new not in h:
    if preflight_old not in h:
        raise SystemExit("Could not find the Android export task insertion point for AI preflight.")
    h = h.replace(preflight_old, preflight_new, 1)
    # The new else branch wraps the original renderQueue.add match. Close that
    # branch explicitly before closing the active-composition and submit guards.
    close_anchor = """            }
        }
    }

    ui.ctx().data_mut(|d| {"""
    close_replacement = """            }
            }
        }
    }

    ui.ctx().data_mut(|d| {"""
    if h.count(close_anchor) != 1:
        raise SystemExit(f"Expected one export-dialog preflight closing anchor; found {h.count(close_anchor)}")
    h = h.replace(close_anchor, close_replacement, 1)
header.write_text(h)

# Copy only neural model weights into app-private storage. Android 10+ blocks execve()
# from the writable app data directory, so the worker itself must be packaged under jniLibs.
builder_file = root.parents[1] / "lib/build-common.sh"
builder_text = builder_file.read_text()
persist_marker = '    }\n    log::info!("settings directory: {}", config.display());'
persist_code = """        let bundled_models = [
            ("models/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf", "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf"),
            ("models/rife-v4.6/flownet.param", "rife-v4.6/flownet.param"),
            ("models/rife-v4.6/flownet.bin", "rife-v4.6/flownet.bin"),
            ("models/realesrgan-x4plus.param", "realesrgan-x4plus.param"),
            ("models/realesrgan-x4plus.bin", "realesrgan-x4plus.bin"),
        ];
        for (asset_path, private_path) in bundled_models {
            let destination = internal.join(private_path);
            if !destination.is_file() {
                if let Some(parent) = destination.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                let temporary = destination.with_extension("tmp");
                if let Ok(asset_name) = std::ffi::CString::new(asset_path) {
                    if let Some(mut asset) = app.asset_manager().open(&asset_name) {
                        if let Ok(mut output) = std::fs::File::create(&temporary) {
                            match std::io::copy(&mut asset, &mut output) {
                                Ok(bytes) if bytes > 0 => {
                                    if let Err(error) = std::fs::rename(&temporary, &destination) {
                                        log::warn!("Could not finalize local AI asset {asset_path}: {error}");
                                        let _ = std::fs::remove_file(&temporary);
                                    }
                                }
                                Ok(_) => {
                                    log::warn!("Local AI asset is empty: {asset_path}");
                                    let _ = std::fs::remove_file(&temporary);
                                }
                                Err(error) => {
                                    log::warn!("Could not extract local AI asset {asset_path}: {error}");
                                    let _ = std::fs::remove_file(&temporary);
                                }
                            }
                        }
                    }
                }
            }
        }

        let deepseek_model = internal.join("DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf");
        if deepseek_model.is_file() {
            std::env::set_var("EFFECTCRAFT_AI_MODEL_PATH", &deepseek_model);
        } else {
            log::warn!("Bundled offline DeepSeek model was not extracted; local chat will remain unavailable.");
        }

        let native_worker = std::env::var_os("LD_LIBRARY_PATH").and_then(|value| {
            std::env::split_paths(&value)
                .map(|directory| directory.join("libeffectcraft-ai-video-worker.so"))
                .find(|candidate| candidate.is_file())
        }).or_else(|| {
            std::fs::read_to_string("/proc/self/maps").ok().and_then(|maps| {
                maps.lines()
                    .filter_map(|line| line.split_whitespace().last())
                    .filter(|path| path.starts_with("/data/app/") && path.ends_with(".so"))
                    .filter_map(|path| std::path::Path::new(path).parent()
                        .map(|directory| directory.join("libeffectcraft-ai-video-worker.so")))
                    .find(|candidate| candidate.is_file())
            })
        });
        let rife = internal.join("rife-v4.6");
        let sr_param = internal.join("realesrgan-x4plus.param");
        let sr_model = internal.join("realesrgan-x4plus.bin");
        if let Some(worker) = native_worker {
            if rife.join("flownet.param").is_file() && rife.join("flownet.bin").is_file() && sr_param.is_file() && sr_model.is_file() {
                std::env::set_var("EFFECTCRAFT_AI_VIDEO_WORKER_PATH", &worker);
                std::env::set_var("EFFECTCRAFT_RIFE_MODEL_PATH", &rife);
                std::env::set_var("EFFECTCRAFT_ESRGAN_PARAM_PATH", &sr_param);
                std::env::set_var("EFFECTCRAFT_ESRGAN_MODEL_PATH", &sr_model);
                log::info!("Local RIFE 4.6 and Real-ESRGAN x4 assets are ready.");
            } else {
                log::warn!("Local video AI model assets are incomplete; no cloud fallback will be used.");
            }
        } else {
            log::warn!("Local video AI worker was not found in Android nativeLibraryDir.");
        }
"""
if persist_marker not in builder_text:
    raise SystemExit("Could not locate persistent-storage function closing brace in Android builder")
if builder_text.count(persist_marker) != 1:
    raise SystemExit("Expected exactly one persistent-storage insertion point")
builder_text = builder_text.replace(persist_marker, persist_code + persist_marker, 1)
# Gradle otherwise stores native libraries uncompressed inside the APK. Turn on legacy
# extraction so PackageManager installs the worker under the app's read-only nativeLibraryDir.
gradle_generator = root.parents[1] / "lib/android_project.py"
gradle_text = gradle_generator.read_text()
if "useLegacyPackaging = true" not in gradle_text:
    if "useLegacyPackaging = false" not in gradle_text:
        raise SystemExit("Could not locate Gradle jniLibs packaging configuration")
    gradle_text = gradle_text.replace("useLegacyPackaging = false", "useLegacyPackaging = true", 1)

# Older Android OEM package installers can be less tolerant of APKs signed only with v2.
# Explicitly include v1, v2 and v3 signatures while keeping the same persistent certificate.
# AGP 8.7.3 exposes these exact SigningConfig DSL properties.
signing_anchor = """                keyPassword System.getenv('ARTCRAFT_KEY_PASSWORD')
            }}
        }}
    }}
"""
signing_replacement = """                keyPassword System.getenv('ARTCRAFT_KEY_PASSWORD')
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = false
            }}
        }}
    }}"""
if "enableV1Signing = true" not in gradle_text:
    if gradle_text.count(signing_anchor) != 1:
        raise SystemExit("Could not uniquely locate Gradle APK signing configuration")
    gradle_text = gradle_text.replace(signing_anchor, signing_replacement, 1)
gradle_generator.write_text(gradle_text)

# Android 10+ W^X requires executable native code to be installed from the APK's native library
# directory. Force PackageManager extraction so the worker can be execve'd from nativeLibraryDir.
manifest_marker = 'python3 "$ROOT/lib/android_project.py" "$ROOT" "$ANDROID_DIR" "$APP" "$APP_VERSION"\n'
manifest_patch = manifest_marker + """python3 - "$ANDROID_DIR/AndroidManifest.xml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
if "android:extractNativeLibs=" not in text:
    marker = "<application"
    index = text.find(marker)
    if index < 0:
        raise SystemExit("Generated AndroidManifest.xml has no application element")
    index += len(marker)
    text = text[:index] + ' android:extractNativeLibs="true"' + text[index:]
    path.write_text(text)
PY
"""
if 'android:extractNativeLibs="true"' not in builder_text:
    if manifest_marker not in builder_text:
        raise SystemExit("Could not find generated AndroidManifest.xml insertion point")
    builder_text = builder_text.replace(manifest_marker, manifest_patch, 1)

# cargo-ndk recreates jniLibs for the Rust app. Place the standalone PIE worker beside the app's
# own .so after that step and before Gradle packages the APK.
cargo_marker = '\nGRADLE_JDK="$(find_gradle_jdk || true)"'
cargo_patch = """
VIDEO_WORKER_SOURCE="$ROOT/$SRC/native/effectcraft-ai-video-worker"
if [[ ! -s "$VIDEO_WORKER_SOURCE" ]]; then
    fail "The local RIFE/Real-ESRGAN worker is missing: $VIDEO_WORKER_SOURCE (cwd=$PWD; ROOT=$ROOT; SRC=$SRC)"
fi
mkdir -p "$ANDROID_DIR/jniLibs/arm64-v8a"
install -m 0755 "$VIDEO_WORKER_SOURCE" "$ANDROID_DIR/jniLibs/arm64-v8a/libeffectcraft-ai-video-worker.so"
echo "Packaged the local video AI worker in jniLibs/arm64-v8a for Android 10+ execution."
"""
if "Packaged the local video AI worker in jniLibs/arm64-v8a" not in builder_text:
    if cargo_marker not in builder_text:
        raise SystemExit("Could not find cargo-ndk/Gradle insertion point")
    builder_text = builder_text.replace(cargo_marker, "\n" + cargo_patch + cargo_marker, 1)

builder_file.write_text(builder_text)

print("Integrated persistent local RIFE 4.6 / Real-ESRGAN x4 inference into the EffectCraft export frame pipeline.")
