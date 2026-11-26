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
    "import android.speech.tts.TextToSpeech;",
    "import android.speech.tts.UtteranceProgressListener;",
    "import java.util.Locale;",
)

JAVA_TTS = r'''
    // EFFECTCRAFT_ANDROID_AM_TEXT_TO_SPEECH_V1
    private static volatile TextToSpeech aeTextToSpeech;
    private static final ConcurrentHashMap<String, String> aeTtsResults = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, String> aeTtsPaths = new ConcurrentHashMap<>();

    public static void startTextToSpeech(String text, float pitch, float rate, String requestId) {
        __CLASS__ activity = galleryActivity;
        if (activity == null || requestId == null || requestId.isEmpty()) {
            if (requestId != null) aeTtsResults.put(requestId, "ERROR: Ae 尚未准备好语音服务。");
            return;
        }
        if (text == null || text.trim().isEmpty()) {
            aeTtsResults.put(requestId, "ERROR: 请先输入文字内容。");
            return;
        }
        aeTtsResults.remove(requestId);
        aeTtsPaths.remove(requestId);
        activity.runOnUiThread(() -> {
            if (aeTextToSpeech == null) {
                aeTextToSpeech = new TextToSpeech(activity, status -> {
                    if (status != TextToSpeech.SUCCESS || aeTextToSpeech == null) {
                        aeTtsResults.put(requestId, "ERROR: 手机当前语音引擎初始化失败。");
                        return;
                    }
                    aeTextToSpeech.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                        @Override public void onStart(String utteranceId) {}
                        @Override public void onDone(String utteranceId) {
                            String path = aeTtsPaths.remove(utteranceId);
                            aeTtsResults.put(utteranceId, path == null
                                ? "ERROR: 配音文件路径丢失。" : "OK:" + path);
                        }
                        @Override public void onError(String utteranceId) {
                            aeTtsPaths.remove(utteranceId);
                            aeTtsResults.put(utteranceId, "ERROR: 语音引擎生成配音失败。");
                        }
                        @Override public void onError(String utteranceId, int errorCode) {
                            aeTtsPaths.remove(utteranceId);
                            aeTtsResults.put(utteranceId, "ERROR: 语音合成失败（" + errorCode + "）。");
                        }
                    });
                    int language = aeTextToSpeech.setLanguage(Locale.SIMPLIFIED_CHINESE);
                    if (language == TextToSpeech.LANG_MISSING_DATA || language == TextToSpeech.LANG_NOT_SUPPORTED) {
                        aeTextToSpeech.setLanguage(Locale.getDefault());
                    }
                    synthesizeAeSpeech(activity, text, pitch, rate, requestId);
                });
            } else {
                synthesizeAeSpeech(activity, text, pitch, rate, requestId);
            }
        });
    }

    private static void synthesizeAeSpeech(__CLASS__ activity, String text, float pitch, float rate, String requestId) {
        try {
            if (aeTextToSpeech == null) {
                aeTtsResults.put(requestId, "ERROR: 手机语音引擎尚未初始化。");
                return;
            }
            aeTextToSpeech.setPitch(Math.max(0.5f, Math.min(2.0f, pitch)));
            aeTextToSpeech.setSpeechRate(Math.max(0.5f, Math.min(2.0f, rate)));
            File directory = new File(activity.getCacheDir(), "AeTTS");
            if (!directory.exists() && !directory.mkdirs()) {
                aeTtsResults.put(requestId, "ERROR: 无法创建配音暂存目录。");
                return;
            }
            String safeId = requestId.replaceAll("[^A-Za-z0-9_-]", "_");
            File output = new File(directory, safeId + ".wav");
            if (output.exists()) output.delete();
            aeTtsPaths.put(requestId, output.getAbsolutePath());
            int result = aeTextToSpeech.synthesizeToFile(text, new Bundle(), output, requestId);
            if (result != TextToSpeech.SUCCESS) {
                aeTtsPaths.remove(requestId);
                aeTtsResults.put(requestId, "ERROR: 当前语音引擎拒绝生成音频。");
            }
        } catch (Exception error) {
            aeTtsPaths.remove(requestId);
            String detail = error.getMessage();
            aeTtsResults.put(requestId, "ERROR: " +
                (detail == null || detail.trim().isEmpty() ? error.getClass().getSimpleName() : detail));
        }
    }

    public static String pollTextToSpeech(String requestId) {
        return requestId == null ? null : aeTtsResults.remove(requestId);
    }

    public static void cancelTextToSpeech(String requestId) {
        if (aeTextToSpeech != null) {
            try { aeTextToSpeech.stop(); } catch (Exception ignored) {}
        }
        if (requestId != null) {
            aeTtsPaths.remove(requestId);
            aeTtsResults.put(requestId, "ERROR: 已取消配音生成。");
        }
    }
'''


