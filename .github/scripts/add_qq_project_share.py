#!/usr/bin/env python3
"""Add project ZIP sharing through Android's Sharesheet; the user chooses any installed target."""
from __future__ import annotations

import os
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
    marker = "EFFECTCRAFT_SHARE_FILEPROVIDER_V1"
    if marker not in source:
        anchor = '    lines.append("    </application>")\n'
        provider = '''    # EFFECTCRAFT_SHARE_FILEPROVIDER_V1: grant Android share targets read access to a ZIP.
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
        "import java.io.BufferedInputStream;",
        "import java.io.BufferedOutputStream;",
        "import java.io.IOException;",
        "import java.util.zip.ZipEntry;",
        "import java.util.zip.ZipOutputStream;",
    ]
    anchor = "import android.content.Context;\n"
    if "import androidx.core.content.FileProvider;" not in source:
        source = once(source, anchor, anchor + "\n".join(imports) + "\n", "FileProvider and ZIP imports")

    marker = "EFFECTCRAFT_ANDROID_EXPORT_FILE_QQ_SHARE_V2"
    if marker not in source:
        anchor = '''    public static String pollGalleryPublish(String requestId) {
        return requestId == null ? null : galleryPublishResults.remove(requestId);
    }
'''
        bridge = r'''
    // EFFECTCRAFT_ANDROID_EXPORT_FILE_QQ_SHARE_V2
    /**
     * Share the exact project file the user most recently exported. Copy it into the
     * app-private FileProvider directory so QQ receives a stable content:// URI.
     */
    public static void shareExportedProject(String exportPath) {
        __CLASS__ activity = galleryActivity;
        if (activity == null || exportPath == null || exportPath.trim().isEmpty()) return;
        activity.io.execute(() -> {
            try {
                File source = new File(exportPath).getCanonicalFile();
                if (!source.isFile() || !source.canRead()) {
                    throw new IOException("找不到刚刚导出的工程文件：" + exportPath);
                }
                File storage = activity.getExternalFilesDir(null);
                if (storage == null) storage = activity.getFilesDir();
                File shareDirectory = new File(storage, "EffectCraftShare");
                if (!shareDirectory.isDirectory() && !shareDirectory.mkdirs()) {
                    throw new IOException("无法创建 QQ 分享暂存目录。");
                }

                String lower = source.getName().toLowerCase(java.util.Locale.ROOT);
                File sharePayload;
                String mime;
                if (lower.endsWith(".ecproj")) {
                    // A mobile EffectCraft export is a collected folder: the .ecproj plus
                    // (Footage) with every copied source image/video/audio/sequence. ZIP the
                    // whole directory so the receiver gets one self-contained import package.
                    File projectRoot = source.getParentFile();
                    if (projectRoot == null || !projectRoot.isDirectory()) {
                        throw new IOException("手机版完整工程素材目录不存在。");
                    }
                    String safeRoot = projectRoot.getName().replaceAll("[^A-Za-z0-9._-]", "_");
                    sharePayload = new File(shareDirectory,
                        "EffectCraft-Mobile-Project-" + safeRoot + "-" + System.currentTimeMillis() + ".zip");
                    zipProjectDirectory(projectRoot, sharePayload);
                    mime = "application/zip";
                } else {
                    String safeName = source.getName().replaceAll("[^A-Za-z0-9._-]", "_");
                    sharePayload = new File(shareDirectory,
                        System.currentTimeMillis() + "-" + safeName);
                    try (java.io.BufferedInputStream input =
                             new java.io.BufferedInputStream(new java.io.FileInputStream(source));
                         java.io.BufferedOutputStream output =
                             new java.io.BufferedOutputStream(new java.io.FileOutputStream(sharePayload))) {
                        byte[] buffer = new byte[64 * 1024];
                        int count;
                        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                    }
                    mime = lower.endsWith(".zip") ? "application/zip"
                        : lower.endsWith(".xml") ? "application/xml"
                        : "application/octet-stream";
                }

                Uri uri = FileProvider.getUriForFile(
                    activity, activity.getPackageName() + ".effectcraft.files", sharePayload);
                Intent send = new Intent(Intent.ACTION_SEND);
                send.setType(mime);
                send.putExtra(Intent.EXTRA_STREAM, uri);
                send.putExtra(Intent.EXTRA_SUBJECT, sharePayload.getName());
                send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                send.setClipData(ClipData.newUri(activity.getContentResolver(), sharePayload.getName(), uri));

                // Try QQ first. If it is absent or refuses the particular project format,
                // gracefully show Android's Sharesheet as a fallback.
                Intent qqSend = new Intent(send);
                qqSend.setPackage("com.tencent.mobileqq");
                Intent chooser = Intent.createChooser(send, "分享到QQ或其他应用");
                activity.runOnUiThread(() -> {
                    try {
                        activity.startActivity(qqSend);
                    } catch (Exception qqError) {
                        Log.w(TAG, "QQ is unavailable for this exported project; opening Android Sharesheet.", qqError);
                        try {
                            activity.startActivity(chooser);
                        } catch (Exception shareError) {
                            Log.e(TAG, "Could not open the exported-project share sheet.", shareError);
                        }
                    }
                });
            } catch (Exception error) {
                Log.e(TAG, "Could not package/share the exported EffectCraft project.", error);
                activity.runOnUiThread(() -> android.widget.Toast.makeText(
                    activity, "工程打包或分享失败：" + error.getMessage(), android.widget.Toast.LENGTH_LONG).show());
            }
        });
    }

    // Zip the collected project directory without following symlinks outside it.
    private static void zipProjectDirectory(File root, File archive) throws IOException {
        String rootPath = root.getCanonicalPath();
        try (ZipOutputStream output = new ZipOutputStream(
                new BufferedOutputStream(new FileOutputStream(archive)))) {
            addProjectFiles(rootPath, root, output);
        } catch (IOException error) {
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
                continue;
            }
            if (child.isDirectory()) {
                addProjectFiles(rootPath, child, output);
            } else if (child.isFile()) {
                String relative = canonical.substring(rootPath.length()).replace(File.separatorChar, '/');
                while (relative.startsWith("/")) relative = relative.substring(1);
                if (relative.isEmpty()) continue;
                output.putNextEntry(new ZipEntry(relative));
                try (java.io.BufferedInputStream input =
                         new java.io.BufferedInputStream(new java.io.FileInputStream(child))) {
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                }
                output.closeEntry();
            }
        }
    }
