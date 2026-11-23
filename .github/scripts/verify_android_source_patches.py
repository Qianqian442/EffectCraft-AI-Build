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
    if "EFFECTCRAFT_ANDROID_FORCE_SIMPLIFIED_CHINESE_V1" not in i18n:
        raise SystemExit("Android interface is not locked to Simplified Chinese.")
    if '"zh-hans"' not in i18n or 'let _ = app;' not in i18n:
        raise SystemExit("Android Simplified Chinese language override is incomplete.")

    effects = (root / "crates/ui-egui/src/i18n/effects.rs").read_text(encoding="utf-8")
    effects_start = effects.find("const SIMPLIFIED_CHINESE: &[Row] = &[")
    effects_end = effects.find("\n];", effects_start)
    ui = (root / "crates/ui-egui/src/i18n/ui.rs").read_text(encoding="utf-8")
    ui_start = ui.find("const SIMPLIFIED_CHINESE:")
    ui_end = ui.find("\n];", ui_start)
    if min(effects_start, effects_end, ui_start, ui_end) < 0:
        raise SystemExit("Could not locate the Simplified Chinese translation catalogs.")
    effects_block = effects[effects_start:effects_end]
    ui_block = ui[ui_start:ui_end]
    effect_names = re.findall(
        r'\(\s*"[^"]+"\s*,\s*"[^"]+"\s*,\s*"((?:\\.|[^"])*)"\s*\)',
        effects_block,
    )
    ui_labels = re.findall(
        r'\(\s*"(?:\\.|[^"]*)"\s*,\s*"((?:\\.|[^"])*)"\s*\)',
        ui_block,
    )
    if len(effect_names) < 300 or len(ui_labels) < 1000:
        raise SystemExit("Simplified Chinese translation catalogs are unexpectedly incomplete.")
    for label in effect_names + ui_labels:
        visible = re.sub(r"\\[nrt]", "", label)
        # "Ae" is the required product name, not untranslated English UI copy.
        visible = visible.replace("Ae", "")  # The product name may touch Chinese text without spaces.
        if re.search(r"[A-Za-z]", visible):
            raise SystemExit(f"Simplified Chinese interface still displays English: {label}")
    print(
        f"Verified Chinese-only Android UI: {len(effect_names)} effect names and "
        f"{len(ui_labels)} panel, dialog and menu labels."
    )


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
        "导出Ae手机版工程",
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
    crash_guard = (
        "EFFECTCRAFT_ANDROID_EXPORT_COMMAND_PANIC_GUARD_V1",
        'match effectcraft_run_export_command(app, &ctx, "renderQueue.add", params) {',
        'effectcraft_run_export_command(app, &ctx, "renderQueue.setRender",',
    )
    missing_guard = [item for item in crash_guard if item not in header_source]
    if missing_guard:
        raise SystemExit("Android Export button crash guard is incomplete: " + "; ".join(missing_guard))

    # The export patch appends the progress popup before the setup dialog.
    # Validate both definitions independently instead of assuming source order.
    export_start = header_source.find("fn export_dialog(")
    progress_start = header_source.find("fn export_progress_dialog(")
    if export_start < 0 or progress_start < 0:
        raise SystemExit("The centered export dialog or Render Queue progress dialog is missing.")
    quick_export = header_source[export_start:]
    if '"renderQueue.add"' not in quick_export or '"renderQueue.render"' not in quick_export:
        raise SystemExit("Quick video export is not routed through the native Render Queue.")
    if "effectcraft_android_video_staging_path" in quick_export or '"renderQueue.setOutput"' in quick_export:
        raise SystemExit("Quick video export must use the Render Queue's resolved output path without a staging override.")
    if "EFFECTCRAFT_ANDROID_EXPORT_START_PANIC_GUARD_V1" not in quick_export:
        raise SystemExit("Synchronous Render Queue startup must remain panic guarded.")
    print("Verified video export writes directly through the Render Queue; Gallery publication is only post-render.")


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
    builder_root = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    saf_activity = (builder_root / "templates/android/SafActivity.java").read_text(encoding="utf-8")
    if "Intent.ACTION_GET_CONTENT" not in saf_activity or "launchDocumentMediaFallback" not in saf_activity:
        raise SystemExit("Android 12 media imports must prefer a gallery/media provider and keep a fallback.")

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
    if "自有工程... | file.importProject" not in visible_import:
        raise SystemExit("The original native self-owned project import action is missing from File > Import.")
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
    if "自有工程包... | file.importEffectCraftMobile" not in visible_import:
        raise SystemExit("The preserved EffectCraft mobile project package import option is missing.")
    if "工程压缩包（ZIP/RAR）... | file.extractProjectArchive" not in visible_import:
        raise SystemExit("ZIP/RAR project archive import is missing from File > Import.")
    for menu_entry in (
        "导入电脑版Ae工程... | file.importAepDesktop",
        "导入手机版Ae工程... | file.importAepMobilePackage",
        "导入am工程... | file.importAlightMotionProject",
        "导入NV工程... | file.importNodeVideoProject",
        "导入capcut工程... | file.importCapCutProject",
        "自有工程... | file.importProject",
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
        raise SystemExit("The self-owned project picker must accept .ecproj/.ecprojx and ZIP packages.")
    if '"file.extractProjectArchive" => ("path", Ask::Open(&["zip", "rar"]))' not in aep_picker:
        raise SystemExit("ZIP/RAR project packages are not selectable from File > Import.")
    for mapping in (
        '"file.importAepMobilePackage" => ("path", Ask::Open(&["ecproj", "ecprojx", "zip"]))',
        '"file.importAlightMotionProject" => ("path", Ask::Open(&["amproj", "xml", "alight", "zip"]))',
        '"file.importNodeVideoProject" => ("path", Ask::Open(&["nv", "json", "zip"]))',
        '"file.importCapCutProject" => ("path", Ask::Open(&["json", "zip"]))',
    ):
        if mapping not in aep_picker:
            raise SystemExit(f"Missing project-specific file picker mapping: {mapping}")

    mobile_importer = (root / "crates/engine/src/cmd/am_nv.rs").read_text(encoding="utf-8")
    if '"file.importEffectCraftMobile"' not in mobile_importer or "import_effectcraft_mobile_project" not in mobile_importer:
        raise SystemExit("The self-owned project import command is missing.")
    if '"file.extractProjectArchive"' not in mobile_importer or "extract_project_rar" not in mobile_importer:
        raise SystemExit("ZIP/RAR extraction and RAR decoding are missing.")
    engine_manifest = (root / "crates/engine/Cargo.toml").read_text(encoding="utf-8")
    if 'rars = { version = "0.12.3", default-features = false }' not in engine_manifest:
        raise SystemExit("The native RAR reader dependency is missing.")
    if '"ecproj" | "ecprojx"' not in mobile_importer or '"zip" =>' not in mobile_importer:
        raise SystemExit("The native self-owned project importer no longer recognizes its project packages.")
    if "EFFECTCRAFT_ANDROID_MOBILE_IMPORT_ACCEPTS_SELF_EXPORT_V1" not in mobile_importer:
        raise SystemExit("The mobile-Ae import button does not dispatch native self-export projects.")
    if "contains_self_project" not in mobile_importer:
        raise SystemExit("The mobile-Ae ZIP importer does not inspect archive entries for .ecproj/.ecprojx.")
    if '"file.importAepMobilePackage" => ("path", Ask::Open(&["ecproj", "ecprojx", "zip"]))' not in aep_picker:
        raise SystemExit("The mobile-Ae picker must accept native .ecproj/.ecprojx files and ZIP packages.")
    if 'super::import_project::import_project(s, &json!({"path": actual}))' not in mobile_importer:
        raise SystemExit("The self-owned project is not routed to the native project reader.")
    for command in ("file.importAepMobilePackage", "file.importAlightMotionProject", "file.importNodeVideoProject", "file.importCapCutProject"):
        if f'"{command}"' not in mobile_importer:
            raise SystemExit(f"Missing format-specific importer command: {command}")
    if "尚未确认该手机 AE 应用的真实工程格式" not in mobile_importer:
        raise SystemExit("The AE mobile import action must report unknown mobile formats honestly.")
    if 'super::aep::import_aep(s, &params)' in mobile_importer:
        raise SystemExit("The mobile AE import must not route a desktop AEP package through the desktop importer.")

    aep_report = (root / "crates/aep/src/import/report.rs").read_text(encoding="utf-8")
    aep_layer_build = (root / "crates/aep/src/import/build.rs").read_text(encoding="utf-8")
    if "guides are not decoded" in aep_report.lower() or "s.guide = h.is_guide();" not in aep_layer_build:
        raise SystemExit("The AEP import report must reflect the verified guide-layer switch support.")

    aep_loss_guard = (root / "crates/ui-egui/src/panels/aep_losses.rs").read_text(encoding="utf-8")
    if '"file.importAepDesktop"' not in aep_loss_guard:
        raise SystemExit("The dedicated desktop AE import entry bypasses the original loss-confirmation guard.")
    for diagnostic in (
        "fn needs_prompt(report: &Value)",
        "if !needs_prompt(&report)",
        "fn imported_lines(report: &Value)",
        "fn diagnostics(report: &Value)",
        '"missingFootage"',
        '"missingFonts"',
        '"limitations"',
        "重新链接缺失素材",
        "文件名唯一",
        "替代字体",
        "导入完成后，打开“文件 > 依赖项 > 重新链接缺失素材”",
        "请允许 Ae 使用“所有文件访问”权限",
        "外置 SD 卡目录请先复制到内部存储",
        "只自动匹配文件名唯一且媒体参数一致的素材",
        '"预计识别并导入的内容："',
        '"未支持、替代或需要处理的内容："',
        '"继续导入（仍有未支持内容）"',
        "const DETAILS: usize = 20;",
        "for line in imported_lines(&report)",
        "for (head, details) in diagnostics(&report)",
    ):
        if diagnostic not in aep_loss_guard:
            raise SystemExit(f"The AE import review dialog is missing a required diagnostic: {diagnostic}")
    print("Verified separate desktop AE and mobile project imports, plus missing-media/font/parser-limit diagnostics.")
    incoming_router = (root / "crates/ui-egui/src/menus.rs").read_text(encoding="utf-8")
    if '"zip" | "rar"' not in incoming_router or '"file.extractProjectArchive"' not in incoming_router:
        raise SystemExit("Incoming ZIP/RAR shares are not unpacked and dispatched by their inner project type.")
    print("Verified incoming ZIP/RAR packages are extracted before their format-specific importers.")

    import_project_command = (root / "crates/engine/src/cmd/import_project.rs").read_text(encoding="utf-8")
    if '"file.importProject"' not in import_project_command:
        raise SystemExit("The native Project importer command was removed instead of relocated.")
    print("Verified the original EffectCraft Project importer remains in File > Import.")

    timeline = (root / "crates/ui-egui/src/panels/timeline.rs").read_text(encoding="utf-8")
    am_effects = (root / "crates/ui-egui/src/panels/effects_presets.rs").read_text(encoding="utf-8")
    effect_controls = (root / "crates/ui-egui/src/panels/effect_controls/panel.rs").read_text(encoding="utf-8")
    widgets = (root / "crates/ui-egui/src/widgets.rs").read_text(encoding="utf-8")
    home = (root / "crates/ui-egui/src/panels/home.rs").read_text(encoding="utf-8")
    am_editor_path = root / "crates/ui-egui/src/am_editor.rs"
    if not am_editor_path.is_file():
        raise SystemExit("The independent AM editor is missing.")
    am_editor = am_editor_path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_AM_EFFECT_BROWSER_V1" not in am_editor or "am_effect_browser" not in am_editor:
        raise SystemExit("The AM-owned visual effect browser is missing.")
    if "EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1" not in widgets or "PanelScroll::begin" not in effect_controls:
        raise SystemExit("AM effect parameter drawers must scroll with AM-scoped finger gestures.")
    if "EFFECTCRAFT_ANDROID_TAP_TO_APPLY_EFFECT_V1" in am_effects or "EFFECTCRAFT_ANDROID_TOUCH_SCROLL_PANEL_V1" in widgets:
        raise SystemExit("The AM patch must not change global Ae effect-row or panel-scroll behavior.")
    if "PanelScroll::begin" not in effect_controls:
        raise SystemExit("Native Effect Controls must retain its scrollable parameter panel.")
    if "EFFECTCRAFT_AM_PORTRAIT_HOME_V1" not in home:
        raise SystemExit("Ae×am portrait Home is missing.")
    if "EFFECTCRAFT_AM_NATIVE_EFFECT_BROWSER_V1" in am_effects or "show_am_native" in am_effects:
        raise SystemExit("The retired simplified AM effect-card replacement must not return.")
    if "EFFECTCRAFT_ANDROID_VISIBLE_KEYFRAME_BUTTON_V3" not in timeline or "let keyframe_enabled = selected_layer.is_some();" not in timeline:
        raise SystemExit("The keyframe button still requires Project-panel footage selection.")
    if "EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_RESOLVE_V2" not in timeline or "android_collect_curve_segments" not in timeline:
        raise SystemExit("The curve action does not resolve keyframe segments from the Timeline playhead.")
    curve_playhead_required = (
        "EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_SOURCE_V3",
        "fn android_playhead_curve_segment(app: &EffectcraftApp, playhead: Tick)",
        "android_curve_quick_access(app, ui, rect, g.tl.time)",
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
    if "android_curve_quick_access(app, ui, rect, g.tl.time)" not in timeline:
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
    if "EFFECTCRAFT_ANDROID_AI_FULLSCREEN_DRAG_V1" not in assistant or "full_screen: bool" not in assistant or "还原窗口" not in assistant:
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
    if "EFFECTCRAFT_ANDROID_EXPORT_START_PANIC_GUARD_V1" not in header_source:
        raise SystemExit("Synchronous render-start panics are not converted into visible export errors.")
    if "effectcraft-export-progress-start-time" not in header_source or "startup_elapsed < 5.0" not in header_source:
        raise SystemExit("The export progress popup must allow asynchronous render startup before reporting failure.")
    am_editor_source = (root / "crates/ui-egui/src/am_editor.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1" not in am_editor_source or 'invoke(app, ui.ctx(), "file.importProject", json!({}))' not in am_editor_source:
        raise SystemExit("The independent AM editor is missing its unified project-import shortcut.")
    if "EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1" in header_source or "project_import_button(app," in header_source:
        raise SystemExit("AM-only project-import controls must not alter the original Ae header or toolbar.")
    print("Verified export progress and guarded render startup in the shared exporter.")
    print("Verified the unified project-import shortcut exists only in the independent AM editor; the original Ae toolbar remains unchanged.")

    import_frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_SHARE_COLLECTED_PROJECT_V1" not in import_frontend:
        raise SystemExit("Mobile full-project export does not wait for Collect Files before sharing.")
    if "shareAfterCollect" not in import_frontend or "share_project_package(project_path)" not in import_frontend:
        raise SystemExit("The mobile project Sharesheet handoff is not connected to the completed collection.")
    builder_root = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    saf_activity = (builder_root / "templates/android/SafActivity.java").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_QQ_PROJECT_SHARE_V1" not in saf_activity or "Toast.makeText(activity, \"工程分享失败：\"" not in saf_activity:
        raise SystemExit("QQ ZIP packaging/share failures must be shown to the user, not only written to logcat.")
    if "archive.length() <= 22" not in saf_activity or "chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)" not in saf_activity:
        raise SystemExit("QQ ZIP share package validation/content-URI read grant is missing.")
    print("Verified mobile project ZIP sharing starts after Collect Files and reports Android Sharesheet errors.")

    if "EFFECTCRAFT_ANDROID_SHARE_ALL_PROJECT_EXPORTS_V1" not in import_frontend:
        raise SystemExit("AM, NodeVideo and CapCut exports are not connected to the project Sharesheet.")
    for token in (
        '"file.saveCopy"',
        '"file.exportLottie"',
        '"file.exportAlightMotion"',
        '"file.exportNodeVideo"',
        '"file.exportCapCut"',
        "share_project_file(exported_path)",
    ):
        if token not in import_frontend:
            raise SystemExit("A supported project export is missing its QQ share handoff: " + token)
    if "EFFECTCRAFT_ANDROID_QQ_PROJECT_FILE_SHARE_V1" not in saf_activity:
        raise SystemExit("Single-file project exports cannot be staged through FileProvider.")
    if "shareProjectFile" not in saf_activity or "分享工程文件（可选择 QQ）" not in saf_activity:
        raise SystemExit("The Android single-project-file Sharesheet bridge is incomplete.")
    if "share_project_file" not in (root / "crates/ui-egui/src/android_gallery.rs").read_text(encoding="utf-8"):
        raise SystemExit("The Rust-to-Android single-file project share bridge is missing.")
    print("Verified self, AM, NodeVideo and CapCut project exports all invoke the Android Sharesheet.")

    if "primary:Download" not in saf_activity or 'intent.setType("*/*")' not in saf_activity:
        raise SystemExit("The Android project picker no longer starts in Downloads with an all-file filter.")
    if '"zip" | "rar" => {' not in import_frontend and '"zip" | "rar" =>' not in (root / "crates/ui-egui/src/menus.rs").read_text(encoding="utf-8"):
        raise SystemExit("Downloaded ZIP/RAR project archives no longer route through the archive importer.")

    incoming_router = (root / "crates/ui-egui/src/menus.rs").read_text(encoding="utf-8")
    incoming_frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_AUTO_IMPORT_EXTERNAL_PROJECT_V1" not in incoming_router:
        raise SystemExit("Android-shared project files do not have an automatic format router.")
    if "EFFECTCRAFT_ANDROID_AUTO_IMPORT_EXTERNAL_PROJECT_V1" not in incoming_frontend:
        raise SystemExit("Incoming projects are not passed through the normal File > Import preflight path.")
    # ZIP/RAR files are extracted before inspecting the contained project extension.
    # Do not require the obsolete behavior that routed every ZIP directly to NodeVideo.
    for token in (
        '"zip" | "rar" => {',
        '"file.extractProjectArchive"',
        'return import_incoming_project(app, &inner);',
    ):
        if token not in incoming_router:
            raise SystemExit(f"Automatic ZIP/RAR extraction routing is missing: {token}")
    for token in (
        '"aep" | "aepx" => "file.importAepDesktop"',
        '"ecproj" | "ecprojx" => "file.importEffectCraftMobile"',
        '"nv" => "file.importNodeVideoProject"',
        '"alight" => "file.importAlightMotionProject"',
        '"fcpxml" | "otio" | "edl" | "aaf" | "omf" => "file.importTimeline"',
        '"lottie" => "file.importLottie"',
        "file.importNodeVideoProject",
    ):
        if token not in incoming_router:
            raise SystemExit(f"Automatic project import routing is missing: {token}")
    if "run_with_picked(app, command, \"path\"" not in incoming_frontend:
        raise SystemExit("Incoming project imports bypass the original importer preflight/dialog path.")
    if "selected_rar" not in incoming_frontend or "file.extractProjectArchive" not in incoming_frontend:
        raise SystemExit("The unified Import Project entry does not route selected RAR archives through extraction.")
    if '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx", "nv", "zip", "rar", "amproj", "xml", "alight", "aep", "aepx", "json"])),' not in incoming_frontend:
        raise SystemExit("The unified project picker does not expose supported QQ-downloaded RAR files.")
    print("Verified automatic opening routes all supported external project formats through the existing importers.")



def verify_am_workspace_and_android_integrity(root: Path) -> None:
    """Verify the isolated AM portrait surface and orientation-only Android bridge."""
    workspace = "AM 竖屏"
    dock = (root / "crates/ui-egui/src/dock.rs").read_text(encoding="utf-8")
    window = (root / "crates/ui-egui/src/app/window.rs").read_text(encoding="utf-8")
    app = (root / "crates/ui-egui/src/app.rs").read_text(encoding="utf-8")
    store = (root / "crates/ui-egui/src/workspace_state.rs").read_text(encoding="utf-8")
    timeline = (root / "crates/ui-egui/src/panels/timeline.rs").read_text(encoding="utf-8")
    am_editor_path = root / "crates/ui-egui/src/am_editor.rs"
    if not am_editor_path.is_file():
        raise SystemExit("The independent AM editor is missing.")
    am_editor_source = am_editor_path.read_text(encoding="utf-8")
    for token in ("fn draw_timeline", "am-mobile-trim", "layer.timing", "EFFECTCRAFT_AM_INDEPENDENT_EDITOR_SURFACE_V1"):
        if token not in am_editor_source:
            raise SystemExit(f"AM's independent timeline is missing its own clip-edge editing support: {token}")
    if "EFFECTCRAFT_ANDROID_AM_TOUCH_TRIM_HANDLES_V1" in timeline:
        raise SystemExit("AM patch must not alter the shared Ae Timeline hit targets.")
    frame = (root / "crates/ui-egui/src/app/frame.rs").read_text(encoding="utf-8")
    header = (root / "crates/ui-egui/src/header.rs").read_text(encoding="utf-8")
    if "workspace_transition" in frame:
        raise SystemExit("AM must not add a transition overlay to the Ae frame.")
    home = (root / "crates/ui-egui/src/panels/home.rs").read_text(encoding="utf-8")
    lib = (root / "crates/ui-egui/src/lib.rs").read_text(encoding="utf-8")
    # AM editing must route to its own touch-first page. The original DockArea
    # remains available as the fallback for Ae mode; it must not render in AM editing mode.
    if "self.dock_area(ui, body);" not in frame:
        raise SystemExit("The original Ae DockArea is missing from the Ae fallback path.")
    am_editor_path = root / "crates/ui-egui/src/am_editor.rs"
    if (
        "crate::am_editor::show(self, ui, full);" not in frame
        or 'self.ui.workspace == "AM 竖屏" && !self.ui.start_screen' not in frame
        or "pub mod am_editor;" not in lib
        or not am_editor_path.is_file()
    ):
        raise SystemExit("AM mode is still routed to the Ae DockArea instead of the independent AM editor.")
    am_editor = am_editor_path.read_text(encoding="utf-8")
    for token in (
        "EFFECTCRAFT_AM_INDEPENDENT_EDITOR_SURFACE_V1",
        "fn top_bar",
        "fn transport",
        "fn draw_timeline",
        "fn bottom_tools",
        "fn tool_drawer",
        "am.drawer.keyframes",
        "EFFECTCRAFT_AM_LONG_PRESS_LAYER_GROUPING_V1",
        "AM_LONG_PRESS_SECONDS",
        "am_group_selected_layers",
        "layer.precompose",
        "has_cross_group_links",
        "layer_action_drawer",
        "EFFECTCRAFT_AM_BOTTOM_SHEET_SLIDE_UP_V1",
        "am_bottom_sheet_progress",
        "颜色和填充",
        "边框和阴影",
        "混合和不透明度",
        "移动与效果",
        "编辑形状",
        "预设",
        "效果",
        "Tool::Pen",
        "Tool::Puppet",
    ):
        if token not in am_editor:
            raise SystemExit(f"Independent AM editor is missing a required mobile editing feature: {token}")

    for token in (
        "EFFECTCRAFT_AM_MOTION_EFFECT_EDITOR_V1",
        "EFFECTCRAFT_AM_SINGLE_MOTION_WORKSPACE_V1",
        '("移动与效果", "motion")',
        "fn am_motion_editor",
        "AM_MOTION_TAB_ID",
        "Sense::drag()",
        "滑动此处以移动图层",
        "PanelKind::EffectControls",
        '"keys.toggleTransform"',
        '"keys.setSegmentCurve"',
        '"keys.velocity"',
        '"am-motion-transform-control"',
        "am_open_effect_browser(&ctx,Some(layer_id))",
        "EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1",
    ):
        if token not in am_editor:
            raise SystemExit(f"AM single motion workspace is missing a required interaction: {token}")
    if '("变换", "transform")' in am_editor or '("关键帧 / 曲线", "keyframes")' in am_editor:
        raise SystemExit("AM Move & Transform must be one workspace, not three tabs.")
    if 'if self.ui.workspace != "AM 竖屏" {' not in frame:
        raise SystemExit("The Ae toolbar must be hidden on both the AM Home and AM editor.")
    if "EFFECTCRAFT_ANDROID_RESPONSIVE_HEADER_SCROLL_V1" not in header:
        raise SystemExit("The original horizontally swipeable Ae toolbar is missing.")
    if "let rx = workspace_menu(app, ui, p, rx, cy);" not in header:
        raise SystemExit("The original Ae workspace menu is missing.")
    if "workspace_tabs(app, ui, p, rx, left, cy);" not in header:
        raise SystemExit("The original Ae workspace tabs are missing.")
    if "EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1" in header or "layout_switch_row(" in header:
        raise SystemExit("The extra Ae/AM toolbar row must remain removed.")
    if 'let header_h = if self.ui.workspace == "AM 竖屏" { 0.0 } else { 40.0 };' not in frame:
        raise SystemExit("AM Home must own its header area while Ae retains its original 40px header.")
    if "FixedSecond(300.0)" not in dock or "FixedFirst(300.0)" not in dock:
        raise SystemExit("The original Ae fixed-width left/right panel arrangement is missing.")
    if '"AM 竖屏"' not in dock:
        raise SystemExit("AM 竖屏 is not registered in the existing workspace menu.")
    if "EFFECTCRAFT_AM_PORTRAIT_HOME_V1" not in home:
        raise SystemExit("Ae×am portrait Home is missing.")
    am_home_start = home.find("// EFFECTCRAFT_AM_PORTRAIT_HOME_V1")
    am_home_end = home.find("pub fn show(app:", am_home_start)
    if am_home_start < 0 or am_home_end < 0:
        raise SystemExit("Could not isolate the AM Home surface for offline-only validation.")
    am_home = home[am_home_start:am_home_end]
    if any(token in am_home for token in ("模板", "教程", "云端", "cloud", "server", "https://")):
        raise SystemExit("AM Home must not expose cloud, server-backed, or network-dependent features.")
    bridge = (root / "crates/ui-egui/src/android_layout.rs").read_text(encoding="utf-8")
    ui_cargo = (root / "crates/ui-egui/Cargo.toml").read_text(encoding="utf-8")

    for token in (
        f'"{workspace}"',
        "tabs(&[Composition, Layer], 0)",
        "tabs(&[Timeline, EffectsPresets, EffectControls, Properties, Project], 0)",
        "Ratio(0.42)",
    ):
        if token not in dock:
            raise SystemExit(f"AM portrait workspace is missing a required panel/layout element: {token}")
    if f'set_workspace_portrait(name == "{workspace}")' not in window:
        raise SystemExit("Switching away from AM does not restore sensor orientation.")
    if "workspace: ui.workspace.clone()" not in store or "ui.workspace = self.workspace" not in store:
        raise SystemExit("The active workspace name is not persisted/restored with workspaces.json.")
    if "set_workspace_portrait" not in window or "setWorkspacePortrait" not in bridge:
        raise SystemExit("The AM selection-only Android orientation bridge is not connected.")
    if "android_layout::set_workspace_portrait" in app:
        raise SystemExit("AM must not change the default Ae app-start orientation.")
    if 'jni = "0.22"' not in ui_cargo:
        raise SystemExit("The Android JNI dependency for orientation switching is missing.")

    builder_root = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    template = builder_root / "templates/android/SafActivity.java"
    if not template.is_file():
        raise SystemExit("Android SafActivity template is missing from ARTCRAFT_DIR.")
    java = template.read_text(encoding="utf-8")
    for token in (
        "EFFECTCRAFT_ANDROID_AM_ORIENTATION_ONLY_V2",
        "setWorkspacePortrait(boolean portrait)",
    ):
        if token not in java:
            raise SystemExit(f"AM-only orientation bridge is missing: {token}")
    if "verifyReleaseSigningCertificate()" in java or "EXPECTED_SIGNING_CERT_SHA256" in java:
        raise SystemExit("AM patch must not add a new signer gate to the Ae app startup path.")
    print("Verified AM is rendered in its independent portrait editor; the shared Ae Timeline and controls are unchanged.")
    # AM's custom visual effect browser calls the shared effect registry and effect.apply command.
    # Effect parameter values and renderer remain shared; only AM presentation and touch gestures are separate.
    am_effects = (root / "crates/ui-egui/src/panels/effects_presets.rs").read_text(encoding="utf-8")
    effect_registry = (root / "crates/effects/src/lib.rs").read_text(encoding="utf-8")
    plugin_api = (root / "crates/effects/src/plugin.rs").read_text(encoding="utf-8")
    effect_controls = (root / "crates/ui-egui/src/panels/effect_controls/panel.rs").read_text(encoding="utf-8")
    for token in ("effectcraft_engine::effects::all()", "effectcraft_engine::effects::find(id)", '"effect.apply"', "app.session.execute(cmd, params)"):
        if token not in am_effects:
            raise SystemExit(f"Native Effects & Presets lost its real effect-application path: {token}")
    for token in ("pub fn all()", "let plugins = plugin::plugins();", "v.extend(plugins);", "pub fn find(id: &str)", "plugin::plugins()"):
        if token not in effect_registry:
            raise SystemExit(f"Engine effect registry no longer exposes imported plug-ins: {token}")
    for token in ("pub fn register_plugin", "pub fn plugins()", "pub fn plugin(id: &str)", "pub trait EffectPlugin", "pub fn unregister_plugin(id: &str)"):
        if token not in plugin_api:
            raise SystemExit(f"Runnable plug-in effect API is missing: {token}")
    plugin_commands = (root / "crates/engine/src/cmd/effect.rs").read_text(encoding="utf-8")
    for token in ('"effect.plugins.unload"', "fn plugins_unload(", '"can_delete": can_delete', "BUILTIN_EFFECT_MODULES", "s.layer_cache.clear();", "cache.clear();"):
        if token not in plugin_commands:
            raise SystemExit(f"Safe plug-in removal path is missing: {token}")
    if "PanelScroll::begin" not in effect_controls:
        raise SystemExit("Native Effect Controls must display the real scrollable parameter panel.")
    widgets = (root / "crates/ui-egui/src/widgets.rs").read_text(encoding="utf-8")
    scroll_marker = "EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"
    if scroll_marker not in widgets or "am_touch_draw_context && ui.input" not in widgets:
        raise SystemExit("AM finger scrolling is not scoped to AM-owned drawers.")
    if "EFFECTCRAFT_ANDROID_TOUCH_SCROLL_PANEL_V2" in widgets or "EFFECTCRAFT_ANDROID_TAP_TO_APPLY_EFFECT_V1" in am_effects:
        raise SystemExit("AM must not install global Android touch behavior into Ae panels.")
    if "EFFECTCRAFT_AM_EFFECT_BROWSER_V1" not in am_editor:
        raise SystemExit("AM visual effect browser is not installed.")
    print("Verified AM's independent effect icon browser, live effect application and AM-scoped parameter scrolling.")
    print("Verified the Android host bridge only changes orientation while AM is selected.")


def verify_account_security(root: Path) -> None:
    # The build checks out this repository as "build-assets", not at the workspace
    # root. Prefer the explicit BUILD_ASSETS_DIR when set, while retaining the
    # older root-level locations for local and legacy workflow invocations.
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    assets_root = Path(os.environ.get("BUILD_ASSETS_DIR", str(workspace / "build-assets"))).resolve()
    worker_candidates = (
        root.parent.parent / "cloudflare-worker/src/index.js",
        workspace / "cloudflare-worker/src/index.js",
        assets_root / "cloudflare-worker/src/index.js",
    )
    worker = next((candidate for candidate in worker_candidates if candidate.is_file()), None)
    if worker is None:
        searched = ", ".join(str(candidate) for candidate in worker_candidates)
        raise SystemExit(
            "Cloudflare account worker source is missing; whitelist/ban protections cannot be verified. "
            f"Searched: {searched}"
        )
    cloud = worker.read_text(encoding="utf-8")

    admin_relative = Path("admin-app/app/src/main/java/com/qianqian/effectcraftadmin/MainActivity.java")
    admin_candidates = (workspace / admin_relative, assets_root / admin_relative)
    admin_path = next((candidate for candidate in admin_candidates if candidate.is_file()), None)
    if admin_path is None:
        searched = ", ".join(str(candidate) for candidate in admin_candidates)
        raise SystemExit(f"Admin account controls source is missing. Searched: {searched}")
    admin = admin_path.read_text(encoding="utf-8")

    for token in ("/v1/whitelist", "/v1/admin/whitelist", "/v1/admin/whitelist/remove", "requireWhitelistedIdentifiers", "ensureNotBanned", "banned_until"):
        if token not in cloud:
            raise SystemExit(f"Cloudflare account security route/check is missing: {token}")
    for token in ("注册 / 登录白名单", "加入白名单", "移除白名单", "封禁", "解禁", "/ban"):
        if token not in admin:
            raise SystemExit(f"Admin account controls are missing: {token}")
    print("Verified server-enforced whitelist, admin add/remove, login/register checks, and ban/unban controls.")

def verify_android_export_frame_scheduling(root: Path) -> None:
    pipeline = (root / "crates/export/src/pipeline.rs").read_text(encoding="utf-8")
    tests = pipeline[pipeline.find("#[cfg(test)]"):]
    required = (
        "EFFECTCRAFT_ANDROID_EXPORT_FRAME_SCHEDULING_V1",
        "pub(crate) fn cpu_inflight_for_platform(var: Option<&str>, android: bool) -> Option<usize>",
        'cpu_inflight_for_platform(std::env::var(CPU_INFLIGHT_ENV).ok().as_deref(), cfg!(target_os = "android"))',
        "android_export_defaults_to_one_in_flight_frame_without_overriding_explicit_settings",
    )
    for token in required:
        if token not in pipeline:
            raise SystemExit(f"Android export scheduling protection is incomplete: {token}")
    if "cpu_inflight_for_platform(None, true), Some(1)" not in tests or "cpu_inflight_for_platform(None, false), None" not in tests:
        raise SystemExit("Android/desktop export scheduling regression assertions are missing.")
    print("Verified Android export frame scheduling: one frame in flight by default; explicit setting overrides and desktop behavior are preserved.")


def verify_aep_post_import_media_prompt(root: Path) -> None:
    aep = (root / "crates/engine/src/cmd/aep.rs").read_text(encoding="utf-8")
    for token in (
        "EFFECTCRAFT_AEP_AUTO_PROMPT_MISSING_MEDIA_RELINK_V1",
        "let prompt_media_relink = !res.report.missing_footage.is_empty();",
        'command: "file.relinkFootage".into(),',
        "params: json!({}),",
    ):
        if token not in aep:
            raise SystemExit(f"AEP import does not offer missing-media relinking: {token}")
    print("Verified AEP import automatically offers the existing relink-folder picker when external media is missing.")


def verify_android_aep_media_relink(root: Path) -> None:
    relink = (root / "crates/engine/src/cmd/relink.rs").read_text(encoding="utf-8")
    frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    required = (
        "EFFECTCRAFT_ANDROID_PRIMARY_STORAGE_RELINK_V1",
        "fn folder_relink_supported(wasm32: bool) -> bool",
        'folder_relink_supported(cfg!(target_arch = "wasm32"))',
        "Android: primary shared storage only",
        "ENTRY_LIMIT: usize = 100_000",
        "compatible(old, &f)",
        "accepted.len() == 1",
        "fn stored_file_name(path: &str) -> Option<&str>",
        "parent.join(stored_file_name(file)?)",
        'let name = stored_file_name(&old.path).unwrap_or("");',
        "aep_windows_media_paths_match_file_names_on_android",
        "file.relinkFootage",
        "fn android_native_folder_relink_is_enabled_but_web_is_not()",
    )
    for token in required:
        if token not in relink:
            raise SystemExit(f"Android AEP missing-media relinking is incomplete: {token}")
    if '"file.relinkFootage" => ("folder", Ask::Folder),' not in frontend:
        raise SystemExit("Android AEP relinking is not wired to the native folder picker.")
    print("Verified Android AEP media relinking: primary-storage folder picker, unique-name and compatible-metadata matching, duplicate protection, and native-platform regression tests.")


def verify_android_aep_playback_guard(root: Path) -> None:
    frames = (root / "crates/ui-egui/src/frames.rs").read_text(encoding="utf-8")
    prefetch = (root / "crates/ui-egui/src/app/prefetch.rs").read_text(encoding="utf-8")
    tests = (root / "crates/ui-egui/src/frames/tests.rs").read_text(encoding="utf-8")
    for token in (
        "EFFECTCRAFT_ANDROID_AEP_PLAYBACK_RESOURCE_GUARD_V1",
        "const ANDROID_GPU_BUDGET: usize = 256 << 20;",
        "fn effectcraft_preview_worker_threads(reported: Option<usize>, android: bool) -> usize",
        "effectcraft_preview_worker_threads(reported_threads, cfg!(target_os = \"android\"))",
        "effectcraft_preview_gpu_budget(cfg!(target_os = \"android\"))",
    ):
        if token not in frames:
            raise SystemExit(f"Android imported-AEP playback memory guard is missing: {token}")
    if "EFFECTCRAFT_ANDROID_AEP_PLAYBACK_PREFETCH_GUARD_V1" not in prefetch or "workers.min(2).max(1)" not in prefetch:
        raise SystemExit("Android imported-AEP playback prefetch is not limited to two workers.")
    if "fn android_aep_playback_resource_guard_is_tested()" not in tests:
        raise SystemExit("Android imported-AEP playback scheduling regression tests are missing.")
    print("Verified Android imported-AEP playback: two frame workers, 256 MiB GPU preview budget, and regression tests.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    header = root / "crates/ui-egui/src/header.rs"
    if not header.is_file():
        raise SystemExit(f"Generated EffectCraft header source is missing: {header}")
    ensure_dimensions_helper(header)
    verify_android_project_interactions(root, header)
    verify_android_aep_playback_guard(root)
    verify_android_aep_media_relink(root)
    verify_aep_post_import_media_prompt(root)
    verify_android_export_frame_scheduling(root)
    memory_helper_count = top_level_function_count(header.read_text(encoding="utf-8"), "effectcraft_export_memory_ok")
    if memory_helper_count != 1:
        raise SystemExit(f"Expected one module-level effectcraft_export_memory_ok helper; found {memory_helper_count}.")
    print("Android export memory safety helper is present without imposing an application memory ceiling.")
    verify_chinese_default(root)
    verify_am_workspace_and_android_integrity(root)
    verify_account_security(root)

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
