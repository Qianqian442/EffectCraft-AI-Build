#!/usr/bin/env python3
"""Enable the existing verified folder relinker on Android primary shared storage."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact anchor, found {count}")
    return source.replace(old, new, 1)


def replace_or_verify(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    return replace_once(source, old, new, label)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/engine/src/cmd/relink.rs"
    if not path.is_file():
        raise SystemExit(f"The native footage relinker source is missing: {path}")
    source = path.read_text(encoding="utf-8")

    marker = "EFFECTCRAFT_ANDROID_PRIMARY_STORAGE_RELINK_V1"
    enabled_old = r"""fn enabled(_: &Session) -> std::result::Result<(), String> {
    if cfg!(target_arch = "wasm32") { Err("folder relinking requires the desktop filesystem".into()) } else { Ok(()) }
}"""
    enabled_new = r"""// EFFECTCRAFT_ANDROID_PRIMARY_STORAGE_RELINK_V1
// Desktop and Android both have a native filesystem. On Android, the folder picker
// first obtains on-demand All files access and only returns a validated primary-storage path.
fn folder_relink_supported(wasm32: bool) -> bool {
    !wasm32
}

fn enabled(_: &Session) -> std::result::Result<(), String> {
    if folder_relink_supported(cfg!(target_arch = "wasm32")) {
        Ok(())
    } else {
        Err("folder relinking requires a native filesystem".into())
    }
}

/// AEP files imported on Android may still contain Windows drive paths.
fn stored_file_name(path: &str) -> Option<&str> {
    path.rsplit(['/', '\\']).find(|part| !part.is_empty())
}"""
    if marker not in source:
        source = replace_once(source, enabled_old, enabled_new, "native/Android relink platform gate")
    elif "fn stored_file_name(path: &str) -> Option<&str>" not in source:
        raise SystemExit("Android relink marker exists without the cross-platform basename helper.")

    source = replace_or_verify(
        source,
        "parent.join(Path::new(file).file_name()?)",
        "parent.join(stored_file_name(file)?)",
        "cross-platform image-sequence basename",
    )
    source = replace_or_verify(
        source,
        'let name = Path::new(&old.path).file_name().and_then(std::ffi::OsStr::to_str).unwrap_or("");',
        'let name = stored_file_name(&old.path).unwrap_or("");',
        "cross-platform imported AEP media basename",
    )

    help_old = "{folder: string (recursive desktop search, no symlinks; max 100000 entries), dryRun?: bool (report only), wait?: bool (return results inline; otherwise jobs.list/jobs.wait)} — relinks only unique exact filenames with compatible metadata; preserves interpretation and sequence ranges. Reports high/low confidence and ambiguous, incompatible, unsupported or notFound items."
    help_new = "{folder: string (recursive native-folder search; Android: primary shared storage only, no symlinks; max 100000 entries), dryRun?: bool (report only), wait?: bool (return results inline; otherwise jobs.list/jobs.wait)} — desktop and Android; relinks only unique exact filenames with compatible metadata; preserves interpretation and sequence ranges. Reports ambiguous, incompatible, unsupported or notFound items."
    source = replace_or_verify(source, help_old, help_new, "Android folder relink command documentation")

    test_marker = "fn android_native_folder_relink_is_enabled_but_web_is_not()"
    if test_marker not in source:
        test_anchor = r"""    #[test]
    fn moved_roots_and_remaps() {"""
        test_replacement = r"""    #[test]
    fn android_native_folder_relink_is_enabled_but_web_is_not() {
        assert!(folder_relink_supported(false), "Android and desktop use native filesystems");
        assert!(!folder_relink_supported(true), "browser filesystem is not a native folder");
    }

    #[test]
    fn aep_windows_media_paths_match_file_names_on_android() {
        assert_eq!(stored_file_name(r"D:\Work\Job\media\clip.mp4"), Some("clip.mp4"));
        assert_eq!(stored_file_name("/storage/emulated/0/Movies/clip.mp4"), Some("clip.mp4"));
        assert_eq!(stored_file_name(r"D:\Work\Job\frames\shot_0001.png"), Some("shot_0001.png"));
    }

    #[test]
    fn moved_roots_and_remaps() {"""
        source = replace_once(source, test_anchor, test_replacement, "Android relink path regression tests")

    required = (
        "fn folder_relink_supported(wasm32: bool) -> bool",
        'folder_relink_supported(cfg!(target_arch = "wasm32"))',
        "fn stored_file_name(path: &str) -> Option<&str>",
        "parent.join(stored_file_name(file)?)",
        'let name = stored_file_name(&old.path).unwrap_or("");',
        "Android: primary shared storage only",
        "ENTRY_LIMIT: usize = 100_000",
        "if ty.is_dir()",
        "compatible(old, &f)",
        "accepted.len() == 1",
        "fn android_native_folder_relink_is_enabled_but_web_is_not()",
        "fn aep_windows_media_paths_match_file_names_on_android()",
    )
    for token in required:
        if token not in source:
            raise SystemExit(f"The existing safe relinker changed or its Android enablement is incomplete: {token}")

    path.write_text(source, encoding="utf-8")
    print("Enabled the existing recursive, metadata-verified Relink Missing Footage command on Android.")
    print("Android scanning remains restricted to a user-selected primary shared-storage folder.")
    print("Windows drive paths and backslash-separated image sequences now match correctly on Android.")
    print("Unique filenames and compatible media metadata are still required; duplicates/incompatible media are not auto-linked.")
    print("Preserves all existing relink, replace-footage, sequence and interpretation behavior.")


if __name__ == "__main__":
    main()