'''
        source = once(source, anchor, anchor + bridge, "Android project share-sheet implementation")
    path.write_text(source, encoding="utf-8")


def patch_rust_bridge(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/android_gallery.rs"
    source = path.read_text(encoding="utf-8")
    marker = "pub(crate) fn share_exported_project"
    if marker in source:
        return
    anchor = '''#[cfg(not(target_os = "android"))]
pub(crate) fn poll_publish(_request_id: &str) -> Result<Option<String>, String> {
    Ok(Some("ERROR: 当前平台不支持 Android 相册发布。".into()))
}
'''
    addition = r'''
#[cfg(target_os = "android")]
pub(crate) fn share_exported_project(project_path: &str) -> Result<(), String> {
    with_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let path = jni::objects::JObject::from(env.new_string(project_path)?);
            env.call_static_method(
                jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                jni::jni_str!("shareExportedProject"),
                jni::jni_sig!("(Ljava/lang/String;)V"),
                &[jni::objects::JValue::Object(&path)],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub(crate) fn share_exported_project(_project_path: &str) -> Result<(), String> {
    Err("工程分享到手机系统分享面板需要 Android 版 EffectCraft。".into())
}
'''
    path.write_text(once(source, anchor, anchor + addition, "Rust JNI Android exported-project QQ share bridge"), encoding="utf-8")


def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to the checked-out sources.")
    patch_manifest_generator(builder)
    patch_activity(builder)
    patch_rust_bridge(effectcraft)

    header = effectcraft / "crates/ui-egui/src/header.rs"
    source = header.read_text(encoding="utf-8")
    if 'ui.button("分享到QQ")' not in source or "share_exported_project(export_path)" not in source:
        raise SystemExit("The generic project share action must be installed before the Android share bridge.")
    path = builder / "templates/android/SafActivity.java"
    activity = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_EXPORT_FILE_QQ_SHARE_V2" not in activity:
        raise SystemExit("The Android project share-sheet implementation is missing.")
    if "zipProjectDirectory(projectRoot, sharePayload)" not in activity or "addProjectFiles(rootPath, child, output)" not in activity:
        raise SystemExit("The Android full mobile-project ZIP packager is missing.")
    print("Added direct sharing of exported project files through QQ.")
    print("For mobile .ecproj exports, the share bridge ZIPs the collected project and all (Footage) assets before sending.")


if __name__ == "__main__":
    main()
