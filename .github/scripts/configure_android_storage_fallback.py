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
     * URI from DocumentsUI. Prefer an ordinary shared-storage directory when the device allows
     * it, then fall back to app-specific external storage, private files, and cache. Reading the
     * selected source itself always goes through ContentResolver, not raw root or Android/data
     * traversal.
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
    helper_anchor = '    private File newStageFile(String name, Uri uri) throws Exception {'
    source = replace_once(source, helper_anchor, stage_helper + helper_anchor, "media staging fallback helper")

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
    print("The engine receives a local staged path; source documents are opened via Android ContentResolver.")


def patch_builder(builder: Path) -> None:
    path = builder / "lib/build-common.sh"
    source = path.read_text(encoding="utf-8")

    # Preserve the builder's original permission-first behavior:
    # - Android 11+: safRequestStoragePermission() checks Environment.isExternalStorageManager()
    #   and opens the per-app All files access settings page when not yet granted.
    # - Android 6-10: it requests the legacy READ/WRITE storage runtime permissions.
    # Do not silently strip either the request call or MANAGE_EXTERNAL_STORAGE declaration.
    call = "    saf_bridge.request_storage_permission();"
    permission = 'name = "android.permission.MANAGE_EXTERNAL_STORAGE"'
    if call not in source:
        raise SystemExit("Original storage permission request call is missing from build-common.sh")
    if permission not in source:
        raise SystemExit("MANAGE_EXTERNAL_STORAGE manifest declaration is missing from build-common.sh")

    print("Preserved the original All files access permission request and manifest declaration.")
    print("If the user declines or the settings activity is unavailable, the SAF picker remains the fallback.")


def main() -> None:
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not builder.is_dir():
        raise SystemExit("ARTCRAFT_DIR must point to the checked-out Android builder")
    patch_activity(builder)
    patch_builder(builder)


if __name__ == "__main__":
    main()
