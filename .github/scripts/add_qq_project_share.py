#!/usr/bin/env python3
"""Add full-project ZIP sharing through Android's Sharesheet (QQ is a selectable target)."""
from __future__ import annotations

import os
import re
from pathlib import Path


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_manifest_generator(builder: Path) -> None:
    path = builder / "lib/android_project.py"
    source = path.read_text(encoding="utf-8")
    # EFFECTCRAFT_OPEN_SHARED_PROJECT_INTENT_V1: register Ae for all supported incoming project formats.
    # SafActivity already stages ACTION_VIEW URIs and routes them to the normal import inbox.
    intent_anchor = '    activities = _as_list(application.get("activity")) or [{}]\n    for activity in activities:\n'
    intent_code = r'''    activities = _as_list(application.get("activity")) or [{}]
    if android_meta.get("package") == "com.artcraft.effectcraft":
        project_extensions = (
            "aep", "aepx", "ecproj", "ecprojx", "zip", "xml", "alight", "amproj",
            "nv", "json", "fcpxml", "otio", "edl", "aaf", "omf", "lottie", "rar",
        )
        for activity in activities:
            filters = activity.setdefault("intent_filter", [])
            for extension in project_extensions:
                for scheme in ("content", "file"):
                    marker_filter = f"EFFECTCRAFT_OPEN_PROJECT_{extension}_{scheme}"
                    if any(item.get("_effectcraft_marker") == marker_filter for item in filters):
                        continue
                    filters.append({
                        "_effectcraft_marker": marker_filter,
                        "actions": ["android.intent.action.VIEW"],
                        "categories": [
                            "android.intent.category.DEFAULT",
                            "android.intent.category.BROWSABLE",
                        ],
                        "data": [{
                            "scheme": scheme,
                            "host": "*",
                            "mime_type": "*/*",
                            "path_pattern": r".*\." + extension,
                        }],
                    })
            send_marker = "EFFECTCRAFT_SEND_PROJECT_MIME_TYPES"
            if not any(item.get("_effectcraft_marker") == send_marker for item in filters):
                filters.append({
                    "_effectcraft_marker": send_marker,
                    "actions": ["android.intent.action.SEND"],
                    "categories": ["android.intent.category.DEFAULT"],
                    "data": [
                        {"mime_type": "application/zip"},
                        {"mime_type": "application/x-zip-compressed"},
                        {"mime_type": "application/vnd.rar"},
                        {"mime_type": "application/x-rar-compressed"},
                        {"mime_type": "application/x-rar"},
                        {"mime_type": "application/octet-stream"},
                        {"mime_type": "application/json"},
                        {"mime_type": "application/xml"},
                        {"mime_type": "text/xml"},
                    ],
                })
    for activity in activities:
'''
    if "EFFECTCRAFT_OPEN_PROJECT_" not in source:
        source = once(source, intent_anchor, intent_code, "incoming project format intent filters")
    marker = "EFFECTCRAFT_SHARE_FILEPROVIDER_V1"
    if marker not in source:
        anchor = '    lines.append("    </application>")\n'
        provider = '''    # EFFECTCRAFT_SHARE_FILEPROVIDER_V1: grant QQ and other share targets read access to a ZIP.
    if android_meta.get("package") == "com.artcraft.effectcraft":
        lines.append('        <provider android:name="androidx.core.content.FileProvider"')
        lines.append('            android:authorities="' + "$" + '{applicationId}.effectcraft.files"')
        lines.append('            android:exported="false" android:grantUriPermissions="true">')
        lines.append('            <meta-data android:name="android.support.FILE_PROVIDER_PATHS"')
        lines.append('                android:resource="@xml/effectcraft_file_paths" />')
        lines.append('        </provider>')
'''
        source = once(source, anchor, provider + anchor, "FileProvider manifest registration")
    resource_anchor = '    (android_dir / "AndroidManifest.xml").write_text(manifest_xml(android_meta))\n'
    resource_marker = "EFFECTCRAFT_SHARE_FILEPROVIDER_RESOURCE_V1"
    resource_code = '''    # EFFECTCRAFT_SHARE_FILEPROVIDER_RESOURCE_V1
    if android_meta.get("package") == "com.artcraft.effectcraft":
        share_paths = android_dir / "res" / "xml" / "effectcraft_file_paths.xml"
        share_paths.parent.mkdir(parents=True, exist_ok=True)
        share_paths.write_text("""<?xml version="1.0" encoding="utf-8"?>
<paths xmlns:android="http://schemas.android.com/apk/res/android">
    <external-files-path name="effectcraft_shared_external" path="." />
    <files-path name="effectcraft_shared_internal" path="." />
</paths>
""")
'''
    if resource_marker not in source:
        source = once(source, resource_anchor, resource_anchor + "\n" + resource_code, "FileProvider XML resource generation")
    path.write_text(source, encoding="utf-8")


