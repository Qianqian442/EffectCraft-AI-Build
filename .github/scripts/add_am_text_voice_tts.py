#!/usr/bin/env python3
"""Add editable AM text controls and Android system-TTS audio generation."""
from __future__ import annotations

import os
from pathlib import Path


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count == 0 and new in source:
        return source
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


JAVA_IMPORTS = (
    "import android.content.res.AssetManager;",
    "import com.k2fsa.sherpa.onnx.GeneratedAudio;",
    "import com.k2fsa.sherpa.onnx.OfflineTts;",
    "import com.k2fsa.sherpa.onnx.OfflineTtsConfig;",
    "import com.k2fsa.sherpa.onnx.OfflineTtsModelConfig;",
    "import com.k2fsa.sherpa.onnx.OfflineTtsVitsModelConfig;",
    "import java.io.IOException;",
    "import java.util.concurrent.ConcurrentHashMap;",
    "import java.util.concurrent.Future;",
)

JAVA_TTS = r'''
    // EFFECTCRAFT_ANDROID_AM_TEXT_TO_SPEECH_V1
    private static volatile OfflineTts aeOfflineTts;
    private static final ExecutorService aeTtsExecutor = Executors.newSingleThreadExecutor();
    private static final ConcurrentHashMap<String, String> aeTtsResults = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Future<?>> aeTtsJobs = new ConcurrentHashMap<>();

    private static synchronized OfflineTts getAeOfflineTts(__CLASS__ activity) throws Exception {
        if (aeOfflineTts != null) return aeOfflineTts;
        File modelDir = new File(activity.getFilesDir(), "ae-offline-tts/sherpa-onnx-vits-zh-ll");
        File modelFile = new File(modelDir, "model.onnx");
        if (!modelFile.isFile() || modelFile.length() < 80L * 1024L * 1024L) {
            copyAeTtsAssets(activity.getAssets(), "ae-tts/sherpa-onnx-vits-zh-ll", modelDir);
        }
        File tokens = new File(modelDir, "tokens.txt");
        File lexicon = new File(modelDir, "lexicon.txt");
        if (!modelFile.isFile() || !tokens.isFile() || !lexicon.isFile()) {
            throw new IOException("离线中文语音模型文件不完整。");
        }
        OfflineTtsVitsModelConfig vits = OfflineTtsVitsModelConfig.builder()
            .setModel(modelFile.getAbsolutePath())
            .setTokens(tokens.getAbsolutePath())
            .setLexicon(lexicon.getAbsolutePath())
            .build();
        OfflineTtsModelConfig model = OfflineTtsModelConfig.builder()
            .setVits(vits)
            .setNumThreads(2)
            .setProvider("cpu")
            .build();
        String rules = new File(modelDir, "date.fst").getAbsolutePath() + "," +
            new File(modelDir, "phone.fst").getAbsolutePath() + "," +
            new File(modelDir, "number.fst").getAbsolutePath() + "," +
            new File(modelDir, "new_heteronym.fst").getAbsolutePath();
        aeOfflineTts = new OfflineTts(OfflineTtsConfig.builder()
            .setModel(model).setRuleFsts(rules).setMaxNumSentences(1).build());
        return aeOfflineTts;
    }

    private static void copyAeTtsAssets(AssetManager assets, String assetPath, File target) throws IOException {
        String[] children = assets.list(assetPath);
        if (children != null && children.length > 0) {
            if (!target.exists() && !target.mkdirs()) throw new IOException("无法创建离线模型目录。");
            for (String child : children) {
                copyAeTtsAssets(assets, assetPath + "/" + child, new File(target, child));
            }
            return;
        }
        if (target.isFile() && target.length() > 0) return;
        File parent = target.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("无法创建离线模型文件夹。");
        }
        File temporary = new File(target.getAbsolutePath() + ".part");
        try (InputStream input = assets.open(assetPath);
             FileOutputStream output = new FileOutputStream(temporary)) {
            byte[] buffer = new byte[32768];
            int read;
            while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
            output.flush();
        }
        if (target.exists()) target.delete();
        if (!temporary.renameTo(target)) {
            temporary.delete();
            throw new IOException("离线模型写入失败：" + target.getName());
        }
    }

    private static native float[] pitchShiftSamples(float[] samples, int sampleRate, double semitones);

    public static void startTextToSpeech(String text, float pitch, float rate, int speakerId, String requestId) {
        __CLASS__ activity = galleryActivity;
        if (activity == null || requestId == null || requestId.isEmpty()) {
            if (requestId != null) aeTtsResults.put(requestId, "ERROR: Ae 尚未准备好语音服务。");
            return;
        }
        if (text == null || text.trim().isEmpty()) {
            aeTtsResults.put(requestId, "ERROR: 请先输入文字内容。");
            return;
        }
        if (text.length() > 2000) {
            aeTtsResults.put(requestId, "ERROR: 单次本地配音最多支持 2000 个字符，请分段生成，避免手机内存不足。");
            return;
        }
        aeTtsResults.put(requestId, "PENDING");
        Future<?> old = aeTtsJobs.remove(requestId);
        if (old != null) old.cancel(true);
        Future<?> job = aeTtsExecutor.submit(() -> {
            try {
                OfflineTts tts = getAeOfflineTts(activity);
                int sid = Math.max(0, Math.min(4, speakerId));
                float speed = Math.max(0.5f, Math.min(2.0f, rate));
                GeneratedAudio generated = tts.generate(text, sid, speed);
                if (generated == null || generated.getSamples() == null || generated.getSamples().length == 0) {
                    throw new IllegalStateException("本地语音模型没有生成有效音频。");
                }
                float[] samples = generated.getSamples();
                double semitones = 12.0 * Math.log(Math.max(0.5, Math.min(2.0, pitch))) / Math.log(2.0);
                if (Math.abs(semitones) > 0.02) {
                    System.loadLibrary("AePitchShifter");
                    samples = pitchShiftSamples(samples, generated.getSampleRate(), semitones);
                    if (samples == null || samples.length == 0) {
                        throw new IllegalStateException("音调处理失败，请重试。");
                    }
                }
                GeneratedAudio outputAudio = new GeneratedAudio(samples, generated.getSampleRate());
                // Generated voice clips must survive cache cleanup and be importable later.
                File directory = new File(activity.getFilesDir(), "AeMedia/Voice");
                if (!directory.exists() && !directory.mkdirs()) {
                    throw new IOException("无法创建配音保存目录。");
                }
                String safeId = requestId.replaceAll("[^A-Za-z0-9_-]", "_");
                File output = new File(directory, safeId + ".wav");
                if (output.exists()) output.delete();
                if (!outputAudio.save(output.getAbsolutePath()) || !output.isFile() || output.length() < 44) {
                    throw new IOException("本地配音 WAV 保存失败。");
                }
                output.setReadable(true, true);
                output.setWritable(true, true);
                aeTtsResults.put(requestId, "OK:" + output.getAbsolutePath());
            } catch (Throwable error) {
                String detail = error.getMessage();
                aeTtsResults.put(requestId, "ERROR: " +
                    (detail == null || detail.trim().isEmpty() ? error.getClass().getSimpleName() : detail));
            } finally {
                aeTtsJobs.remove(requestId);
            }
        });
        aeTtsJobs.put(requestId, job);
    }

    public static String pollTextToSpeech(String requestId) {
        if (requestId == null) return null;
        String result = aeTtsResults.get(requestId);
        if (result == null || "PENDING".equals(result)) return null;
        return aeTtsResults.remove(requestId);
    }

    public static void cancelTextToSpeech(String requestId) {
        if (requestId == null) return;
        Future<?> job = aeTtsJobs.remove(requestId);
        if (job != null) job.cancel(true);
        aeTtsResults.put(requestId, "ERROR: 已取消配音生成。");
    }
'''


