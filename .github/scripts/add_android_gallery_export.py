#!/usr/bin/env python3
"""Publish completed EffectCraft video exports to Android Gallery and show a confirmed-success popup."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str, count: int = 1) -> str:
    actual = source.count(old)
    if actual != count:
        raise SystemExit(f"{label}: expected {count} occurrence(s), found {actual}")
    return source.replace(old, new, count)


RUST_MODULE = r'''use std::sync::atomic::{AtomicUsize, Ordering};

#[cfg(target_os = "android")]
static ANDROID_VM: AtomicUsize = AtomicUsize::new(0);

#[cfg(target_os = "android")]
pub fn init_android_gallery_vm(ptr: *mut std::ffi::c_void) {
    ANDROID_VM.store(ptr as usize, Ordering::Release);
}

#[cfg(target_os = "android")]
fn with_vm<T>(f: impl FnOnce(&jni::vm::JavaVM) -> Result<T, String>) -> Result<T, String> {
    let ptr = ANDROID_VM.load(Ordering::Acquire);
    if ptr == 0 {
        return Err("Android 相册接口尚未初始化。".into());
    }
    let vm = jni::vm::JavaVM::singleton().map_err(|error| error.to_string())?;
    f(&vm)
}

#[cfg(target_os = "android")]
pub(crate) fn start_publish(path: &str, request_id: &str) -> Result<(), String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let path = env.new_string(path)?;
            let id = env.new_string(request_id)?;
            env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("startGalleryPublish"),
                jni::jni_sig!("(Ljava/lang/String;Ljava/lang/String;)V"),
                &[
                    jni::objects::JValue::Object(&path),
                    jni::objects::JValue::Object(&id),
                ],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub(crate) fn start_publish(_path: &str, _request_id: &str) -> Result<(), String> {
    Err("视频发布到 Android 相册仅在 Android 版本中可用。".into())
}

/// None means MediaStore is still copying; Some("OK") or Some("ERROR: ...") is final.
#[cfg(target_os = "android")]
pub(crate) fn poll_publish(request_id: &str) -> Result<Option<String>, String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<Option<String>> {
            let id = env.new_string(request_id)?;
            let object = env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("pollGalleryPublish"),
                jni::jni_sig!("(Ljava/lang/String;)Ljava/lang/String;"),
                &[jni::objects::JValue::Object(&id)],
            )?.l()?;
            if object.is_null() {
                return Ok(None);
            }
            let value = env.as_cast::<jni::objects::JString>(&object)?;
            Ok(Some(value.to_string()))
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub(crate) fn poll_publish(_request_id: &str) -> Result<Option<String>, String> {
    Ok(Some("ERROR: 当前平台不支持 Android 相册发布。".into()))
}
'''


JAVA_IMPORTS = [
    "import android.content.ContentValues;",
    "import android.media.MediaScannerConnection;",
    "import android.provider.MediaStore;",
    "import java.util.concurrent.ConcurrentHashMap;",
]

JAVA_BRIDGE = r'''
    // EFFECTCRAFT_ANDROID_MEDIASTORE_GALLERY_V1
    private static volatile __CLASS__ galleryActivity;
    private static final ConcurrentHashMap<String, String> galleryPublishResults = new ConcurrentHashMap<>();

    public static void startGalleryPublish(String sourcePath, String requestId) {
        __CLASS__ activity = galleryActivity;
        if (activity == null || sourcePath == null || requestId == null || requestId.isEmpty()) {
            if (requestId != null) galleryPublishResults.put(requestId, "ERROR: EffectCraft 已退出，无法保存到相册。");
            return;
        }
        activity.io.execute(() -> {
            Uri inserted = null;
            try {
                File source = new File(sourcePath);
                if (!source.isFile() || source.length() <= 0) {
                    throw new IllegalStateException("未找到已导出的视频文件。");
                }
                String name = source.getName();
                String lower = name.toLowerCase(java.util.Locale.ROOT);
                String mime = lower.endsWith(".webm") ? "video/webm"
                    : lower.endsWith(".mov") ? "video/quicktime"
                    : lower.endsWith(".mkv") ? "video/x-matroska"
                    : lower.endsWith(".avi") ? "video/x-msvideo" : "video/mp4";

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    ContentValues values = new ContentValues();
                    values.put(MediaStore.Video.Media.DISPLAY_NAME, name);
                    values.put(MediaStore.Video.Media.MIME_TYPE, mime);
                    values.put(MediaStore.Video.Media.RELATIVE_PATH,
                        Environment.DIRECTORY_DCIM + "/EffectCraft");
                    values.put(MediaStore.Video.Media.IS_PENDING, 1);
                    inserted = getContentResolver().insert(
                        MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values);
                    if (inserted == null) {
                        throw new IllegalStateException("Android 相册没有接受视频文件。");
                    }
                    try (InputStream input = new BufferedInputStream(new FileInputStream(source));
                         OutputStream raw = getContentResolver().openOutputStream(inserted, "w")) {
                        if (raw == null) throw new IllegalStateException("无法写入 Android 相册。");
                        try (java.io.BufferedOutputStream output = new java.io.BufferedOutputStream(raw)) {
                            byte[] buffer = new byte[1024 * 1024];
                            int count;
                            long written = 0;
                            while ((count = input.read(buffer)) != -1) {
                                output.write(buffer, 0, count);
                                written += count;
                            }
                            output.flush();
                            if (written != source.length()) {
                                throw new IllegalStateException("视频复制到相册时字节数不一致。");
                            }
                        }
                    }
                    ContentValues publish = new ContentValues();
                    publish.put(MediaStore.Video.Media.IS_PENDING, 0);
                    if (getContentResolver().update(inserted, publish, null, null) <= 0) {
                        throw new IllegalStateException("视频已复制，但未能完成相册发布。");
                    }
                } else {
                    File album = new File(
                        Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DCIM),
                        "EffectCraft");
                    if (!album.exists() && !album.mkdirs()) {
                        throw new IllegalStateException("无法创建 DCIM/EffectCraft 相册目录。");
                    }
                    File destination = new File(album, name);
                    try (InputStream input = new BufferedInputStream(new FileInputStream(source));
                         OutputStream output = new java.io.BufferedOutputStream(new FileOutputStream(destination))) {
                        byte[] buffer = new byte[1024 * 1024];
                        int count;
                        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                    }
                    MediaScannerConnection.scanFile(
                        this, new String[] { destination.getAbsolutePath() }, new String[] { mime }, null);
                }

                source.delete();
                galleryPublishResults.put(requestId, "OK");
                Log.i(TAG, "Published EffectCraft video to DCIM/EffectCraft: " + name);
            } catch (Exception error) {
                if (inserted != null) {
                    try { getContentResolver().delete(inserted, null, null); } catch (Exception ignored) {}
                }
                String detail = error.getMessage();
                galleryPublishResults.put(requestId, "ERROR: " +
                    (detail == null || detail.trim().isEmpty() ? error.getClass().getSimpleName() : detail));
                Log.e(TAG, "Could not publish EffectCraft video to Android Gallery.", error);
            }
        });
    }

    public static String pollGalleryPublish(String requestId) {
        return requestId == null ? null : galleryPublishResults.remove(requestId);
    }
'''


def patch_android_activity(builder: Path) -> None:
    path = builder / "templates/android/SafActivity.java"
    source = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_MEDIASTORE_GALLERY_V1" not in source:
        anchor = "import android.content.Context;\n"
        imports = "\n".join(item for item in JAVA_IMPORTS if item not in source) + "\n"
        source = replace_once(source, anchor, anchor + imports, "MediaStore Java imports")
        class_anchor = "public final class __CLASS__ extends NativeActivity {\n"
        source = replace_once(source, class_anchor, class_anchor + JAVA_BRIDGE + "\n", "MediaStore gallery bridge")
        create_anchor = "    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n"
        source = replace_once(source, create_anchor, create_anchor + "        galleryActivity = this;\n", "Gallery activity registration")
        destroy_anchor = "    protected void onDestroy() {\n"
        source = replace_once(source, destroy_anchor, destroy_anchor + "        if (galleryActivity == this) galleryActivity = null;\n", "Gallery activity cleanup")
    path.write_text(source, encoding="utf-8")


def patch_builder(builder: Path) -> None:
    path = builder / "lib/build-common.sh"
    source = path.read_text(encoding="utf-8")

    recipe_anchor = "/// Open the picker allowing several files at once (imports take a list); empty on cancel or error.\n"
    stage_fn = r'''
/// Route movie exports to a private staging file. The completed file is later published through
/// Android MediaStore; non-video Save dialogs continue to use the original SAF flow.
fn saf_video_gallery_stage_path(default: &str) -> Result<Option<String>, String> {
    let ext = std::path::Path::new(default)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !matches!(ext.as_str(), "mp4" | "mov" | "webm" | "mkv" | "avi") {
        return Ok(None);
    }
    let name = std::path::Path::new(default)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "视频文件名无效。".to_string())?;
    let directory = std::env::temp_dir().join("EffectCraftExports");
    std::fs::create_dir_all(&directory)
        .map_err(|error| format!("无法创建视频暂存目录：{error}"))?;
    let original = directory.join(name);
    if !original.exists() {
        return Ok(Some(original.to_string_lossy().into_owned()));
    }
    let stem = std::path::Path::new(name).file_stem().and_then(|v| v.to_str()).unwrap_or("EffectCraft");
    let extension = std::path::Path::new(name).extension().and_then(|v| v.to_str()).unwrap_or("mp4");
    for suffix in 1..1000 {
        let candidate = directory.join(format!("{stem}_{suffix}.{extension}"));
        if !candidate.exists() {
            return Ok(Some(candidate.to_string_lossy().into_owned()));
        }
    }
    Err("视频暂存目录中同名文件过多，请清理后重试。".into())
}
'''
    if "fn saf_video_gallery_stage_path(" not in source:
        # Locate the EffectCraft entry inside SAF_RECIPES, not the unrelated SPECIAL map
        # near the top of build-common.sh. Restrict the insertion to that entry's state
        # literal so the same comment in LightCraft is not counted as a second match.
        recipes_marker = "SAF_RECIPES = {"
        if recipes_marker not in source:
            raise SystemExit("Could not find SAF_RECIPES")
        recipes_start = source.index(recipes_marker)
        effectcraft_marker = '    "effectcraft": {'
        effectcraft_start = source.find(effectcraft_marker, recipes_start)
        if effectcraft_start < 0:
            raise SystemExit("Could not find the EffectCraft SAF recipe")
        state_marker = '"state": SYNC_SAF_STATE + '
        state_start = source.find(state_marker, effectcraft_start)
        if state_start < 0:
            raise SystemExit("Could not find the EffectCraft SAF state block")
        state_open = source.find("'''", state_start)
        if state_open < 0:
            raise SystemExit("Could not find the EffectCraft SAF state string")
        state_body_start = state_open + 3
        state_body_end = source.find("'''", state_body_start)
        if state_body_end < 0:
            raise SystemExit("Could not find the end of the EffectCraft SAF state string")
        state_body = source[state_body_start:state_body_end]
        state_body = replace_once(
            state_body, recipe_anchor, stage_fn + "\\n" + recipe_anchor,
            "Video gallery staging helper",
        )
        source = source[:state_body_start] + state_body + source[state_body_end:]

    old_save = '            FileDialog::Save { default, .. } => saf_save_path(&bridge, &state, &default).into_iter().collect(),'
    new_save = r'''            FileDialog::Save { default, .. } => {
                match saf_video_gallery_stage_path(&default) {
                    Ok(Some(path)) => vec![path],
                    Ok(None) => saf_save_path(&bridge, &state, &default).into_iter().collect(),
                    Err(error) => {
                        log::error!("EffectCraft video staging: {error}");
                        Vec::new()
                    }
                }
            },'''
    if new_save not in source:
        source = replace_once(source, old_save, new_save, "Video export SAF routing")

    anchor_vm = "egui_winit::android_activity::set_vm(android_app.vm_as_ptr());"
    gallery_call = anchor_vm + "\n    effectcraft_ui_egui::android_gallery::init_android_gallery_vm(android_app.vm_as_ptr());"
    if "android_gallery::init_android_gallery_vm" not in source:
        source = replace_once(source, anchor_vm, gallery_call, "Android Gallery JNI initialization", 2)
    path.write_text(source, encoding="utf-8")


def patch_ui(effectcraft: Path) -> None:
    ui = effectcraft / "crates/ui-egui/src"
    lib = ui / "lib.rs"
    source = lib.read_text(encoding="utf-8")
    if "mod android_gallery;" not in source:
        source = replace_once(source, "pub mod audio;\n", "pub mod audio;\npub mod android_gallery;\n", "Android Gallery module declaration")
    # The Android launcher is a separate crate and must be able to initialize this module.
    source = source.replace("pub(crate) mod android_gallery;", "pub mod android_gallery;")

    cargo = ui.parent / "Cargo.toml"
    manifest = cargo.read_text(encoding="utf-8")
    if 'jni = "0.22"' not in manifest:
        marker = "[target.'cfg(not(target_arch = \"wasm32\"))'.dependencies]\n"
        manifest = replace_once(manifest, marker, marker + 'jni = "0.22"\n', "Android Gallery JNI dependency")
        cargo.write_text(manifest, encoding="utf-8")
    lib.write_text(source, encoding="utf-8")

    module = ui / "android_gallery.rs"
    if not module.exists() or "pub(crate) fn start_publish" not in module.read_text(encoding="utf-8"):
        module.write_text(RUST_MODULE, encoding="utf-8")
    else:
        module_source = module.read_text(encoding="utf-8")
        module_source = module_source.replace(
            "pub(crate) fn init_android_gallery_vm(",
            "pub fn init_android_gallery_vm(",
        )
        module.write_text(module_source, encoding="utf-8")

    header = ui / "header.rs"
    h = header.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_GALLERY_SUCCESS_POPUP_V1" not in h:
        anchor = '    let all_done = !ids.is_empty() && done_items == ids.len();\n'
        gallery_state = r'''    // EFFECTCRAFT_ANDROID_GALLERY_SUCCESS_POPUP_V1
    let gallery_state_id = visible_id.with("gallery-state");
    let gallery_request_id = visible_id.with("gallery-request");
    let mut gallery_state = ctx.data(|data| data.get_temp::<String>(gallery_state_id).unwrap_or_else(|| "idle".to_string()));
    let mut gallery_request = ctx.data(|data| data.get_temp::<String>(gallery_request_id).unwrap_or_default());

    // Publish only after the Render Queue reports every requested video as Done.
    if all_done && failure.is_none() && gallery_state == "idle" {
        let output_path = ids.iter()
            .filter_map(|id| app.session.project.render_queue.iter().find(|item| item.id == *id))
            .filter_map(|item| item.last_output.clone())
            .last();
        if let Some(path) = output_path {
            gallery_request = format!("effectcraft-gallery-{}", ids.first().copied().unwrap_or(0));
            match crate::android_gallery::start_publish(&path, &gallery_request) {
                Ok(()) => gallery_state = "pending".to_string(),
                Err(error) => gallery_state = format!("error:{error}"),
            }
        } else {
            gallery_state = "error:导出完成，但没有找到最终视频文件。".to_string();
        }
    }

    if all_done && gallery_state == "pending" {
        match crate::android_gallery::poll_publish(&gallery_request) {
            Ok(Some(result)) if result == "OK" => gallery_state = "done".to_string(),
            Ok(Some(result)) => gallery_state = format!("error:{}", result.strip_prefix("ERROR: ").unwrap_or(&result)),
            Ok(None) => ctx.request_repaint_after(std::time::Duration::from_millis(250)),
            Err(error) => gallery_state = format!("error:{error}"),
        }
    }
    ctx.data_mut(|data| {
        data.insert_temp(gallery_state_id, gallery_state.clone());
        data.insert_temp(gallery_request_id, gallery_request.clone());
    });
'''
        h = replace_once(h, anchor, anchor + gallery_state, "Gallery publish state machine")

        old_final = '    let final_state = !rendering && (all_done || failure.is_some() || stopped);'
        new_final = '    let final_state = !rendering && (failure.is_some() || stopped || (all_done && (gallery_state == "done" || gallery_state.starts_with("error:"))));'
        h = replace_once(h, old_final, new_final, "Gallery-aware final state")

        old_heading = '''            if all_done {
                window_ui.heading("导出完成");
            } else if let Some(message) = &failure {'''
        new_heading = '''            if all_done && gallery_state == "done" {
                window_ui.heading("视频已成功导出至相册");
            } else if all_done && gallery_state == "pending" {
                window_ui.heading("正在保存到相册");
                window_ui.horizontal(|ui| { ui.spinner(); ui.label("正在将视频添加到 DCIM/EffectCraft，请稍候…"); });
            } else if all_done && gallery_state.starts_with("error:") {
                window_ui.heading("保存到相册失败");
                window_ui.label(gallery_state.trim_start_matches("error:"));
            } else if all_done {
                window_ui.heading("导出完成，正在准备相册文件…");
            } else if let Some(message) = &failure {'''
        h = replace_once(h, old_heading, new_heading, "Gallery completion message")

        old_actions = '''                if final_state && actions.button("完成").clicked() {
                    close_requested = true;
                }'''
        new_actions = '''                if all_done && gallery_state == "done" {
                    if actions.button("OK").clicked() {
                        close_requested = true;
                    }
                } else if final_state && actions.button("关闭").clicked() {
                    close_requested = true;
                }'''
        h = replace_once(h, old_actions, new_actions, "Gallery OK action")

        old_close = '''            data.remove::<Option<String>>(error_id);
        });'''
        new_close = '''            data.remove::<Option<String>>(error_id);
            data.remove::<String>(gallery_state_id);
            data.remove::<String>(gallery_request_id);
        });'''
        h = replace_once(h, old_close, new_close, "Gallery state cleanup")

        h = h.replace(
            '        .movable(true)\n        .collapsible(false)\n        .resizable(false)\n        .default_pos(ctx.content_rect().center() - vec2(175.0, 105.0))',
            '        .movable(gallery_state != "done")\n        .collapsible(false)\n        .resizable(false)\n        .default_pos(ctx.content_rect().center() - vec2(175.0, 105.0))',
            1,
        )
        header.write_text(h, encoding="utf-8")


def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to the checked-out sources.")
    patch_ui(effectcraft)
    patch_builder(builder)
    patch_android_activity(builder)
    print("Video exports are staged privately rather than sent to the generic document picker.")
    print("Completed videos are published through Android MediaStore to DCIM/EffectCraft.")
    print("The centered success page appears only after MediaStore publication returns OK; its button says OK.")


if __name__ == "__main__":
    main()
