#!/usr/bin/env python3
"""Route QQ-received plug-in files to Ae and open the plug-in picker in QQ's receive folder."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_QQ_PLUGIN_IMPORT_V1"


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_migration_module(effectcraft: Path) -> None:
    lib = effectcraft / "crates/ui-egui/src/lib.rs"
    source = lib.read_text(encoding="utf-8")
    old = '#[cfg(not(target_arch = "wasm32"))]\nmod plugin_migration;\n'
    new = '#[cfg(not(target_arch = "wasm32"))]\npub mod plugin_migration;\n'
    if new not in source:
        source = once(source, old, new, "public desktop plug-in archive probe")
        lib.write_text(source, encoding="utf-8")

    module = effectcraft / "crates/ui-egui/src/plugin_migration.rs"
    source = module.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_QQ_PLUGIN_ARCHIVE_PROBE_V1"
    if marker not in source:
        anchor = "/// Called when the existing effect.plugins.load picker returns a ZIP."
        helper = r'''
/// EFFECTCRAFT_ANDROID_QQ_PLUGIN_ARCHIVE_PROBE_V1
/// Decide whether a ZIP handed to Ae by QQ is a plug-in package or a project archive.
/// Only recognizable plug-in payload extensions are considered; ordinary project ZIPs
/// therefore keep following the existing project importer.
pub fn looks_like_plugin_archive(path: &str) -> bool {
    let Ok(file) = File::open(path) else { return false };
    let Ok(mut archive) = ZipArchive::new(file) else { return false };
    const PLUGIN_EXTENSIONS: &[&str] = &[
        "wasm", "wat", "jsx", "js", "aex", "dll", "ofx", "so",
        "dylib", "plugin", "bundle", "prm", "8bf",
    ];
    for index in 0..archive.len() {
        let Ok(entry) = archive.by_index(index) else { continue };
        if entry.is_dir() { continue; }
        let Ok(name) = entry.name() else { continue };
        let extension = Path::new(name)
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        if PLUGIN_EXTENSIONS.contains(&extension.as_str()) {
            return true;
        }
    }
    false
}

'''
        source = once(source, anchor, helper + anchor, "QQ plug-in ZIP detector")
        module.write_text(source, encoding="utf-8")


def patch_saf_bridge(builder: Path) -> None:
    path = builder / "templates/android/saf_bridge.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    request_anchor = "        pub fn request_save(&self, id: u64, name: &str) -> Result<(), String> {\n"
    request = r'''        /// Open the system picker in QQ's ordinary shared receive directory first.
        pub fn request_plugin_open(&self, id: u64) -> Result<(), String> {
            self.vm
                .attach_current_thread(|env| -> jni::errors::Result<()> {
                    let activity_raw = self.app.activity_as_ptr() as jni::sys::jobject;
                    let activity = unsafe { env.as_cast_raw::<JObject>(&activity_raw)? };
                    env.call_method(
                        &*activity,
                        jni_str!("safRequestPluginOpen"),
                        jni_sig!("(J)V"),
                        &[JValue::Long(id as i64)],
                    )?;
                    Ok(())
                })
                .map_err(|error| error.to_string())
        }

'''
    source = once(source, request_anchor, request + request_anchor, "QQ plug-in SAF request bridge")

    worker_anchor = "        fn wait_answer_worker(&self, id: u64, timeout: Duration) -> Result<PickAnswer, String> {\n"
    worker = r'''        /// Worker-thread picker used only by plug-in import. It starts in QQ's receive folder
        /// when that public folder exists, then falls back to shared Download/Documents.
        pub fn pick_plugin_open_blocking_worker(&self, id: u64, timeout: Duration) -> Result<PickAnswer, String> {
            self.request_plugin_open(id)?;
            self.wait_answer_worker(id, timeout)
        }

'''
    source = once(source, worker_anchor, worker + worker_anchor, "QQ plug-in worker picker")
    source = source.replace("// ARTCRAFT_ANDROID_SAF_BRIDGE_V3", "// ARTCRAFT_ANDROID_SAF_BRIDGE_V3\n// " + MARKER, 1)
    path.write_text(source, encoding="utf-8")


def patch_saf_activity(builder: Path) -> None:
    path = builder / "templates/android/SafActivity.java"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    anchor = "    private void launchSafOpenPicker(long id, boolean multiple) {\n"
    methods = r'''    // EFFECTCRAFT_ANDROID_QQ_PLUGIN_IMPORT_V1
    /**
     * The dedicated plug-in picker starts in QQ's usual shared receive folder when it exists.
     * Files stored inside QQ's private Android/data area cannot be browsed by other apps; for
     * those, use QQ's Share / Open with Ae action, which delivers a granted content:// URI.
     */
    public void safRequestPluginOpen(long id) {
        requestAllFilesAccessThen(() -> launchSafPluginOpenPicker(id));
    }

    private Uri preferredPluginReceiveFolderUri() {
        try {
            File root = Environment.getExternalStorageDirectory().getCanonicalFile();
            String[] candidates = {
                "Tencent/QQfile_recv",
                "QQfile_recv",
                "Download/QQfile_recv",
                "Download/QQ",
                "Download",
                "Documents"
            };
            for (String relative : candidates) {
                File folder = new File(root, relative).getCanonicalFile();
                String prefix = root.getPath() + File.separator;
                if (!folder.getPath().startsWith(prefix) || !folder.isDirectory()) continue;
                String documentId = "primary:" + relative.replace(File.separatorChar, '/');
                return DocumentsContract.buildDocumentUri(
                    "com.android.externalstorage.documents", documentId);
            }
        } catch (Exception error) {
            Log.i(TAG, "Could not resolve QQ's shared receive folder; using Download.", error);
        }
        return DocumentsContract.buildDocumentUri(
            "com.android.externalstorage.documents", "primary:Download");
    }

    private void launchSafPluginOpenPicker(long id) {
        try {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("*/*");
            intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI, preferredPluginReceiveFolderUri());
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
            requestIds.put(REQ_OPEN, id);
            startActivityForResult(intent, REQ_OPEN);
        } catch (Exception error) {
            enqueueError(id, "open", "无法打开 QQ 插件接收目录，请从 QQ 使用“分享/其他应用打开 → Ae”："
                + error.toString());
        }
    }

'''
    source = once(source, anchor, methods + anchor, "QQ receive-folder Android picker")
    path.write_text(source, encoding="utf-8")


def patch_android_shell(builder: Path) -> None:
    path = builder / "lib/build-common.sh"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_QQ_PLUGIN_IMPORT_V1"
    if marker in source:
        return

    fn_anchor = "fn saf_dialog_async(bridge: saf::Bridge, state: Arc<SafState>, dialog: effectcraft_ui_egui::FileDialog, done: effectcraft_ui_egui::DialogDone) {\n"
    helper = r'''/// Open the Android system picker at QQ's shared receive folder for plug-in file types.
fn saf_open_plugin_paths(bridge: &saf::Bridge, state: &SafState) -> Vec<String> {
    let id = saf_next_id(state);
    match bridge.pick_plugin_open_blocking_worker(id, saf::PICK_TIMEOUT) {
        Ok(saf::PickAnswer::Paths(paths)) => paths,
        Ok(saf::PickAnswer::Cancelled) => Vec::new(),
        Err(error) => {
            log::error!("Android QQ plug-in picker: {error}");
            Vec::new()
        }
    }
}

'''
    source = once(source, fn_anchor, helper + fn_anchor, "QQ-aware plug-in picker helper")

    old = '''    std::thread::spawn(move || {
        use effectcraft_ui_egui::FileDialog;
        let paths = match dialog {'''
    new = r'''    std::thread::spawn(move || {
        use effectcraft_ui_egui::FileDialog;
        let is_plugin_dialog = matches!(
            &dialog,
            FileDialog::Open { exts, many: false }
                if exts.iter().any(|extension| matches!(
                    extension.as_str(),
                    "wasm" | "wat" | "zip" | "aex" | "dll" | "ofx" | "so"
                    | "dylib" | "plugin" | "bundle" | "prm" | "8bf" | "jsx" | "js"
                ))
        );
        let paths = if is_plugin_dialog {
            saf_open_plugin_paths(&bridge, &state)
        } else {
            match dialog {'''
    source = once(source, old, new, "plug-in-specific QQ picker dispatch")

    old_tail = '''            FileDialog::Save { default, .. } => saf_save_path(&bridge, &state, &default).into_iter().collect(),
        };
        done(paths);
    });'''
    new_tail = '''            FileDialog::Save { default, .. } => saf_save_path(&bridge, &state, &default).into_iter().collect(),
            }
        };
        done(paths);
    });'''
    source = once(source, old_tail, new_tail, "plug-in-aware dialog dispatch close")
    source = source.replace("fn saf_dialog_async(", "// " + marker + "\nfn saf_dialog_async(", 1)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to the checked-out source trees")

    patch_migration_module(effectcraft)
    patch_saf_bridge(builder)
    patch_saf_activity(builder)
    patch_android_shell(builder)
    print("QQ plug-in handoff and QQfile_recv-first Android picker are installed.")
    print("Project imports keep their existing Download picker and incoming project routing.")
    print("QQ-private Android/data files remain supported through QQ's Share/Open-with content URI grant.")


if __name__ == "__main__":
    main()