RUST_TTS = r'''
#[cfg(target_os = "android")]
pub fn start_tts(text: &str, pitch: f32, rate: f32, speaker_id: i32, request_id: &str) -> Result<(), String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let text = env.new_string(text)?;
            let id = env.new_string(request_id)?;
            env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("startTextToSpeech"),
                jni::jni_sig!("(Ljava/lang/String;FFILjava/lang/String;)V"),
                &[
                    jni::objects::JValue::Object(&text),
                    jni::objects::JValue::Float(pitch),
                    jni::objects::JValue::Float(rate),
                    jni::objects::JValue::Int(speaker_id),
                    jni::objects::JValue::Object(&id),
                ],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub fn start_tts(_text: &str, _pitch: f32, _rate: f32, _speaker_id: i32, _request_id: &str) -> Result<(), String> {
    Err("当前平台不支持本地 Android 语音合成。".into())
}

#[cfg(target_os = "android")]
pub fn poll_tts(request_id: &str) -> Result<Option<String>, String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<Option<String>> {
            let id = env.new_string(request_id)?;
            let object = env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("pollTextToSpeech"),
                jni::jni_sig!("(Ljava/lang/String;)Ljava/lang/String;"),
                &[jni::objects::JValue::Object(&id)],
            )?.l()?;
            if object.is_null() { return Ok(None); }
            let value = env.as_cast::<jni::objects::JString>(&object)?;
            Ok(Some(value.to_string()))
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub fn poll_tts(_request_id: &str) -> Result<Option<String>, String> {
    Ok(Some("ERROR: 当前平台不支持本地 Android 语音合成。".into()))
}

#[cfg(target_os = "android")]
pub fn cancel_tts(request_id: &str) -> Result<(), String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let id = env.new_string(request_id)?;
            env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("cancelTextToSpeech"),
                jni::jni_sig!("(Ljava/lang/String;)V"),
                &[jni::objects::JValue::Object(&id)],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub fn cancel_tts(_request_id: &str) -> Result<(), String> {
    Err("当前平台不支持本地 Android 语音合成。".into())
}
'''


