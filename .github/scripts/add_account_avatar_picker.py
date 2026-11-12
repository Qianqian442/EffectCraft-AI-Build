#!/usr/bin/env python3
"""Add a true Android photo-library picker and compact local avatar upload to EffectCraft."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)


ACCOUNT_PATCH_MARKER = "EFFECTCRAFT_ACCOUNT_PHOTO_PICKER_V1"
JAVA_PATCH_MARKER = "EFFECTCRAFT_ANDROID_ACCOUNT_PHOTO_PICKER_V1"
RFD_PATCH_MARKER = "EFFECTCRAFT_RFD_IMAGE_PICKER_V1"


def patch_cargo(effectcraft: Path) -> None:
    cargo = effectcraft / "crates/ui-egui/Cargo.toml"
    source = cargo.read_text(encoding="utf-8")
    dependency_entries = [
        ("base64", 'base64 = "0.22"'),
        ("image", 'image = { version = "0.25", default-features = false, features = ["jpeg", "png", "webp"] }'),
        ("pollster", 'pollster = "0.4"'),
        # The builder vendors its Android SAF-enabled rfd at workspace_root/vendor/rfd.
        # From crates/ui-egui this is ../../vendor/rfd.
        ("rfd", 'rfd = { path = "../../vendor/rfd", default-features = false }'),
    ]
    import re
    match = re.search(r"(?m)^\[dependencies\]\s*$", source)
    if not match:
        raise SystemExit(f"Missing [dependencies] section in {cargo}")
    next_section = re.search(r"(?m)^\[", source[match.end():])
    section_end = match.end() + next_section.start() if next_section else len(source)
    dependency_section = source[match.end():section_end]
    missing = []
    for name, entry in dependency_entries:
        # Check only the normal [dependencies] table. A dev-dependency or
        # target-specific dependency is not visible to account.rs.
        if not re.search(rf"(?m)^\s*{re.escape(name)}\s*=", dependency_section):
            missing.append(entry)
    if missing:
        source = source[:match.end()] + "\n" + "\n".join(missing) + source[match.end():]
    cargo.write_text(source, encoding="utf-8")


def patch_rfd(rfd_root: Path) -> None:
    path = rfd_root / "src/artcraft_saf.rs"
    source = path.read_text(encoding="utf-8")
    if RFD_PATCH_MARKER not in source:
        source = replace_once(
            source,
            "    Open { multiple: bool },\n    /// Where to save one file, with the dialog's suggested file name.\n",
            "    Open { multiple: bool },\n    // EFFECTCRAFT_RFD_IMAGE_PICKER_V1\n    Image,\n    /// Where to save one file, with the dialog's suggested file name.\n",
            "RFD image picker kind",
        )
        source += r'''

/// EFFECTCRAFT_RFD_IMAGE_PICKER_V1
/// Launch Android's image-only system photo picker and return its staged local path.
pub async fn pick_image() -> Option<Vec<PathBuf>> {
    pick(Kind::Image).await
}
'''
    path.write_text(source, encoding="utf-8")


def patch_saf_bridge(builder: Path) -> None:
    path = builder / "templates/android/saf_bridge.rs"
    source = path.read_text(encoding="utf-8")
    marker = "pub fn request_image(&self, id: u64)"
    if marker not in source:
        anchor = '''        pub fn request_save(&self, id: u64, name: &str) -> Result<(), String> {
'''
        method = r'''        pub fn request_image(&self, id: u64) -> Result<(), String> {
            self.vm
                .attach_current_thread(|env| -> jni::errors::Result<()> {
                    let activity_raw = self.app.activity_as_ptr() as jni::sys::jobject;
                    // SAFETY: AndroidApp retains this global Activity reference.
                    let activity = unsafe { env.as_cast_raw::<JObject>(&activity_raw)? };
                    env.call_method(
                        &*activity,
                        jni_str!("safRequestImage"),
                        jni_sig!("(J)V"),
                        &[JValue::Long(id as i64)],
                    )?;
                    Ok(())
                })
                .map_err(|e| e.to_string())
        }

        pub fn pick_image_blocking(&self, id: u64, timeout: Duration) -> Result<PickAnswer, String> {
            let _nonblocking = NonblockingCallbacks::enable();
            self.request_image(id)?;
            self.wait_answer(id, timeout)
        }

'''
        source = replace_once(source, anchor, method + anchor, "Rust SAF image picker bridge")
        path.write_text(source, encoding="utf-8")


def patch_java(builder: Path) -> None:
    path = builder / "templates/android/SafActivity.java"
    source = path.read_text(encoding="utf-8")
    if JAVA_PATCH_MARKER in source:
        return
    source = replace_once(
        source,
        "import android.provider.OpenableColumns;\n",
        "import android.provider.OpenableColumns;\nimport android.provider.MediaStore;\n",
        "MediaStore import",
    )
    source = replace_once(
        source,
        "    private static final int REQ_FOLDER = 0x5046;\n",
        "    private static final int REQ_FOLDER = 0x5046;\n    private static final int REQ_IMAGE = 0x5047;\n",
        "photo picker request code",
    )
    anchor = '''    public void safRequestSave(long id, String suggestedName) {
'''
    method = r'''    // EFFECTCRAFT_ANDROID_ACCOUNT_PHOTO_PICKER_V1
    /** Image-only picker: Android 13+ Photo Picker, older Android system image chooser. */
    public void safRequestImage(long id) {
        runOnUiThread(() -> {
            try {
                Intent intent;
                if (Build.VERSION.SDK_INT >= 33) {
                    intent = new Intent(MediaStore.ACTION_PICK_IMAGES);
                    intent.setType("image/*");
                } else {
                    intent = new Intent(Intent.ACTION_GET_CONTENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("image/*");
                }
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                requestIds.put(REQ_IMAGE, id);
                startActivityForResult(intent, REQ_IMAGE);
            } catch (Exception error) {
                enqueueError(id, "image", error.toString());
            }
        });
    }

'''
    source = replace_once(source, anchor, method + anchor, "Android image-only picker method")
    source = replace_once(
        source,
        "if (requestCode != REQ_OPEN && requestCode != REQ_SAVE && requestCode != REQ_FOLDER) return;",
        "if (requestCode != REQ_OPEN && requestCode != REQ_SAVE && requestCode != REQ_FOLDER && requestCode != REQ_IMAGE) return;",
        "photo picker activity result filter",
    )
    source = replace_once(
        source,
        'final String kind = requestCode == REQ_OPEN ? "open" : requestCode == REQ_SAVE ? "save" : "folder";',
        'final String kind = requestCode == REQ_IMAGE ? "image" : requestCode == REQ_OPEN ? "open" : requestCode == REQ_SAVE ? "save" : "folder";',
        "photo picker result kind",
    )
    source = replace_once(
        source,
        'JSONObject result = base(id, "open", "ok");\n                result.put("paths", paths);\n                results.offer(result.toString());\n            } catch (Exception e) {\n                enqueueError(id, "open", e.toString());',
        'JSONObject result = base(id, kind, "ok");\n                result.put("paths", paths);\n                results.offer(result.toString());\n            } catch (Exception e) {\n                enqueueError(id, kind, e.toString());',
        "preserve image picker result kind",
    )
    path.write_text(source, encoding="utf-8")


def patch_build_common(builder: Path) -> None:
    path = builder / "lib/build-common.sh"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_RFD_IMAGE_PICKER_V1"
    if marker in source:
        return
    prefix = "RFD_SAF_SETUP = '''"
    start = source.index(prefix)
    body_start = start + len(prefix)
    end = source.index("'''", body_start)
    block = source[body_start:end]
    block = replace_once(
        block,
        "            rfd::artcraft_saf::Kind::Open { multiple } => { launcher_bridge.request_open(id, multiple).ok(); }\n",
        "            rfd::artcraft_saf::Kind::Open { multiple } => { launcher_bridge.request_open(id, multiple).ok(); }\n            // EFFECTCRAFT_RFD_IMAGE_PICKER_V1\n            rfd::artcraft_saf::Kind::Image => { launcher_bridge.request_image(id).ok(); }\n",
        "async RFD image picker route",
    )
    block = replace_once(
        block,
        '''            rfd::artcraft_saf::Kind::Folder => blocking_bridge.pick_folder_blocking(id, saf::PICK_TIMEOUT),
''',
        '''            rfd::artcraft_saf::Kind::Folder => blocking_bridge.pick_folder_blocking(id, saf::PICK_TIMEOUT),
            rfd::artcraft_saf::Kind::Image => {
                let answer = blocking_bridge.pick_image_blocking(id, saf::PICK_TIMEOUT);
                if let Ok(saf::PickAnswer::Paths(ref paths)) = answer {
                    for path in paths { blocking_state.mirror.track(id, path); }
                }
                answer
            }
''',
        "blocking RFD image picker route",
    )
    source = source[:body_start] + block + source[end:]
    path.write_text(source, encoding="utf-8")


def patch_account_source(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/account.rs"
    source = path.read_text(encoding="utf-8")
    if ACCOUNT_PATCH_MARKER in source:
        return

    source = replace_once(
        source,
        "use std::time::Duration;\n",
        "use std::time::Duration;\nuse base64::Engine as _;\n",
        "avatar base64 import",
    )
    source = replace_once(
        source,
        "pub(crate) struct AccountState {\n",
        '''// EFFECTCRAFT_ACCOUNT_PHOTO_PICKER_V1
#[derive(Clone, Copy)]
enum AvatarTarget { Register, Profile }

pub(crate) struct AccountState {
''',
        "avatar picker target type",
    )
    source = replace_once(
        source,
        "    status: String,\n    pending: Option<Receiver<Result<HttpResult, String>>>,\n",
        "    status: String,\n    avatar_picker_pending: Option<Receiver<Result<Option<(String, String)>, String>>>,\n    avatar_picker_target: Option<AvatarTarget>,\n    avatar_picker_status: String,\n    pending: Option<Receiver<Result<HttpResult, String>>>,\n",
        "avatar picker state fields",
    )
    source = replace_once(
        source,
        "            status: String::new(),\n            pending: None,\n",
        "            status: String::new(),\n            avatar_picker_pending: None,\n            avatar_picker_target: None,\n            avatar_picker_status: String::new(),\n            pending: None,\n",
        "avatar picker default state",
    )
    helper = r'''
// EFFECTCRAFT_ACCOUNT_PHOTO_PICKER_V1
fn encode_avatar_file(path: &std::path::Path) -> Result<(String, String), String> {
    let name = path.file_name().and_then(|value| value.to_str())
        .unwrap_or("avatar").to_string();
    let bytes = std::fs::read(path).map_err(|error| format!("读取所选图片失败：{error}"))?;
    if bytes.is_empty() || bytes.len() > 32 * 1024 * 1024 {
        return Err("图片文件为空或超过32MB，无法用作头像。".to_string());
    }
    let cursor = std::io::Cursor::new(bytes);
    let mut reader = image::ImageReader::new(cursor)
        .with_guessed_format()
        .map_err(|error| format!("无法识别图片格式：{error}"))?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(8192);
    limits.max_image_height = Some(8192);
    limits.max_alloc = Some(96 * 1024 * 1024);
    reader.limits(limits);
    let decoded = reader.decode().map_err(|error| format!("图片解码失败：{error}"))?;

    let mut side = 256u32;
    let mut quality = 82u8;
    for _ in 0..12 {
        let rgb = decoded.thumbnail(side, side).to_rgb8();
        let thumb = image::DynamicImage::ImageRgb8(rgb);
        let mut jpeg = Vec::new();
        image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpeg, quality)
            .encode_image(&thumb)
            .map_err(|error| format!("压缩头像失败：{error}"))?;
        if jpeg.len() <= 96 * 1024 {
            let encoded = base64::engine::general_purpose::STANDARD.encode(jpeg);
            return Ok((format!("data:image/jpeg;base64,{encoded}"), name));
        }
        if quality > 58 {
            quality = quality.saturating_sub(8);
        } else if side > 128 {
            side = (side * 3 / 4).max(128);
            quality = 76;
        } else {
            break;
        }
    }
    Err("头像压缩后仍然过大，请换一张图片。".to_string())
}

'''
    source = replace_once(source, "impl Default for AccountState {\n", helper + "impl Default for AccountState {\n", "avatar image encoder")
    methods = r'''
    fn start_avatar_picker(&mut self, target: AvatarTarget) {
        if self.avatar_picker_pending.is_some() { return; }
        let (tx, rx) = mpsc::channel();
        self.avatar_picker_pending = Some(rx);
        self.avatar_picker_target = Some(target);
        self.avatar_picker_status = "正在打开手机相册…".to_string();
        std::thread::spawn(move || {
            let result = match pollster::block_on(rfd::artcraft_saf::pick_image()) {
                None => Ok(None),
                Some(paths) => match paths.into_iter().next() {
                    Some(path) => encode_avatar_file(&path).map(Some),
                    None => Ok(None),
                },
            };
            let _ = tx.send(result);
        });
    }

    fn poll_avatar_picker(&mut self) {
        let received = match self.avatar_picker_pending.as_ref().map(|rx| rx.try_recv()) {
            Some(Ok(result)) => Some(result),
            Some(Err(TryRecvError::Disconnected)) => Some(Err("相册选择过程已中断".to_string())),
            Some(Err(TryRecvError::Empty)) | None => None,
        };
        let Some(result) = received else { return; };
        self.avatar_picker_pending = None;
        let target = self.avatar_picker_target.take().unwrap_or(AvatarTarget::Register);
        match result {
            Ok(Some((data_uri, name))) => {
                match target {
                    AvatarTarget::Register => self.avatar_url = data_uri,
                    AvatarTarget::Profile => self.edit_avatar = data_uri,
                }
                self.avatar_picker_status = format!("已选择头像：{name}（已压缩）");
            }
            Ok(None) => {
                self.avatar_picker_status = "已取消选择头像".to_string();
            }
            Err(error) => {
                self.avatar_picker_status = error;
            }
        }
    }

'''
    source = replace_once(source, "    fn send(&mut self, action: Action, method: &str, path: &str, body: Value, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\n", methods + "    fn send(&mut self, action: Action, method: &str, path: &str, body: Value, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\n", "avatar picker methods")
    source = replace_once(
        source,
        "    app.account.poll(config);\n",
        "    app.account.poll(config);\n    app.account.poll_avatar_picker();\n",
        "avatar picker per-frame poll",
    )

    profile_old = '''                    ui.label("头像图片地址（可填写 https 图片链接）");
                    ui.text_edit_singleline(&mut app.account.edit_avatar);
'''
    profile_new = r'''                    ui.label("头像（可选）");
                    ui.horizontal(|ui| {
                        let busy = app.account.avatar_picker_pending.is_some();
                        if ui.add_enabled(!busy, egui::Button::new(if app.account.edit_avatar.is_empty() { "从相册选择头像" } else { "从相册更换头像" })).clicked() {
                            app.account.start_avatar_picker(AvatarTarget::Profile);
                        }
                        if !app.account.edit_avatar.is_empty() && ui.button("移除头像").clicked() {
                            app.account.edit_avatar.clear();
                            app.account.avatar_picker_status = "已移除头像".to_string();
                        }
                    });
                    if !app.account.avatar_picker_status.is_empty() {
                        ui.small(&app.account.avatar_picker_status);
                    }
'''
    source = replace_once(source, profile_old, profile_new, "profile avatar album controls")

    register_old = '''                ui.label("头像图片地址（可选，https 图片链接）");
                ui.text_edit_singleline(&mut app.account.avatar_url);
'''
    register_new = r'''                ui.label("头像（可选）");
                ui.horizontal(|ui| {
                    let busy = app.account.avatar_picker_pending.is_some();
                    if ui.add_enabled(!busy, egui::Button::new(if app.account.avatar_url.is_empty() { "从相册选择头像" } else { "从相册更换头像" })).clicked() {
                        app.account.start_avatar_picker(AvatarTarget::Register);
                    }
                    if !app.account.avatar_url.is_empty() && ui.button("移除头像").clicked() {
                        app.account.avatar_url.clear();
                        app.account.avatar_picker_status = "已移除头像".to_string();
                    }
                });
                if !app.account.avatar_picker_status.is_empty() {
                    ui.small(&app.account.avatar_picker_status);
                }
'''
    source = replace_once(source, register_old, register_new, "registration avatar album controls")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    required = [
        effectcraft / "crates/ui-egui/src/account.rs",
        effectcraft / "crates/ui-egui/Cargo.toml",
        builder / "lib/build-common.sh",
        builder / "templates/android/SafActivity.java",
        builder / "templates/android/saf_bridge.rs",
        builder / "vendor/rfd/src/artcraft_saf.rs",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Account photo picker patch is missing required upstream files:\n" + "\n".join(missing))

    patch_cargo(effectcraft)
    patch_rfd(builder / "vendor/rfd")
    patch_saf_bridge(builder)
    patch_java(builder)
    patch_build_common(builder)
    patch_account_source(effectcraft)
    print("Added Android system Photo Picker (image/*) for account registration and profile avatars.")
    print("Picked photos are resized to 256px JPEG and embedded as bounded data URIs for P2P upload.")
    print("No broad storage permission is needed; existing HTTP(S) avatar URLs remain compatible.")


if __name__ == "__main__":
    main()
