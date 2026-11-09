#!/usr/bin/env python3
"""Prefer Android's shared-storage SAF picker and fall back safely for staged file reads."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_SHARED_STORAGE_SAF_FALLBACK_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_activity(builder: Path) -> None:
    path = builder / "templates/android/SafActivity.java"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Android shared-storage SAF fallback already configured.")
        return

    class_anchor = 'public final class __CLASS__ extends NativeActivity {\n'
    permission_fields = r'''
    // EFFECTCRAFT_ANDROID_PERMISSION_ON_IMPORT_V1
    private static final int REQ_IMPORT_STORAGE_PERMISSION = 0x504A;
    private Runnable pendingStorageContinuation;
    private boolean waitingForAllFilesAccessSettings = false;

    /**
     * Request "Allow management of all files" only when a file import is requested.
     * When the user returns from Settings, continue the exact import that opened it.
     * A refusal or unavailable Settings screen still falls through to the SAF picker.
     */
    public void requestAllFilesAccessThen(Runnable continuation) {
        if (continuation == null) return;
        runOnUiThread(() -> {
            if (hasOriginalStorageAccess()) {
                continuation.run();
                return;
            }
            if (pendingStorageContinuation != null) {
                Log.i(TAG, "A storage-permission request is already pending.");
                return;
            }
            pendingStorageContinuation = continuation;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                try {
                    Intent settings = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
                    settings.setData(Uri.parse("package:" + getPackageName()));
                    waitingForAllFilesAccessSettings = true;
                    startActivity(settings);
                } catch (Exception error) {
                    waitingForAllFilesAccessSettings = false;
                    Log.w(TAG, "All files access settings unavailable; continuing with SAF.", error);
                    finishPendingStorageContinuation();
                }
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                    && checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                try {
                    requestPermissions(new String[] {
                        Manifest.permission.READ_EXTERNAL_STORAGE,
                        Manifest.permission.WRITE_EXTERNAL_STORAGE
                    }, REQ_IMPORT_STORAGE_PERMISSION);
                } catch (Exception error) {
                    Log.w(TAG, "Legacy storage permission request failed; continuing with SAF.", error);
                    finishPendingStorageContinuation();
                }
            } else {
                finishPendingStorageContinuation();
            }
        });
    }

    private void finishPendingStorageContinuation() {
        Runnable continuation = pendingStorageContinuation;
        pendingStorageContinuation = null;
        if (continuation != null) continuation.run();
    }

'''
    source = replace_once(source, class_anchor, class_anchor + permission_fields,
                          "on-demand storage permission fields and helper")

    open_anchor = '''                intent.setType("*/*");
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);'''
    open_replacement = '''                intent.setType("*/*");
                // EFFECTCRAFT_ANDROID_SHARED_STORAGE_SAF_FALLBACK_V1
                // Open the ordinary shared Download folder first, not / or Android/data.
                // The user can still navigate to other shared-storage folders in DocumentsUI.
                intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                    DocumentsContract.buildDocumentUri(
                        "com.android.externalstorage.documents", "primary:Download"));
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);'''
    source = replace_once(source, open_anchor, open_replacement, "SAF open picker start folder")

    # Route every ordinary file-open request through the same permission-first mechanism.
    # This is the existing picker used by both plug-in import and project import.
    old_open_method = '''    public void safRequestOpen(long id, boolean multiple) {
        runOnUiThread(() -> {
            try {
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                // EFFECTCRAFT_ANDROID_SHARED_STORAGE_SAF_FALLBACK_V1
                // Open the ordinary shared Download folder first, not / or Android/data.
                // The user can still navigate to other shared-storage folders in DocumentsUI.
                intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                    DocumentsContract.buildDocumentUri(
                        "com.android.externalstorage.documents", "primary:Download"));
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
                requestIds.put(REQ_OPEN, id);
                startActivityForResult(intent, REQ_OPEN);
            } catch (Exception e) {
                enqueueError(id, "open", e.toString());
            }
        });
    }'''
    new_open_method = '''    public void safRequestOpen(long id, boolean multiple) {
        requestAllFilesAccessThen(() -> launchSafOpenPicker(id, multiple));
    }

    private void launchSafOpenPicker(long id, boolean multiple) {
        try {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("*/*");
            intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                DocumentsContract.buildDocumentUri(
                    "com.android.externalstorage.documents", "primary:Download"));
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
            requestIds.put(REQ_OPEN, id);
            startActivityForResult(intent, REQ_OPEN);
        } catch (Exception e) {
            enqueueError(id, "open", e.toString());
        }
    }'''
    source = replace_once(source, old_open_method, new_open_method,
                          "permission-first shared plug-in and project file picker")

    resume_old = '''    protected void onResume() {
        super.onResume();
        suppressSelectionHandles();
    }'''
    resume_new = '''    protected void onResume() {
        super.onResume();
        if (waitingForAllFilesAccessSettings) {
            waitingForAllFilesAccessSettings = false;
            // Continue whichever import asked for permission. Granted access uses the original
            // shared-storage path; a refusal uses SAF plus the app-owned staging fallback.
            finishPendingStorageContinuation();
        }
        suppressSelectionHandles();
    }'''
    source = replace_once(source, resume_old, resume_new, "resume import after all-files settings")

    permissions_result = '''    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_IMPORT_STORAGE_PERMISSION) {
            // SAF remains available even when the legacy runtime permission is declined.
            finishPendingStorageContinuation();
        }
    }

'''
    permissions_anchor = '    private void extractAssetsIfNeeded() {'
    source = replace_once(source, permissions_anchor, permissions_result + permissions_anchor,
                          "legacy storage permission callback")

    folder_anchor = '''                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
                requestIds.put(REQ_FOLDER, id);'''
    folder_replacement = '''                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
                // ACTION_OPEN_DOCUMENT_TREE cannot grant Download/root on Android 11+.
                // Start in the ordinary Documents folder, where directory grants are allowed.
                intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                    DocumentsContract.buildDocumentUri(
                        "com.android.externalstorage.documents", "primary:Documents"));
                requestIds.put(REQ_FOLDER, id);'''
    source = replace_once(source, folder_anchor, folder_replacement, "SAF folder picker start folder")

    old_stage = '        File dir = new File(appStorageDir(), "media");'
    new_stage = '        File dir = mediaStagingDirectory();'
    source = replace_once(source, old_stage, new_stage, "media staging directory selection")

    # Keep the Rust bridge's files_dir()/media convention aligned with whichever writable
    # directory was selected, including the public shared-storage fallback.
    old_files_dir = '    public String safFilesDir() { return appStorageDir().getAbsolutePath(); }'
    new_files_dir = '''    public String safFilesDir() {
        try {
            File media = mediaStagingDirectory();
            File parent = media.getParentFile();
            return (parent == null ? appStorageDir() : parent).getAbsolutePath();
        } catch (Exception error) {
            Log.w(TAG, "Falling back to app storage for SAF staging.", error);
            return appStorageDir().getAbsolutePath();
        }
    }'''
    source = replace_once(source, old_files_dir, new_files_dir, "SAF files directory bridge")

    stage_helper = r'''
    /**
     * Path-based EffectCraft readers need a local working copy after Android grants a content://
     * URI from DocumentsUI. The open path first tries an original primary shared-storage path
     * when All files access is granted; otherwise it stages through ContentResolver into
     * app-specific external storage, private files, or cache.
     */
    private File mediaStagingDirectory() throws Exception {
        List<File> candidates = new ArrayList<>();
        // Source files are read from the shared-storage URI returned by SAF. Keep the
        // engine's working copies in app-owned writable locations, not in public Download.
        File external = getExternalFilesDir(null);
        if (external != null) candidates.add(new File(external, "media"));
        candidates.add(new File(getFilesDir(), "media"));
        candidates.add(new File(getCacheDir(), "media"));

        for (File dir : candidates) {
            try {
                if ((!dir.isDirectory() && !dir.mkdirs()) || !dir.isDirectory()) continue;
                // canWrite() alone is not reliable on scoped-storage devices; verify with a
                // real create/delete operation before returning this directory to Rust.
                File probe = File.createTempFile(".effectcraft-storage-probe-", ".tmp", dir);
                if (probe.delete() || !probe.exists()) return dir;
            } catch (Exception error) {
                Log.i(TAG, "Storage staging path is not writable; trying next location: " + dir, error);
            }
        }
        throw new java.io.IOException("无法创建可写的导入暂存目录；请在系统文件选择器中从 Download 或 Documents 选择文件。");
    }

'''

    direct_path_helper = r''' 
    /** Use the original shared-storage path only when Android says broad path access is granted. */
    private boolean hasOriginalStorageAccess() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                return Environment.isExternalStorageManager();
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && !Environment.isExternalStorageLegacy()) {
                return false;
            }
            return Build.VERSION.SDK_INT < Build.VERSION_CODES.M
                || checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
        } catch (Throwable error) {
            Log.i(TAG, "Could not confirm original storage access; using SAF staging.", error);
            return false;
        }
    }

    /**
     * Resolve only primary shared-storage DocumentsProvider URIs to raw paths, and only after
     * the original broad permission has actually been granted. Every other provider/device
     * falls through to the ContentResolver copy path, so no guessed /data or root paths are used.
     */
    private String originalSharedStoragePath(Uri uri) {
        if (uri == null || !hasOriginalStorageAccess()) return null;
        if (!"com.android.externalstorage.documents".equals(uri.getAuthority())) return null;
        try {
            String documentId = DocumentsContract.getDocumentId(uri);
            if (documentId == null) return null;
            int colon = documentId.indexOf(':');
            if (colon <= 0 || !"primary".equalsIgnoreCase(documentId.substring(0, colon))) return null;
            String relative = documentId.substring(colon + 1);
            if (relative.isEmpty()) return null;
            File root = Environment.getExternalStorageDirectory().getCanonicalFile();
            File candidate = new File(root, relative).getCanonicalFile();
            String prefix = root.getPath() + File.separator;
            if (!candidate.getPath().startsWith(prefix)) return null;
            if (!candidate.isFile() || !candidate.canRead()) return null;
            return candidate.getAbsolutePath();
        } catch (Exception error) {
            Log.i(TAG, "Original shared-storage path unavailable; falling back to SAF staging for " + uri, error);
            return null;
        }
    }

'''
    helper_anchor = '    private File newStageFile(String name, Uri uri) throws Exception {'
    source = replace_once(source, helper_anchor, stage_helper + direct_path_helper + helper_anchor, "storage staging and original-path helpers")

    open_loop_old = '''                for (Uri uri : uris) {
                    File stage = newStageFile(displayName(uri), uri);
                    copyUriToFile(uri, stage);
                    rememberUri(stage, uri);
                    paths.put(stage.getAbsolutePath());
                }'''
    open_loop_new = '''                for (Uri uri : uris) {
                    // The same SAF open handler serves plug-ins and project imports (.ecproj/.aep).
                    // Preserve their real source parent when the original broad permission is granted.
                    String originalPath = originalSharedStoragePath(uri);
                    if (originalPath != null) {
                        Log.i(TAG, "Using original shared-storage path for import: " + originalPath);
                        paths.put(originalPath);
                        continue;
                    }
                    File stage = newStageFile(displayName(uri), uri);
                    copyUriToFile(uri, stage);
                    rememberUri(stage, uri);
                    Log.i(TAG, "Using SAF staged path for import: " + stage.getAbsolutePath());
                    paths.put(stage.getAbsolutePath());
                }'''
    source = replace_once(source, open_loop_old, open_loop_new, "permission-first original path import")

    # Replace the builder's file-channel copy with ContentResolver streaming. Some
    # DocumentsProviders expose pipes whose FileChannel.size() is zero even for non-empty files.
    copy_start = source.find("    private void copyUriToFile(Uri uri, File destination) throws Exception {")
    if copy_start < 0:
        raise SystemExit("Could not locate Android SAF URI copy method")
    copy_end = source.find("\n    /**\n     * Collect the file(s) an", copy_start)
    if copy_end < 0:
        raise SystemExit("Could not locate the end of Android SAF URI copy method")
    copy_method = r'''    private void copyUriToFile(Uri uri, File destination) throws Exception {
        InputStream input = getContentResolver().openInputStream(uri);
        if (input == null) {
            throw new java.io.IOException("Android document provider did not open the selected file");
        }
        try (InputStream in = input; FileOutputStream out = new FileOutputStream(destination, false)) {
            byte[] buffer = new byte[256 * 1024];
            int count;
            while ((count = in.read(buffer)) != -1) {
                out.write(buffer, 0, count);
            }
            out.flush();
            out.getFD().sync();
        }
        if (!destination.isFile() || destination.length() == 0) {
            throw new java.io.IOException("所选文件读取结果为空，请重新选择文件。");
        }
    }
'''
    source = source[:copy_start] + copy_method + source[copy_end:]

    path.write_text(source, encoding="utf-8")
    print("Configured SAF pickers to start in shared Download storage.")
    print("Added ordered writable staging fallback: app external files, private files, then cache.")
    print("Granted shared-storage files keep their original path; other providers use ContentResolver staged copies.")


def patch_builder(builder: Path) -> None:
    path = builder / "lib/build-common.sh"
    source = path.read_text(encoding="utf-8")

    # Keep the special Android "Allow management of all files" permission in the manifest,
    # but do not interrupt normal launches. The permission is requested when either import
    # entry opens the shared file picker, and then the original import continues after Settings.
    call = "    saf_bridge.request_storage_permission();"
    permission = 'name = "android.permission.MANAGE_EXTERNAL_STORAGE"'
    if source.count(call) != 1:
        raise SystemExit("Expected exactly one original startup storage-permission request")
    if permission not in source:
        raise SystemExit("MANAGE_EXTERNAL_STORAGE manifest declaration is missing from build-common.sh")
    source = source.replace(call + "\n", "", 1)
    if call in source:
        raise SystemExit("Startup storage-permission request was not removed")
    path.write_text(source, encoding="utf-8")

    # Route QQ / Files / browser ACTION_VIEW handoffs for AEP documents to the AEP
    # importer, rather than treating them as native EffectCraft project files.
    incoming_old = '''    "effectcraft": \'\'\'        if let Err(error) = self.inner.session.execute("file.open", serde_json::json!({ "path": path })) {
            log::error!("Could not open the incoming file {path}: {error}");
        }
\'\'\','''
    incoming_new = '''    "effectcraft": \'\'\'        let extension = std::path::Path::new(path)
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        let command = if matches!(extension.as_str(), "aep" | "aepx") {
            "file.importAep"
        } else {
            "file.open"
        };
        if let Err(error) = self.inner.session.execute(command, serde_json::json!({ "path": path })) {
            log::error!("Could not open the incoming file {path}: {error}");
        }
\'\'\','''
    if incoming_new not in source:
        if source.count(incoming_old) != 1:
            raise SystemExit("Could not uniquely locate EffectCraft's incoming-file handler")
        source = source.replace(incoming_old, incoming_new, 1)
    if 'matches!(extension.as_str(), "aep" | "aepx")' not in source:
        raise SystemExit("AEP incoming-file routing was not applied")
    path.write_text(source, encoding="utf-8")

    associations_path = builder / "lib/file_associations.py"
    associations = associations_path.read_text(encoding="utf-8")
    old_association = '    "effectcraft": ["ecproj", "ecprojx", "ectemplate"],'
    new_association = '    "effectcraft": ["ecproj", "ecprojx", "ectemplate", "aep", "aepx"],'
    if new_association not in associations:
        count = associations.count(old_association)
        if count != 1:
            raise SystemExit(f"Could not uniquely find EffectCraft's Android file associations (found {count})")
        associations = associations.replace(old_association, new_association, 1)
    associations_path.write_text(associations, encoding="utf-8")

    print("Kept MANAGE_EXTERNAL_STORAGE in the Android manifest.")
    print("Moved the storage permission prompt from app startup to plug-in/project import.")
    print("Denied or unavailable access continues through the SAF picker and app-owned staging.")


def main() -> None:
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not builder.is_dir():
        raise SystemExit("ARTCRAFT_DIR must point to the checked-out Android builder")
    patch_activity(builder)
    patch_builder(builder)


if __name__ == "__main__":
    main()
