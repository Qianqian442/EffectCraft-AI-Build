# Rebuild trigger: ensure final module-scope export-helper repair is included.
#!/usr/bin/env python3
"""Final source gate for the generated Android EffectCraft checkout.

The export helpers are injected by more than one patch script. This last gate
checks their Rust module scope after *all* UI patches have run, and restores the
aspect-ratio helper if an earlier script accidentally left it nested or absent.
It also verifies that the Android locale default patch actually landed.
"""
from __future__ import annotations

import os
import re
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
    # AM-style Undo/Redo must use the engine's native project history, not a visual-only button.
    undo_required = (
        "EFFECTCRAFT_ANDROID_AM_UNDO_REDO_BUTTONS_V1",
        "Icon::Undo", "Icon::Redo", '"edit.undo"', '"edit.redo"',
        "!app.session.history.undo.is_empty()", "!app.session.history.redo.is_empty()",
    )
    missing_undo = [token for token in undo_required if token not in header_source]
    icons = (root / "crates/ui-egui/src/icons.rs").read_text(encoding="utf-8")
    if missing_undo or "Undo =>" not in icons or "Redo =>" not in icons:
        raise SystemExit("AM-style Undo/Redo is missing or disconnected from native edit history: " + "; ".join(missing_undo))
    print("Verified AM-style Undo/Redo buttons call the native edit history.")
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
    if "EFFECTCRAFT_ANDROID_FIVE_PROJECT_IMPORT_BUTTONS_V1" in project:
        raise SystemExit("Duplicate five-format project buttons remain in the Project panel.")
    if "EFFECTCRAFT_ANDROID_PROJECT_HEADER_IMPORT_V7" not in project or '"project.importMedia"' not in project:
        raise SystemExit("The Project panel must retain its media import shortcut.")
    if '"project.importProject"' in project or "导入工程" in project:
        raise SystemExit("Project import must stay in File > Import, not the Project panel.")
    for label in ("导入电脑版Ae工程", "导入手机版Ae工程", "导入am工程", "导入NV工程", "导入capcut工程"):
        if label in project:
            raise SystemExit(f"Project import label {label} must stay in File > Import.")
    print("Verified the Project panel keeps media import only; project formats stay in File > Import.")

    frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_PICTURE_VIDEO_PICKER_V2" not in frontend:
        raise SystemExit("The dedicated picture/video picker is missing.")
    if "let import_extensions = if pictures_and_videos { footage(PICTURE_VIDEO) } else { footage(MEDIA) };" not in frontend:
        raise SystemExit("Picture/video filtering is not scoped to the dedicated Project-panel button.")
    if '"wav"' not in frontend or '"gltf"' not in frontend or "footage(MEDIA)" not in frontend:
        raise SystemExit("The original generic File > Import media types were removed.")
    print("Verified only the dedicated Media button filters to pictures/videos; generic File > Import retains other media types.")

    file_cmd = (root / "crates/engine/src/cmd/file.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_AUTO_ADD_IMPORTED_MEDIA_V4" not in file_cmd or "picturesAndVideos" not in file_cmd:
        raise SystemExit("The picture/video shortcut is not scoped separately from generic File > Import.")
    if "new_comp(s, r, None, true)" not in file_cmd:
        raise SystemExit("Picture/video imports without an active composition do not create a fitted composition.")
    if "json!(still_duration)" in file_cmd and "stillDuration" not in file_cmd:
        raise SystemExit("A removed optional duration parameter is still being applied.")
    layer_create = (root / "crates/engine/src/cmd/layer/create.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_FIT_IMPORTED_MEDIA_TO_COMP_V2" not in layer_create:
        raise SystemExit("Imported picture/video layers no longer fit the composition when explicitly requested.")
    file_more = (root / "crates/engine/src/cmd/file_more.rs").read_text(encoding="utf-8")
    if 'b_p(p, "fitToComp").unwrap_or(false)' not in file_more:
        raise SystemExit("Fit-to-comp is not an opt-in setting for New Comp from Selection.")
    print("Verified media-only auto-add and optional fit; still duration follows existing user preferences.")

    menu = (root / "crates/engine/src/menus.rs").read_text(encoding="utf-8")
    import_match = re.search(r"(?m)^  Import\r?$", menu)
    if not import_match:
        raise SystemExit("The original File > Import menu block is missing.")
    end_match = re.search(r"(?m)^  Import Recent Footage\r?$", menu[import_match.end():])
    if not end_match:
        raise SystemExit("The end of the File > Import menu block is missing.")
    visible_import = menu[import_match.start():import_match.end() + end_match.start()]
    if "EffectCraft Project... | file.importProject" not in visible_import:
        raise SystemExit("The original native EffectCraft Project import action is missing from File > Import.")
    required_imports = [
        "File... | file.import",
        "Multiple Files... | file.importMultiple",
        "更多工程格式",
        "Adobe Premiere Pro Project... | file.importTimeline",
        "After Effects Project... | file.importAep",
        "Placeholder... | file.importPlaceholder",
        "Solid... | file.importSolid",
        "Lottie... | file.importLottie",
        "Vanishing Point (.vpe)... | file.importVanishingPoint",
        "Essential Graphics Template... | essential.importTemplate",
    ]
    if any(item not in visible_import for item in required_imports):
        raise SystemExit("Moving the Project import action removed or hid another original Import command.")
    if "导入电脑版Ae工程... | file.importAepDesktop" not in visible_import:
        raise SystemExit("The dedicated desktop AE project import option is missing.")
    if "导入手机版Ae工程... | file.importAepMobilePackage" not in visible_import:
        raise SystemExit("The dedicated mobile AE project package import option is missing.")
    if "EffectCraft 手机版工程包... | file.importEffectCraftMobile" not in visible_import:
        raise SystemExit("The preserved EffectCraft mobile project package import option is missing.")
    for menu_entry in (
        "导入电脑版Ae工程... | file.importAepDesktop",
        "导入手机版Ae工程... | file.importAepMobilePackage",
        "导入am工程... | file.importAlightMotionProject",
        "导入NV工程... | file.importNodeVideoProject",
        "导入capcut工程... | file.importCapCutProject",
        "EffectCraft Project... | file.importProject",
    ):
        if menu_entry not in visible_import:
            raise SystemExit(f"File > Import is missing a format-specific entry: {menu_entry}")
    print("Verified five separate project formats and original EffectCraft import in File > Import.")

    aep_commands = (root / "crates/engine/src/cmd/aep.rs").read_text(encoding="utf-8")
    if '"file.importAepDesktop"' not in aep_commands or '"file.importAep"' not in aep_commands:
        raise SystemExit("The desktop AE alias or original AE import command is missing.")
    aep_picker = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    if '"file.importAepDesktop" => ("path", Ask::Open(&["aep", "aepx"]))' not in aep_picker:
        raise SystemExit("The AE desktop picker is not scoped to .aep/.aepx.")
    if '"file.importAep" => ("path", Ask::Open(&["aep", "aepx"]))' not in aep_picker:
        raise SystemExit("The original AE project picker was removed.")
    if '"file.importEffectCraftMobile" => ("path", Ask::Open(&["ecproj", "ecprojx", "zip"]))' not in aep_picker:
        raise SystemExit("The EffectCraft mobile picker must accept .ecproj/.ecprojx and ZIP packages.")
    for mapping in (
        '"file.importAepMobilePackage" => ("path", Ask::Open(&["zip"]))',
        '"file.importAlightMotionProject" => ("path", Ask::Open(&["xml", "alight", "zip"]))',
        '"file.importNodeVideoProject" => ("path", Ask::Open(&["nv", "json", "zip"]))',
        '"file.importCapCutProject" => ("path", Ask::Open(&["json", "zip"]))',
    ):
        if mapping not in aep_picker:
            raise SystemExit(f"Missing project-specific file picker mapping: {mapping}")

    mobile_importer = (root / "crates/engine/src/cmd/am_nv.rs").read_text(encoding="utf-8")
    if '"file.importEffectCraftMobile"' not in mobile_importer or "import_effectcraft_mobile_project" not in mobile_importer:
        raise SystemExit("The EffectCraft mobile-export project import command is missing.")
    if '"ecproj" | "ecprojx"' not in mobile_importer or '"zip" =>' not in mobile_importer:
        raise SystemExit("The EffectCraft native mobile project importer no longer recognizes its project packages.")
    if 'super::import_project::import_project(s, &json!({"path": actual}))' not in mobile_importer:
        raise SystemExit("The EffectCraft native mobile project is not routed to the native project reader.")
    for command in ("file.importAepMobilePackage", "file.importAlightMotionProject", "file.importNodeVideoProject", "file.importCapCutProject"):
        if f'"{command}"' not in mobile_importer:
            raise SystemExit(f"Missing format-specific importer command: {command}")
    if "尚未确认该手机 AE 应用的真实工程格式" not in mobile_importer:
        raise SystemExit("The AE mobile import action must report unknown mobile formats honestly.")
    if 'super::aep::import_aep(s, &params)' in mobile_importer:
        raise SystemExit("The mobile AE import must not route a desktop AEP package through the desktop importer.")

    aep_loss_guard = (root / "crates/ui-egui/src/panels/aep_losses.rs").read_text(encoding="utf-8")
    if '"file.importAepDesktop"' not in aep_loss_guard:
        raise SystemExit("The dedicated desktop AE import entry bypasses the original loss-confirmation guard.")
    print("Verified separate desktop AE and EffectCraft mobile-export import entries; mobile packages use the native .ecproj reader.")
    import_project_command = (root / "crates/engine/src/cmd/import_project.rs").read_text(encoding="utf-8")
    if '"file.importProject"' not in import_project_command:
        raise SystemExit("The native Project importer command was removed instead of relocated.")
    print("Verified the original EffectCraft Project importer remains in File > Import.")

    timeline = (root / "crates/ui-egui/src/panels/timeline.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_VISIBLE_KEYFRAME_BUTTON_V3" not in timeline or "let keyframe_enabled = selected_layer.is_some();" not in timeline:
        raise SystemExit("The keyframe button still requires Project-panel footage selection.")
    if "EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_RESOLVE_V2" not in timeline or "android_collect_curve_segments" not in timeline:
        raise SystemExit("The curve action does not resolve keyframe segments from the Timeline playhead.")
    curve_playhead_required = (
        "EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_SOURCE_V3",
        "fn android_playhead_curve_segment(app: &EffectcraftApp, playhead: Tick)",
        "android_curve_quick_access(app, ui, rect, g.time)",
        "app.session.state.selected_keys",
    )
    missing_curve = [token for token in curve_playhead_required if token not in timeline]
    if missing_curve:
        raise SystemExit("Curve presets are not bound to the visible Timeline playhead/selected keys: " + "; ".join(missing_curve))
    if "layer.comp_time(pair[0].time)" not in timeline or "layer.comp_time(pair[1].time)" not in timeline:
        raise SystemExit("The curve resolver does not account for the layer's comp-time mapping.")
    if "EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_SOURCE_V3" not in timeline:
        raise SystemExit("The curve resolver does not use the displayed Timeline playhead.")
    if "android_playhead_curve_segment(app, playhead)" not in timeline:
        raise SystemExit("The curve picker is not using its visible playhead argument.")
    if "android_curve_quick_access(app, ui, rect, g.time)" not in timeline:
        raise SystemExit("The curve picker is not receiving the Timeline's displayed current-time indicator.")
    if "app.session.state.selected_keys" not in timeline:
        raise SystemExit("The curve resolver does not use selected keyframes to identify the target property.")
    if "layer_ids.push(key.layer)" not in timeline:
        raise SystemExit("The curve resolver does not include the layer owning a touch-selected keyframe.")
    viewer = (root / "crates/ui-egui/src/panels/viewer.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_PROJECT_FILE_VIEWER_SELECTION_V3" not in viewer:
        raise SystemExit("Composition viewer selection is not synchronized for direct keyframing.")
    print("Verified viewer-selected layers can be keyed without Project-panel selection.")

    assistant = (root / "crates/ui-egui/src/ai_assistant.rs").read_text(encoding="utf-8")
    if "Sense::click_and_drag()" not in assistant or "bubble_drag_origin" not in assistant or "response.drag_delta()" not in assistant:
        raise SystemExit("The floating AI assistant is missing its tap-and-drag interaction.")
    if "EFFECTCRAFT_ANDROID_AI_EXPANDED_DRAG_V2" not in assistant or "full_screen: bool" not in assistant or "还原窗口" not in assistant:
        raise SystemExit("The AI assistant full-screen/restore patch was overwritten or is missing.")
    print("Verified the AI bubble is draggable and the chat window keeps its full-screen/restore control.")

    if "full_screen: bool" not in assistant or 'ui.button(if state.full_screen' not in assistant:
        raise SystemExit("The AI assistant is missing its full-screen / restore control.")
    if "egui::WindowDrag::TitleBar" not in assistant:
        raise SystemExit("AI assistant drag handling may intercept inner controls; title-bar-only drag is required.")
    print("Verified AI assistant fullscreen mode and title-bar-only window dragging.")

    widgets = (root / "crates/ui-egui/src/widgets.rs").read_text(encoding="utf-8")
    if 'id.with("touch-pan")' in widgets:
        raise SystemExit("A full-panel touch drag may intercept normal button taps.")
    print("Verified shared touch scrolling does not capture entire panels or block child buttons.")

    if "EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_RESOLVE_V2" not in timeline or "android_collect_curve_segments" not in timeline:
        raise SystemExit("Curve presets cannot resolve a unique keyframe interval under the playhead.")
    print("Verified Curve can resolve a unique adjacent keyframe pair from the playhead position.")

    timing = (root / "crates/engine/src/cmd/layer/timing.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_EXTEND_COMP_ON_LAYER_OUT_DRAG_V1" not in timing or "if extend_comp" not in timing:
        raise SystemExit("Dragging a layer's Out edge cannot extend the composition duration.")
    if "24.0 * 60.0 * 60.0" in timing or "Tick::from_seconds_f64(24.0" in timing:
        raise SystemExit("Timeline duration still has an artificial 24-hour drag ceiling.")
    if "comp.work_area.1 = required_end" not in timing:
        raise SystemExit("Composition work area no longer follows the extended composition end.")
    timeline_source = (root / "crates/ui-egui/src/panels/timeline.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_LAYER_OUT_DRAG_EXTENDS_COMP_V1" not in timeline_source or '"extendComp": true' not in timeline_source:
        raise SystemExit("Timeline Out-edge drag is not requesting composition extension.")
    if "EFFECTCRAFT_ANDROID_TOUCH_TRIM_HANDLES_V1" not in timeline_source or "TRIM_OUTSIDE: f32 = 18.0" not in timeline_source or "grip_height" not in timeline_source:
        raise SystemExit("The layer Out edge is missing its larger touch target or visible trim handle.")
    print("Verified Out-edge finger handle extends the layer, composition and timeline range.");

    if 'window_ui.label(format!("导出进度：{:.0}%"' not in header_source or "show_percentage()" not in header_source:
        raise SystemExit("The export progress popup is missing its numeric percentage.")
    if "export_progress_dialog(app, ui);" not in header_source:
        raise SystemExit("The export progress popup is not drawn by the Android header.")
    print("Verified export progress displays a real numeric percentage.")

    import_frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_SHARE_COLLECTED_PROJECT_V1" not in import_frontend:
        raise SystemExit("Mobile full-project export does not wait for Collect Files before sharing.")
    if "shareAfterCollect" not in import_frontend or "share_project_package(project_path)" not in import_frontend:
        raise SystemExit("The mobile project Sharesheet handoff is not connected to the completed collection.")
    print("Verified mobile project ZIP sharing starts after the folder picker and footage collection finish.")


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
