#!/usr/bin/env python3
"""Final source gate for the generated Android EffectCraft checkout.

The export helpers are injected by more than one patch script. This last gate
checks their Rust module scope after *all* UI patches have run, and restores the
aspect-ratio helper if an earlier script accidentally left it nested or absent.
It also verifies that the Android locale default patch actually landed.
"""
from __future__ import annotations

import os
from pathlib import Path


DIMENSIONS_HELPER = r'''
/// Preserve source aspect ratio while converting the selected export resolution
/// to even dimensions. Supports landscape, portrait and square compositions.
fn effectcraft_export_dimensions(source_width: u32, source_height: u32, resolution: &str) -> (u32, u32) {
    let target_height = match resolution {
        "480" => 480_u32,
        "720" => 720_u32,
        "1080" => 1080_u32,
        "1440" => 1440_u32,
        "2160" => 2160_u32,
        _ => return (source_width.max(2) & !1, source_height.max(2) & !1),
    };
    let source_width = source_width.max(1);
    let source_height = source_height.max(1);
    let scaled_width = ((source_width as f64 * target_height as f64)
        / source_height as f64)
        .round()
        .clamp(2.0, 8192.0) as u32;
    let width = (scaled_width.max(2) & !1).max(2);
    (width, target_height)
}
'''