def patch_activity(builder: Path) -> None:
    path = builder / "templates/android/SafActivity.java"
    source = path.read_text(encoding="utf-8")
    imports = [
        "import androidx.core.content.FileProvider;",
        "import android.widget.Toast;",
        "import java.io.BufferedInputStream;",
        "import java.io.BufferedOutputStream;",
        "import java.io.IOException;",
        "import java.util.zip.ZipEntry;",
        "import java.util.zip.ZipOutputStream;",
    ]
    anchor = "import android.content.Context;\n"
    if "import androidx.core.content.FileProvider;" not in source:
        source = once(source, anchor, anchor + "\n".join(imports) + "\n", "FileProvider and ZIP imports")

    marker = "EFFECTCRAFT_ANDROID_QQ_PROJECT_SHARE_V1"
    if marker not in source:
        anchor = '''    public static String pollGalleryPublish(String requestId) {
        return requestId == null ? null : galleryPublishResults.remove(requestId);
    }
'''
        bridge = r'''
    // EFFECTCRAFT_ANDROID_QQ_PROJECT_SHARE_V1
    /**
     * ZIP the folder created by File > Dependencies > Collect Files. The ZIP contains the
     * .ecproj file and its (Footage) directory, then Android grants the chosen target read access.
     */
    public static void shareProjectPackage(String projectPath) {
        __CLASS__ activity = galleryActivity;
        if (activity == null) {
            throw new IllegalStateException("Ae 尚未准备好工程分享界面，请返回应用后重试。");
        }
        if (projectPath == null || projectPath.trim().isEmpty()) {
            throw new IllegalArgumentException("没有取得已收集工程的文件路径。");
        }
        activity.io.execute(() -> {
            try {
                File projectFile = new File(projectPath).getCanonicalFile();
                if (!projectFile.isFile() || !projectFile.getName().toLowerCase(java.util.Locale.ROOT).endsWith(".ecproj")) {
                    throw new IOException("没有找到完整导出的 .ecproj 工程文件。");
                }
                File root = projectFile.getParentFile();
                if (root == null || !root.isDirectory()) throw new IOException("工程素材文件夹不存在。");

                File storage = activity.getExternalFilesDir(null);
                if (storage == null) storage = activity.getFilesDir();
                File shareDirectory = new File(storage, "EffectCraftShare");
                if (!shareDirectory.isDirectory() && !shareDirectory.mkdirs()) {
                    throw new IOException("无法创建工程分享暂存目录。");
                }
                File archive = new File(shareDirectory,
                    root.getName().replaceAll("[^A-Za-z0-9_-]", "_") + "-" + System.currentTimeMillis() + ".zip");
                zipProjectDirectory(root, root, archive);
                if (!archive.isFile() || archive.length() <= 22) {
                    throw new IOException("工程 ZIP 打包结果为空或不完整。");
                }

                Uri uri = FileProvider.getUriForFile(
                    activity, activity.getPackageName() + ".effectcraft.files", archive);
                Intent send = new Intent(Intent.ACTION_SEND);
                send.setType("application/zip");
                send.putExtra(Intent.EXTRA_STREAM, uri);
                send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                send.setClipData(ClipData.newUri(activity.getContentResolver(), archive.getName(), uri));
                Intent chooser = Intent.createChooser(send, "选择 QQ 发送工程 ZIP");
                chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                activity.runOnUiThread(() -> {
                    try {
                        activity.startActivity(chooser);
                        Toast.makeText(activity, "工程包已准备好，请选择 QQ 发送。", Toast.LENGTH_LONG).show();
                    } catch (Exception error) {
                        Log.e(TAG, "Could not open the Android project share sheet.", error);
                        Toast.makeText(activity, "无法打开分享面板：" + error.getMessage(), Toast.LENGTH_LONG).show();
                    }
                });
            } catch (Exception error) {
                Log.e(TAG, "Could not package the EffectCraft project for QQ.", error);
                final String detail = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
                activity.runOnUiThread(() ->
                    Toast.makeText(activity, "工程分享失败：" + detail, Toast.LENGTH_LONG).show());
            }
        });
    }

    private static void zipProjectDirectory(File root, File current, File archive) throws IOException {
        String rootPath = root.getCanonicalPath();
        try (ZipOutputStream output = new ZipOutputStream(
                new BufferedOutputStream(new FileOutputStream(archive)))) {
            addProjectFiles(rootPath, current, output);
        } catch (IOException error) {
            // Never leave a partial ZIP that could be mistaken for a valid project attachment.
            // The archive is private to this app and is removed on failure.
            try { archive.delete(); } catch (Exception ignored) {}
            throw error;
        }
    }

    private static void addProjectFiles(String rootPath, File directory, ZipOutputStream output) throws IOException {
        File[] children = directory.listFiles();
        if (children == null) throw new IOException("无法读取工程素材目录：" + directory.getName());
        for (File child : children) {
            String canonical = child.getCanonicalPath();
            if (!canonical.equals(rootPath) && !canonical.startsWith(rootPath + File.separator)) {
                // Ignore symlinks that escape the collected-project folder.
                continue;
            }
            if (child.isDirectory()) {
                addProjectFiles(rootPath, child, output);
            } else if (child.isFile()) {
                String relative = canonical.substring(rootPath.length())
                    .replace(File.separatorChar, '/');
                while (relative.startsWith("/")) relative = relative.substring(1);
                if (relative.isEmpty()) continue;
                output.putNextEntry(new ZipEntry(relative));
                try (InputStream input = new BufferedInputStream(new FileInputStream(child))) {
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                }
                output.closeEntry();
            }

        

        }
    }
    // EFFECTCRAFT_ANDROID_QQ_PROJECT_FILE_SHARE_V1
    /** Stage one exported project file in the app-owned FileProvider directory and share it. */
    public static void shareProjectFile(String exportedPath) {
        __CLASS__ activity = galleryActivity;
        if (activity == null) {
            throw new IllegalStateException("Ae 尚未准备好工程分享界面，请返回应用后重试。");
        }
        if (exportedPath == null || exportedPath.trim().isEmpty()) {
            throw new IllegalArgumentException("没有取得已导出工程文件的路径。");
        }
        activity.io.execute(() -> {
            File staged = null;
            try {
                Uri sourceUri = (exportedPath.startsWith("content://") || exportedPath.startsWith("file://"))
                    ? Uri.parse(exportedPath) : null;
                String sourceName = sourceUri != null ? sourceUri.getLastPathSegment()
                    : new File(exportedPath).getName();
                if (sourceName == null || sourceName.trim().isEmpty()) sourceName = "EffectCraft-Project.bin";
                sourceName = new File(sourceName).getName();
                StringBuilder safeName = new StringBuilder();
                for (int i = 0; i < sourceName.length(); i++) {
                    char ch = sourceName.charAt(i);
                    safeName.append((ch == '/' || ch == '\\' || ch == 0) ? '_' : ch);
                }

                File storage = activity.getExternalFilesDir(null);
                if (storage == null) storage = activity.getFilesDir();
                File shareDirectory = new File(storage, "EffectCraftShare");
                if (!shareDirectory.isDirectory() && !shareDirectory.mkdirs()) {
                    throw new IOException("无法创建工程分享暂存目录。");
                }
                staged = new File(shareDirectory, System.currentTimeMillis() + "-" + safeName.toString());
                InputStream raw = sourceUri != null
                    ? activity.getContentResolver().openInputStream(sourceUri)
                    : new FileInputStream(new File(exportedPath));
                if (raw == null) throw new IOException("无法读取导出的工程文件。");
                try (InputStream input = new BufferedInputStream(raw);
                     java.io.OutputStream output = new BufferedOutputStream(new FileOutputStream(staged))) {
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                }
                if (!staged.isFile() || staged.length() <= 0) {
                    throw new IOException("导出的工程文件为空，不能分享。");
                }

                String lower = staged.getName().toLowerCase(java.util.Locale.ROOT);
                String mime = lower.endsWith(".zip") || lower.endsWith(".amproj") ? "application/zip"
                    : lower.endsWith(".xml") || lower.endsWith(".alight") ? "application/xml"
                    : lower.endsWith(".json") ? "application/json" : "application/octet-stream";
                Uri uri = FileProvider.getUriForFile(
                    activity, activity.getPackageName() + ".effectcraft.files", staged);
                Intent send = new Intent(Intent.ACTION_SEND);
                send.setType(mime);
                send.putExtra(Intent.EXTRA_STREAM, uri);
                send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                send.setClipData(ClipData.newUri(activity.getContentResolver(), staged.getName(), uri));
                Intent chooser = Intent.createChooser(send, "分享工程文件（可选择 QQ）");
                chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                activity.runOnUiThread(() -> {
                    try {
                        activity.startActivity(chooser);
                        Toast.makeText(activity, "工程文件已准备，请选择 QQ 或其他应用。", Toast.LENGTH_LONG).show();
                    } catch (Exception error) {
                        Log.e(TAG, "Could not open the project-file share sheet.", error);
                        Toast.makeText(activity, "无法打开分享面板：" + error.getMessage(), Toast.LENGTH_LONG).show();
                    }
                });
            } catch (Exception error) {
                if (staged != null) try { staged.delete(); } catch (Exception ignored) {}
                Log.e(TAG, "Could not stage the exported project for sharing.", error);
                final String detail = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
                activity.runOnUiThread(() ->
                    Toast.makeText(activity, "工程分享失败：" + detail, Toast.LENGTH_LONG).show());
            }
        });
    }
'''
        source = once(source, anchor, anchor + bridge, "Android QQ project share implementation")
    path.write_text(source, encoding="utf-8")