AM_EDITOR_HELPER = r'''
// EFFECTCRAFT_AM_TEXT_VOICE_EDITOR_V1
fn am_text_voice_editor(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect, layer_id: u64) {
    let ctx = ui.ctx().clone();
    let time = app.session.time();
    let initial = app.session.active_comp()
        .and_then(|comp| comp.layers.iter().find(|layer| layer.id.0 == layer_id))
        .and_then(|layer| layer.props.prop("text/sourceText").map(|prop| prop.value_at(layer.layer_time(time))))
        .map(|value| match value {
            KV::Text(doc) => doc.text.clone(),
            KV::Str(text) => text,
            _ => String::new(),
        })
        .unwrap_or_default();
    let text_id = Id::new(("am-text-voice-content", layer_id));
    let mut text = ctx.data(|d| d.get_temp::<String>(text_id)).unwrap_or(initial);
    let mut pitch = ctx.data(|d| d.get_temp::<f32>(Id::new(("am-text-voice-pitch", layer_id)))).unwrap_or(1.0);
    let mut rate = ctx.data(|d| d.get_temp::<f32>(Id::new(("am-text-voice-rate", layer_id)))).unwrap_or(1.0);
    let mut speaker_id = ctx.data(|d| d.get_temp::<i32>(Id::new(("am-text-voice-speaker", layer_id)))).unwrap_or(0);
    let selected_audio_layers: Vec<u64> = app.session.active_comp().map(|comp| {
        app.session.state.selected_layers.iter().filter_map(|selected| {
            comp.layers.iter()
                .find(|layer| layer.id == *selected && layer.props.prop("audio/levels").is_some())
                .map(|layer| layer.id.0)
        }).collect()
    }).unwrap_or_default();
    let mut music_volume_db = ctx.data(|d| d.get_temp::<f32>(Id::new(("am-text-voice-music-volume", layer_id)))).unwrap_or(0.0);
    let pending_id = Id::new(("am-text-voice-pending", layer_id));
    let t = app.tokens;
    ui.painter().with_clip_rect(rect).rect_filled(rect, 0.0, t.panel_bg);

    // Two side-by-side pages inside one compact sheet: swipe horizontally to move
    // between text editing and AI voice settings. The sheet never exceeds the timeline.
    let mut pages = ui.new_child(egui::UiBuilder::new().max_rect(rect.shrink2(vec2(8.0, 6.0))));
    egui::ScrollArea::horizontal()
        .id_salt("am-text-voice-horizontal-pages")
        .auto_shrink([false, false])
        // Keep finger-drag paging on Android using the current egui ScrollSource API.
        .scroll_source(egui::scroll_area::ScrollSource::DRAG)
        .show(&mut pages, |pages_ui| {
            let page_w = rect.width() - 16.0;
            let page_h = rect.height() - 12.0;
            pages_ui.set_min_width(page_w * 2.0);
            pages_ui.horizontal(|pages_ui| {
                pages_ui.allocate_ui_with_layout(
                    vec2(page_w, page_h),
                    egui::Layout::top_down(egui::Align::Min),
                    |page| {
                        page.label("文字内容 · 向左滑动进入配音");
                        let edit = page.add_sized(
                            [page_w - 12.0, (page_h - 66.0).max(74.0)],
                            egui::TextEdit::multiline(&mut text)
                                .desired_rows(3)
                                .font(Tokens::ui(11.0))
                                .hint_text("在这里编辑文字内容"),
                        );
                        if edit.changed() {
                            ctx.data_mut(|d| d.insert_temp(text_id, text.clone()));
                            if let Err(error) = app.session.execute("layer.setText", json!({
                                "layer": layer_id, "text": text.clone(), "merge": "am-text-voice"
                            })) {
                                app.ui.status = format!("文字修改失败：{error}");
                            } else {
                                ctx.request_repaint();
                            }
                        }
                        if page.add_sized([page_w - 12.0, 32.0], egui::Button::new("画布编辑文字")).clicked() {
                            invoke(app, &ctx, "text.edit", json!({"layer": layer_id}));
                            ctx.data_mut(|d| {
                                d.remove::<String>(Id::new("am-mobile-tool-drawer"));
                                d.remove::<u64>(Id::new(AM_ACTIVE_LAYER_ID));
                            });
                        }
                    },
                );
                pages_ui.allocate_ui_with_layout(
                    vec2(page_w, page_h),
                    egui::Layout::top_down(egui::Align::Min),
                    |page| {
                        page.label("AI 配音 · 向右滑动返回文字");
                        page.horizontal(|page| {
                            let generate = page.add_sized([page_w * 0.47, 34.0], egui::Button::new("生成本地 AI 配音"));
                            app.auto.add_response("am.textvoice.generate", &generate, "使用 Ae 内置离线中文语音模型生成配音");
                            if generate.clicked()
                                && ctx.data(|d| d.get_temp::<String>(pending_id).is_none())
                                && !text.trim().is_empty()
                            {
                                let request_id = format!("am-tts-{layer_id}-{}-{}", app.session.revision,
                                    (ctx.input(|i| i.time) * 1000.0) as u64);
                                match crate::android_gallery::start_tts(&text, pitch, rate, speaker_id, &request_id) {
                                    Ok(()) => {
                                        ctx.data_mut(|d| d.insert_temp(pending_id, request_id));
                                        app.ui.status = "正在本地生成配音…".into();
                                    }
                                    Err(error) => app.ui.status = format!("无法启动本地配音：{error}"),
                                }
                            } else if generate.clicked() && text.trim().is_empty() {
                                app.ui.status = "请先输入需要配音的文字。".into();
                            }
                            if page.add_sized([page_w * 0.47, 34.0], egui::Button::new("导入背景音乐")).clicked() {
                                invoke(app, &ctx, "file.import", json!({}));
                            }
                        });
                        page.label("选择本地发音人 · 左右滑动");
                        egui::ScrollArea::horizontal()
                            .id_salt(("am-local-tts-voices", layer_id))
                            .auto_shrink([false, true])
                            .scroll_source(egui::scroll_area::ScrollSource::DRAG)
                            .show(page, |voices_ui| {
                                voices_ui.horizontal(|voices_ui| {
                                    for sid in 0..5 {
                                        let voice = voices_ui.selectable_label(speaker_id == sid, format!("音色 {}", sid + 1));
                                        if voice.clicked() { speaker_id = sid; }
                                    }
                                });
                            });
                        page.label(format!("当前发音人：音色 {}", speaker_id + 1));
                        page.add(egui::Slider::new(&mut pitch, 0.5..=2.0).text("音调"));
                        page.add(egui::Slider::new(&mut rate, 0.5..=2.0).text("语速"));
                        ctx.data_mut(|d| {
                            d.insert_temp(Id::new(("am-text-voice-pitch", layer_id)), pitch);
                            d.insert_temp(Id::new(("am-text-voice-rate", layer_id)), rate);
                            d.insert_temp(Id::new(("am-text-voice-speaker", layer_id)), speaker_id);
                        });
                        if selected_audio_layers.is_empty() {
                            page.label("音乐音量：先在时间轴选择音乐/音频图层。");
                        } else {
                            let volume = page.add(egui::Slider::new(&mut music_volume_db, -60.0..=12.0).text("音乐音量 (dB)"));
                            if volume.changed() {
                                for audio_layer in &selected_audio_layers {
                                    if let Err(error) = app.session.execute("prop.set", json!({
                                        "layer": audio_layer, "path": "audio/levels",
                                        "value": [music_volume_db, music_volume_db],
                                        "merge": "am-music-volume"
                                    })) {
                                        app.ui.status = format!("音乐音量调整失败：{error}");
                                    }
                                }
                                ctx.request_repaint();
                            }
                            ctx.data_mut(|d| d.insert_temp(Id::new(("am-text-voice-music-volume", layer_id)), music_volume_db));
                        }
                        page.label("使用 Ae 内置离线中文模型生成；首次启动会准备本地模型，之后无需联网。");
                        if let Some(request_id) = ctx.data(|d| d.get_temp::<String>(pending_id)) {
                            if page.add_sized([page_w - 12.0, 30.0], egui::Button::new("取消配音生成")).clicked() {
                                let _ = crate::android_gallery::cancel_tts(&request_id);
                                ctx.data_mut(|d| d.remove::<String>(pending_id));
                                app.ui.status = "已取消配音生成。".into();
                            }
                        }
                    },
                );
            });
        });

    if let Some(request_id) = ctx.data(|d| d.get_temp::<String>(pending_id)) {
        match crate::android_gallery::poll_tts(&request_id) {
            Ok(Some(result)) => {
                ctx.data_mut(|d| d.remove::<String>(pending_id));
                if let Some(path) = result.strip_prefix("OK:") {
                    match crate::menus::invoke(app, &ctx, "file.import", json!({"paths": [path]})) {
                        Ok(_) => app.ui.status = "配音已生成并加入当前合成时间轴。".into(),
                        Err(error) => app.ui.status = format!("配音已生成，但导入失败：{error}"),
                    }
                } else {
                    app.ui.status = result.strip_prefix("ERROR:").unwrap_or(&result).to_string();
                }
            }
            Ok(None) => ctx.request_repaint_after(std::time::Duration::from_millis(160)),
            Err(error) => {
                ctx.data_mut(|d| d.remove::<String>(pending_id));
                app.ui.status = format!("配音状态读取失败：{error}");
            }
        }
    }
}
'''


