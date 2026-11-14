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

    marker = "EFFECTCRAFT_ANDROID_PROJECT_SHARE_SHEET_V1"
    if marker not in source:
        anchor = '''    public static String pollGalleryPublish(String requestId) {
        return requestId == null ? null : galleryPublishResults.remove(requestId);
    }
'''
        bridge = r'''
    // EFFECTCRAFT_ANDROID_PROJECT_SHARE_SHEET_V1
    /**
     * ZIP the folder created by File > Dependencies > Collect Files. The ZIP contains the
     * .ecproj file and its (Footage) directory, then Android grants the chosen target read access.
     */
    public static void shareProjectPackage(String projectPath) {
        __CLASS__ activity = galleryActivity;
        if (activity == null || projectPath == null || projectPath.trim().isEmpty()) return;
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
                zipProjectDirectory(root, archive);

                Uri uri = FileProvider.getUriForFile(
                    activity, activity.getPackageName() + ".effectcraft.files", archive);
                Intent send = new Intent(Intent.ACTION_SEND);
                send.setType("application/zip");
                send.putExtra(Intent.EXTRA_STREAM, uri);
                send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                send.setClipData(ClipData.newUri(activity.getContentResolver(), archive.getName(), uri));
                Intent chooser = Intent.createChooser(send, "分享工程 ZIP");
                activity.runOnUiThread(() -> {
                    try {
                        activity.startActivity(chooser);
                    } catch (Exception error) {
                        Log.e(TAG, "Could not open the Android project share sheet.", error);
                    }
                });
            } catch (Exception error) {
                Log.e(TAG, "Could not package the EffectCraft project for sharing.", error);
            }
        });
    }

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
            if (!canonical.equals(rootPath) && !canonical.startsWith(rootPath + File.separator)) continue;
            if (child.isDirectory()) {
                addProjectFiles(rootPath, child, output);
            } else if (child.isFile()) {
                String relative = canonical.substring(rootPath.length()).replace(File.separatorChar, '/');
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
'''
        source = once(source, anchor, anchor + bridge, "Android project share-sheet implementation")
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
    Err("工程分享到手机系统分享面板需要 Android 版 EffectCraft。".into())
}
'''
    path.write_text(once(source, anchor, anchor + addition, "Rust JNI Android project share bridge"), encoding="utf-8")


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
    if 'ui.button("打包并分享工程")' not in source or "share_project_package(project_path)" not in source:
        raise SystemExit("The generic project share action must be installed before the Android share bridge.")
    path = builder / "templates/android/SafActivity.java"
    activity = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_PROJECT_SHARE_SHEET_V1" not in activity:
        raise SystemExit("The Android project share-sheet implementation is missing.")
    print("Added complete project ZIP packaging through Android's system Sharesheet.")
    print("Installed apps are offered as share targets; no QQ-only button or label is added.")


if __name__ == "__main__":
    main()