RUST_TTS = r'''
#[cfg(target_os = "android")]
pub fn start_tts(text: &str, pitch: f32, rate: f32, request_id: &str) -> Result<(), String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let text = env.new_string(text)?;
            let id = env.new_string(request_id)?;
            env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("startTextToSpeech"),
                jni::jni_sig!("(Ljava/lang/String;FFLjava/lang/String;)V"),
                &[
                    jni::objects::JValue::Object(&text),
                    jni::objects::JValue::Float(pitch),
                    jni::objects::JValue::Float(rate),
                    jni::objects::JValue::Object(&id),
                ],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub fn start_tts(_text: &str, _pitch: f32, _rate: f32, _request_id: &str) -> Result<(), String> {
    Err("当前平台不支持 Android 语音合成。".into())
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
    Ok(Some("ERROR: 当前平台不支持 Android 语音合成。".into()))
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
    Err("当前平台不支持 Android 语音合成。".into())
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
    let pending_id = Id::new(("am-text-voice-pending", layer_id));
    let t = app.tokens;
    ui.painter().with_clip_rect(rect).rect_filled(rect, 0.0, t.panel_bg);

    // Two side-by-side pages inside one compact sheet: swipe horizontally to move
    // between text editing and AI voice settings. The sheet never exceeds the timeline.
    let mut pages = ui.new_child(egui::UiBuilder::new().max_rect(rect.shrink2(vec2(8.0, 6.0))));
    egui::ScrollArea::horizontal()
        .id_salt("am-text-voice-horizontal-pages")
        .auto_shrink([false, false])
        .drag_to_scroll(true)
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
                        page.add(egui::Slider::new(&mut pitch, 0.5..=2.0).text("音调"));
                        page.add(egui::Slider::new(&mut rate, 0.5..=2.0).text("语速"));
                        ctx.data_mut(|d| {
                            d.insert_temp(Id::new(("am-text-voice-pitch", layer_id)), pitch);
                            d.insert_temp(Id::new(("am-text-voice-rate", layer_id)), rate);
                        });
                        page.label("使用手机当前语音引擎；可将 CloneTTS 等离线 AI 语音设为系统默认引擎。");
                        page.horizontal(|page| {
                            if page.add_sized([page_w * 0.47, 34.0], egui::Button::new("导入背景音乐")).clicked() {
                                invoke(app, &ctx, "file.import", json!({}));
                            }
                            let voice = page.add_sized([page_w * 0.47, 34.0], egui::Button::new("生成 AI 配音"));
                            app.auto.add_response("am.textvoice.generate", &voice, "使用当前系统语音引擎生成配音");
                            if voice.clicked() && !text.trim().is_empty() {
                                let request_id = format!("am-tts-{layer_id}-{}-{}", app.session.revision,
                                    (ctx.input(|i| i.time) * 1000.0) as u64);
                                match crate::android_gallery::start_tts(&text, pitch, rate, &request_id) {
                                    Ok(()) => {
                                        ctx.data_mut(|d| d.insert_temp(pending_id, request_id));
                                        app.ui.status = "正在生成配音…".into();
                                    }
                                    Err(error) => app.ui.status = format!("无法启动配音：{error}"),
                                }
                            } else if voice.clicked() {
                                app.ui.status = "请先输入需要配音的文字。".into();
                            }
                        });
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
        cleanup = "        if (aeTextToSpeech != null) { try { aeTextToSpeech.stop(); aeTextToSpeech.shutdown(); } catch (Exception ignored) {} aeTextToSpeech = null; }\n"
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