def patch_activity(builder: Path) -> None:
    path = builder / "templates/android/SafActivity.java"
    source = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_AM_TEXT_TO_SPEECH_V1" not in source:
        anchor = "import android.content.Context;\n"
        imports = "".join(item + "\n" for item in JAVA_IMPORTS if item not in source)
        source = once(source, anchor, anchor + imports, "Android TTS imports")
        anchor = "    public static String createGalleryStagingPath(String requestedName) {\n"
        source = once(source, anchor, JAVA_TTS + "\n" + anchor, "Android TTS bridge")
        destroy = "    protected void onDestroy() {\n"
        cleanup = "        // Keep the process-owned offline TTS model alive across Activity recreation.\n"
        source = once(source, destroy, destroy + cleanup, "Android TTS cleanup")
    path.write_text(source, encoding="utf-8")


def patch_gallery_rust(root: Path) -> None:
    path = root / "crates/ui-egui/src/android_gallery.rs"
    source = path.read_text(encoding="utf-8")
    if "pub fn start_tts(" not in source:
        anchor = '#[cfg(not(target_os = "android"))]\npub(crate) fn poll_publish(_request_id: &str) -> Result<Option<String>, String> {\n    Ok(Some("ERROR: 当前平台不支持 Android 相册发布。".into()))\n}\n'
        source = once(source, anchor, anchor + "\n" + RUST_TTS, "Rust Android TTS JNI methods")
        path.write_text(source, encoding="utf-8")