def top_level_function_count(source: str, name: str) -> int:
    """Count function definitions at Rust module depth zero, ignoring comments/strings."""
    needle = f"fn {name}("
    depth = 0
    count = 0
    i = 0
    n = len(source)
    while i < n:
        if source.startswith("//", i):
            end = source.find("\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if source.startswith("/*", i):
            i += 2
            comment_depth = 1
            while i < n and comment_depth:
                if source.startswith("/*", i):
                    comment_depth += 1
                    i += 2
                elif source.startswith("*/", i):
                    comment_depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        # Skip Rust raw strings (r#"..."#, br#"..."#, etc.).
        raw_start = i
        if source.startswith("br", i):
            raw_start += 2
        elif source.startswith("r", i):
            raw_start += 1
        if raw_start < n and source[raw_start] == "#":
            j = raw_start
            while j < n and source[j] == "#":
                j += 1
            if j < n and source[j] == '"':
                hashes = j - raw_start
                terminator = '"' + ("#" * hashes)
                end = source.find(terminator, j + 1)
                i = n if end < 0 else end + len(terminator)
                continue
        if source[i] == '"':
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                elif source[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        # Skip short Rust character literals such as '{', '}', and '\\n',
        # but do not mistake lifetimes like 'a or 'static for character literals.
        if source[i] == "'":
            end = source.find("'", i + 1, min(n, i + 18))
            newline = source.find("\\n", i + 1, min(n, i + 18))
            if end >= 0 and (newline < 0 or end < newline):
                literal_body = source[i + 1:end]
                if literal_body and not any(ch.isspace() for ch in literal_body):
                    i = end + 1
                    continue
        if depth == 0 and source.startswith(needle, i):
            count += 1
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth < 0:
                raise SystemExit("Rust source has an unmatched closing brace before export helper validation.")
        i += 1
    if depth != 0:
        raise SystemExit("Rust source has unbalanced braces before export helper validation.")
    return count


def ensure_dimensions_helper(header: Path) -> None:
    source = header.read_text(encoding="utf-8")
    count = top_level_function_count(source, "effectcraft_export_dimensions")
    if count == 0:
        source = source.rstrip() + "\n\n" + DIMENSIONS_HELPER.strip() + "\n"
        header.write_text(source, encoding="utf-8")
        print("Restored effectcraft_export_dimensions at Rust module scope.")
    elif count == 1:
        print("effectcraft_export_dimensions is present at Rust module scope.")
    else:
        raise SystemExit(f"Expected exactly one module-level effectcraft_export_dimensions; found {count}.")

    verified = top_level_function_count(header.read_text(encoding="utf-8"), "effectcraft_export_dimensions")
    if verified != 1:
        raise SystemExit("Export dimensions helper did not pass the final module-scope check.")


def verify_chinese_default(root: Path) -> None:
    prefs = (root / "crates/engine/src/settings/prefs/sections.rs").read_text(encoding="utf-8")
    i18n = (root / "crates/ui-egui/src/i18n.rs").read_text(encoding="utf-8")
    if 'language: String = "zh-hans".into(),' not in prefs:
        raise SystemExit("Android default-language patch did not set General.language to zh-hans.")
    android_fallback = '''#[cfg(target_os = "android")]
            { "zh-hans" }'''
    if android_fallback not in i18n:
        raise SystemExit("Saved 'system' preference is not forced to Simplified Chinese on Android.")
    print("Android default language is Simplified Chinese, including saved 'system' preferences.")


def verify_android_project_interactions(root: Path, header: Path) -> None:
    """Fail the APK build if the five export actions, import control or touch fixes regress."""
    header_source = header.read_text(encoding="utf-8")
    export_labels = [
        "导出 AE 电脑版工程",
        "导出 AE 手机版工程",
        "导出 AM 工程",
        "导出 NV 工程",
        "导出 CapCut 工程",
    ]
    for label in export_labels:
        if label not in header_source:
            raise SystemExit(f"Missing required independent project-export button: {label}")
    if 'ComboBox::from_id_salt("effectcraft-project-export-choice")' in header_source:
        raise SystemExit("Project export regressed to a dropdown instead of five independent buttons.")
    if "尚未实现" not in header_source or "AEP/AEPX" not in header_source:
        raise SystemExit("The unavailable desktop AE exporter must be clearly disclosed in the UI.")
    print("Verified the five requested independent project-export buttons and honest AE desktop status.")

    project = (root / "crates/ui-egui/src/panels/project.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_PROJECT_HEADER_IMPORT_V5" not in project:
        raise SystemExit("The visible Project-panel Import Media control is missing.")
    if "compact_import_layout" not in project or "import_rect.max.y + 6.0" not in project:
        raise SystemExit("The narrow-screen Import Media layout no longer moves the header below the button.")
    print("Verified the image/video Import Media button uses a non-overlapping narrow-screen layout.")

    frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_PICTURE_VIDEO_IMPORT_ONLY_V1" not in frontend:
        raise SystemExit("The normal Import Media picker is not restricted to picture/video media.")
    if "VIDEO_EXTENSIONS.iter()" not in frontend:
        raise SystemExit("Video extensions were removed from the normal Import Media picker.")

    file_cmd = (root / "crates/engine/src/cmd/file.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_AUTO_ADD_IMPORTED_MEDIA_V2" not in file_cmd or 'params["addToComp"] = json!(true);' not in file_cmd:
        raise SystemExit("Import Media no longer automatically inserts selected assets into the active composition.")
    layer_create = (root / "crates/engine/src/cmd/layer/create.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_FIT_IMPORTED_MEDIA_TO_COMP_V2" not in layer_create:
        raise SystemExit("Imported picture/video layers no longer fit the active composition.")
    print("Verified image/video imports are added to the composition and fitted to the frame.")

    menu = (root / "crates/engine/src/menus.rs").read_text(encoding="utf-8")
    if "导入素材... | file.import" not in menu or "导入工程... | file.importProject" not in menu:
        raise SystemExit("The Import menu must expose one media entry and one unified project entry.")
    visible_import = menu[menu.find("  Import\\n"):menu.find("  Import Recent Footage\\n")]
    if visible_import.count("导入工程... | file.importProject") != 1:
        raise SystemExit("Duplicate project-import entries are visible in the Import menu.")
    print("Verified the Import menu has one media entry and one unified project entry.")

    timeline = (root / "crates/ui-egui/src/panels/timeline.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_VISIBLE_KEYFRAME_BUTTON_V3" not in timeline or "let keyframe_enabled = selected_layer.is_some();" not in timeline:
        raise SystemExit("The keyframe button still requires Project-panel footage selection.")
    viewer = (root / "crates/ui-egui/src/panels/viewer.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_PROJECT_FILE_VIEWER_SELECTION_V3" not in viewer:
        raise SystemExit("Composition viewer selection is not synchronized for direct keyframing.")
    print("Verified viewer-selected layers can be keyed without Project-panel selection.")

    assistant = (root / "crates/ui-egui/src/ai_assistant.rs").read_text(encoding="utf-8")
    if "Sense::click_and_drag()" not in assistant or "bubble_drag_origin" not in assistant or "response.drag_delta()" not in assistant:
        raise SystemExit("The floating AI assistant is missing its tap-and-drag interaction.")
    print("Verified the floating AI assistant bubble supports tap and touch-drag.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    header = root / "crates/ui-egui/src/header.rs"
    if not header.is_file():
        raise SystemExit(f"Generated EffectCraft header source is missing: {header}")
    ensure_dimensions_helper(header)
    verify_android_project_interactions(root, header)
    memory_helper_count = top_level_function_count(header.read_text(encoding="utf-8"), "effectcraft_export_memory_ok")
    if memory_helper_count != 1:
        raise SystemExit(f"Expected one module-level effectcraft_export_memory_ok helper; found {memory_helper_count}.")
    print("Android export memory safety helper is present without imposing an application memory ceiling.")
    verify_chinese_default(root)

    parity = root / "docs/localization-parity.md"
    if parity.is_file():
        report = parity.read_text(encoding="utf-8")
        row = next((line.strip() for line in report.splitlines() if line.startswith("| Simplified Chinese |")), None)
        if row:
            print("Upstream localization baseline (not a completion claim):")
            print(row)
    print("Final Android source patch gate passed.")


if __name__ == "__main__":
    main()