def patch_rust_bridge(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/android_gallery.rs"
    source = path.read_text(encoding="utf-8")
    marker = "pub(crate) fn share_project_package"
    if marker in source:
        return
    anchor = '''#[cfg(not(target_os = "android"))]
pub(crate) fn poll_publish(_request_id: &str) -> Result<Option<String>, String> {
    Ok(Some("ERROR: 当前平台不支持 Android 相册发布。".into()))
}
'''
    addition = r'''
#[cfg(target_os = "android")]
pub(crate) fn share_project_package(project_path: &str) -> Result<(), String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let path = jni::objects::JObject::from(env.new_string(project_path)?);
            env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("shareProjectPackage"),
                jni::jni_sig!("(Ljava/lang/String;)V"),
                &[jni::objects::JValue::Object(&path)],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub(crate) fn share_project_package(_project_path: &str) -> Result<(), String> {
    Err("工程分享到 QQ 需要使用 Android 版 EffectCraft。".into())
}
'''
    path.write_text(once(source, anchor, anchor + addition, "Rust JNI QQ share bridge"), encoding="utf-8")


def patch_frontend(effectcraft: Path) -> None:
    """Share only after the asynchronous Collect Files folder picker has completed."""
    path = effectcraft / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_SHARE_COLLECTED_PROJECT_V1"
    if marker in source:
        return
    old = """    let r = app.session.execute(id, Value::Object(p)).map_err(|e| e.to_string());
    if let Err(e) = &r {
        app.ui.status = e.clone();
    }
    r
}"""
    new = """    // EFFECTCRAFT_ANDROID_SHARE_COLLECTED_PROJECT_V1
    // The caller requests sharing by setting shareAfterCollect. Remove that UI-only flag
    // before sending parameters to the engine, then wait until the folder picker has returned
    // and file.collectFiles has actually copied the .ecproj and all footage.
    let share_after_collect = id == "file.collectFiles"
        && params.get("shareAfterCollect").and_then(Value::as_bool) == Some(true);
    p.remove("shareAfterCollect");
    let r = app.session.execute(id, Value::Object(p)).map_err(|e| e.to_string());
    if let Err(e) = &r {
        app.ui.status = e.clone();
    } else if share_after_collect {
        match &r {
            Ok(result) => {
                let collection_errors = result.get("errors").and_then(Value::as_array);
                if collection_errors.is_some_and(|errors| !errors.is_empty()) {
                    app.ui.status = "部分素材未能收集，已取消工程分享；请检查素材文件后重试。".into();
                } else if let Some(project_path) = result.get("project").and_then(Value::as_str) {
                    if let Err(error) = crate::android_gallery::share_project_package(project_path) {
                        app.ui.status = format!("工程分享失败：{error}");
                    } else {
                        app.ui.status = "完整工程包已准备，请在系统分享面板选择 QQ 或其他应用。".into();
                    }
                } else {
                    app.ui.status = "工程已收集，但没有取得工程文件路径，无法分享。".into();
                }
            }
            Err(_) => {}
        }
    }
    r
}"""
    if source.count(old) != 1:
        raise SystemExit(f"Collected-project sharing hook: expected one run_with_picked tail, found {source.count(old)}")
    source = source.replace(old, new, 1)
    if marker not in source:
        raise SystemExit("Collected-project sharing hook was not installed")
    path.write_text(source, encoding="utf-8")


def patch_file_associations(builder: Path) -> None:
    path = builder / "lib" / "file_associations.py"
    source = path.read_text(encoding="utf-8")
    rar_mimes = '''EXT_MIME = {
    # Ae accepts project bundles shared from QQ and Android file managers.
    "zip": ("application/zip", "application/x-zip-compressed"),
    "rar": ("application/vnd.rar", "application/x-rar-compressed", "application/x-rar"),
'''
    if '"rar": ("application/vnd.rar"' not in source:
        source = once(source, "EXT_MIME = {", rar_mimes, "ZIP/RAR MIME associations")
    # Preserve every existing Ae-associated extension and append the supported project types.
    association = re.search(r'(?ms)^(\s*"effectcraft"\s*:\s*)\[(.*?)\](\s*,)', source)
    if association is None:
        raise SystemExit("Could not find the Ae file-association list in lib/file_associations.py")
    extensions = re.findall(r'"([^"]+)"', association.group(2))
    for extension in (
        "ecproj", "ecprojx", "ectemplate",
        "aep", "aepx", "alight", "amproj", "xml", "nv", "json", "zip", "rar",
        "lottie", "fcpxml", "otio", "edl", "aaf", "omf",
    ):
        if extension not in extensions:
            extensions.append(extension)
    replacement = association.group(1) + "[" + ", ".join(f'"{extension}"' for extension in extensions) + "]" + association.group(3)
    source = source[:association.start()] + replacement + source[association.end():]
    path.write_text(source, encoding="utf-8")


def patch_rar_dependency(effectcraft: Path) -> None:
    path = effectcraft / "crates" / "engine" / "Cargo.toml"
    source = path.read_text(encoding="utf-8")
    dependency = 'rars = { version = "0.12.3", default-features = false }'
    if dependency not in source:
        anchor = "effectcraft-sam2 = { workspace = true }"
        source = once(source, anchor, anchor + "\n" + dependency, "RAR reader dependency")
        path.write_text(source, encoding="utf-8")


def patch_incoming_project_dispatch(builder: Path, effectcraft: Path) -> None:
    # Resolve every external project path to its existing importer. Keep this inside the UI
    # crate so desktop-AE imports still pass through the normal loss-review dialog.
    frontend = effectcraft / "crates/ui-egui/src/menus/frontend.rs"
    source = frontend.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_AUTO_IMPORT_EXTERNAL_PROJECT_V1"
    if marker not in source:
        anchor = "/// View ▸ Zoom In / Zoom Out: the next standard magnification (as a share of screen pixels, so\n"
        code = """// EFFECTCRAFT_ANDROID_AUTO_IMPORT_EXTERNAL_PROJECT_V1
/// Open an incoming Android share using the same preflight/dialog path as File > Import.
pub(super) fn run_incoming_project(app: &mut EffectcraftApp, command: &str, path: &str) -> Result<(), String> {
    run_with_picked(app, command, "path", &json!({}), Value::String(path.to_owned())).map(|_| ())
}

"""
        source = once(source, anchor, code + anchor, "incoming project importer bridge")
        frontend.write_text(source, encoding="utf-8")

    # Add the ZIP/RAR picker beside the original native project picker. This runs
    # before later scripts split mobile AE / EffectCraft imports, so do not depend on
    # the later file.importEffectCraftMobile mapping already existing.
    archive_picker = '"file.extractProjectArchive" => ("path", Ask::Open(&["zip", "rar"]))'
    if archive_picker not in source:
        base_picker = re.compile(
            r'(?m)^(?P<indent>[ \t]*)"file\.importProject"\s*=>\s*\("path",\s*Ask::Open\(&\[[^\]]*\]\)\),\s*$'
        )
        match = base_picker.search(source)
        if match is None:
            raise SystemExit("Could not locate the original file.importProject picker for ZIP/RAR registration.")
        line_end = source.find("\n", match.end())
        if line_end < 0:
            line_end = len(source)
        insertion = match.group("indent") + "        " + archive_picker + ",\n"
        source = source[:line_end + 1] + insertion + source[line_end + 1:]

    run_anchor = '    p.insert(key.to_string(), v);\n    // Picked files import in the background, with the Importing card showing progress (#270).'
    run_new = '''    p.insert(key.to_string(), v);
    if id == "file.extractProjectArchive" {
        let extracted = app.session.execute(id, Value::Object(p)).map_err(|error| error.to_string())?;
        let inner = extracted.get("path").and_then(Value::as_str)
            .ok_or_else(|| "压缩包已解压，但没有识别到工程文件".to_string())?.to_owned();
        super::import_incoming_project(app, &inner)?;
        return Ok(extracted);
    }
    // Picked files import in the background, with the Importing card showing progress (#270).'''
    if 'if id == "file.extractProjectArchive"' not in source:
        source = once(source, run_anchor, run_new, "automatic import after archive picker")
    frontend.write_text(source, encoding="utf-8")

    menus = effectcraft / "crates/ui-egui/src/menus.rs"
    source = menus.read_text(encoding="utf-8")
    if marker not in source:
        anchor = "pub struct UiCommand {\n"
        code = r"""// EFFECTCRAFT_ANDROID_AUTO_IMPORT_EXTERNAL_PROJECT_V1
/// Route a file received from QQ / Android Sharesheet to its existing project importer.
pub fn import_incoming_project(app: &mut EffectcraftApp, path: &str) -> Result<(), String> {
    let extension = std::path::Path::new(path)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();

    let command = match extension.as_str() {
        "aep" | "aepx" => "file.importAepDesktop",
        "ecproj" | "ecprojx" => "file.importEffectCraftMobile",
        // Extract project bundles first, then dispatch the actual contained project format.
        "zip" | "rar" => {
            let extracted = app.session.execute(
                "file.extractProjectArchive",
                json!({"path": path}),
            ).map_err(|error| error.to_string())?;
            let inner = extracted.get("path").and_then(Value::as_str)
                .ok_or_else(|| "压缩包已解压，但没有识别到工程文件".to_string())?
                .to_owned();
            return import_incoming_project(app, &inner);
        }
        "nv" => "file.importNodeVideoProject",
        "alight" => "file.importAlightMotionProject",
        "amproj" => "file.importAlightMotionProject",
        "xml" => {
            let bytes = std::fs::read(path).unwrap_or_default();
            let head = String::from_utf8_lossy(&bytes[..bytes.len().min(8192)]).to_ascii_lowercase();
            if head.contains("<scene") || head.contains("<alightmotion") || head.contains("alight motion") {
                "file.importAlightMotionProject"
            } else {
                "file.importTimeline"
            }
        }
        "fcpxml" | "otio" | "edl" | "aaf" | "omf" => "file.importTimeline",
        "lottie" => "file.importLottie",
        "json" => {
            let bytes = std::fs::read(path).unwrap_or_default();
            let value: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
            let lottie = value.get("layers").and_then(Value::as_array).is_some()
                && value.get("fr").is_some()
                && value.get("ip").is_some()
                && value.get("op").is_some();
            if lottie { "file.importLottie" } else { "file.importNodeVideoProject" }
        }
        _ => return Err(format!("Ae 暂不支持自动导入此工程格式：.{}", extension)),
    };

    frontend::run_incoming_project(app, command, path)
}

"""
        source = once(source, anchor, code + anchor, "public incoming-project format router")
        menus.write_text(source, encoding="utf-8")

    # The final File > Import menu is generated later by
    # add_five_project_import_buttons.py; it adds the archive command there.
    builder_file = builder / "lib" / "build-common.sh"
    shell = builder_file.read_text(encoding="utf-8")
    old_open = """    "effectcraft": '''        if let Err(error) = self.inner.session.execute("file.open", serde_json::json!({ "path": path })) {
            log::error!("Could not open the incoming file {path}: {error}");
        }
''',
"""
    new_open = """    "effectcraft": '''        if let Err(error) = effectcraft_ui_egui::menus::import_incoming_project(&mut self.inner, path) {
            log::error!("Could not automatically import the incoming project {path}: {error}");
        }
''',
"""
    if "effectcraft_ui_egui::menus::import_incoming_project(&mut self.inner, path)" not in shell:
        # Match the EffectCraft INTENT_OPEN entry by key and closing delimiter.
        pattern = re.compile(r"""(?ms)^    "effectcraft": '''.*?^''',\n(?=    "filmcraft":)""")
        shell, count = pattern.subn(lambda _match: new_open, shell, count=1)
        if count != 1:
            raise SystemExit("Could not locate the EffectCraft INTENT_OPEN entry in build-common.sh")
        builder_file.write_text(shell, encoding="utf-8")

    frontend_check = frontend.read_text(encoding="utf-8")
    menus_check = menus.read_text(encoding="utf-8")
    manifest_generator = (builder / "lib" / "android_project.py").read_text(encoding="utf-8")
    associations = (builder / "lib" / "file_associations.py").read_text(encoding="utf-8")
    if '"amproj"' not in manifest_generator or '"amproj"' not in associations:
        raise SystemExit("Alight Motion .amproj files are not registered for direct Android open.")
    if '"alight" => "file.importAlightMotionProject"' not in menus_check or '"amproj" => "file.importAlightMotionProject"' not in menus_check:
        raise SystemExit("Alight Motion .alight/.amproj incoming files are not routed to the AM importer.")
    if marker not in frontend_check or marker not in menus_check:
        raise SystemExit("The format-aware incoming-project router was not installed.")
    required = (
        "file.importAepDesktop", "file.importEffectCraftMobile",
        "file.importAlightMotionProject", "file.importNodeVideoProject",
        "file.importTimeline", "file.importLottie",
    )
    missing = [command for command in required if command not in menus_check]
    if missing:
        raise SystemExit("The incoming-project router is missing: " + ", ".join(missing))
    if "effectcraft_ui_egui::menus::import_incoming_project(&mut self.inner, path)" not in shell:
        raise SystemExit("The Android shell still bypasses the automatic project importer.")
    print("Registered automatic external project import routing for AE, EffectCraft, AM, NodeVideo, CapCut, Lottie and timeline formats.")


def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to the checked-out sources.")
    patch_manifest_generator(builder)
    patch_file_associations(builder)
    patch_rar_dependency(effectcraft)
    patch_activity(builder)
    patch_rust_bridge(effectcraft)
    patch_frontend(effectcraft)
    patch_incoming_project_dispatch(builder, effectcraft)

    manifest_generator = (builder / "lib/android_project.py").read_text(encoding="utf-8")
    if "EFFECTCRAFT_OPEN_PROJECT_" not in manifest_generator:
        raise SystemExit("Ae is not registered to receive supported project formats.")
    associations = (builder / "lib" / "file_associations.py").read_text(encoding="utf-8")
    if '"rar"' not in associations or "application/vnd.rar" not in associations:
        raise SystemExit("Ae is not registered for RAR project packages.")
    for action in ("android.intent.action.VIEW", "android.intent.action.SEND"):
        if action not in manifest_generator:
            raise SystemExit(f"Ae incoming project intent filter is missing {action}.")
    activity_source = (builder / "templates/android/SafActivity.java").read_text(encoding="utf-8")
    for token in ("handleIncomingFiles(getIntent())", "Intent.ACTION_VIEW", "intentPoll"):
        if token not in activity_source:
            raise SystemExit(f"Ae incoming file handoff is incomplete: {token}")
    # The QQ destination is now the system Sharesheet opened after Collect Files completes.
    # Do not add another standalone button to the export dialog.
    print("Added the Android full-project share bridge used by the unified Project Export selector.")
    print("The archive includes the .ecproj and collected footage; QQ and other targets receive a read-granted content URI.")
    print("All supported project extensions are registered with Android and routed into their existing Ae importers after staging.")


if __name__ == "__main__":
    main()