def patch_am_editor(root: Path) -> None:
    path = root / "crates/ui-egui/src/am_editor.rs"
    source = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_AM_TEXT_VOICE_EDITOR_V1" not in source:
        source = once(source, "use serde_json::json;\n", "use serde_json::json;\nuse effectcraft_keyframe::Value as KV;\n", "AM text document import")
        source = once(source, "fn tool_drawer(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {\n",
                      AM_EDITOR_HELPER + "\nfn tool_drawer(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {\n",
                      "AM text and voice editor")
        source = once(source, '        "keyframes" => Some(PanelKind::Timeline),\n',
                      '        "keyframes" => Some(PanelKind::Timeline),\n        "text_voice" => None,\n',
                      "AM text voice drawer kind")
        source = once(source, '        "keyframes" => "关键帧 / 曲线",\n',
                      '        "keyframes" => "关键帧 / 曲线",\n        "text_voice" => "文字与配音",\n',
                      "AM text voice drawer title")
        source = source.replace('if kind != "add" && kind != "motion" {',
                                'if kind != "add" && kind != "motion" && kind != "text_voice" {', 1)
        close_anchor = '''    if response.clicked() {
        ui.ctx().data_mut(|d| d.remove::<String>(id));
        return;
    }
    if kind == "add" {'''
        close_replacement = '''    if response.clicked() {
        ui.ctx().data_mut(|d| d.remove::<String>(id));
        return;
    }
    if kind == "text_voice" {
        if let Some(layer_id) = ui.ctx().data(|d| d.get_temp::<u64>(Id::new(AM_ACTIVE_LAYER_ID))) {
            am_text_voice_editor(app, ui, body, layer_id);
        } else {
            ui.painter().text(body.center(), Align2::CENTER_CENTER, "请先选择文字图层。", Tokens::ui(11.0), app.tokens.text_dim);
        }
        return;
    }
    if kind == "add" {'''
        source = once(source, close_anchor, close_replacement, "render AM text voice editor")
        height_anchor = '''    let sheet_h = if let Some(kind) = drawer_kind.as_deref() {
        if kind == "motion" {'''
        height_replacement = '''    let sheet_h = if let Some(kind) = drawer_kind.as_deref() {
        if kind == "text_voice" {
            (rect.height() * 0.38).clamp(240.0, 420.0).min(timeline_rect.height().max(200.0))
        } else if kind == "motion" {'''
        source = once(source, height_anchor, height_replacement, "keep text voice sheet no taller than timeline")
        path.write_text(source, encoding="utf-8")
    for token in ("EFFECTCRAFT_AM_TEXT_VOICE_EDITOR_V1", "text_voice", "text.edit", "layer.setText",
                  "start_tts", "poll_tts", "导入背景音乐", "取消配音生成"):
        if token not in source:
            raise SystemExit(f"AM text voice editor missing: {token}")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not root.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to the checked-out source and Android builder.")
    patch_activity(builder)
    patch_gallery_rust(root)
    patch_am_editor(root)
    print("Installed AM text editing, pitch/rate controls, cancellable TTS synthesis and background-music import.")


if __name__ == "__main__":
    main()
