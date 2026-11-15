#!/usr/bin/env python3
"""Replace the single Project-panel import action with five independent project import buttons."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_FIVE_PROJECT_IMPORT_BUTTONS_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_project_panel(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    old_project_rect = """    let project_rect = Rect::from_min_size(
        pos2(
            if compact_import_layout { rect.min.x + 8.0 } else { media_rect.max.x + button_gap },
            if compact_import_layout { media_rect.max.y + 3.0 } else { button_y },
        ),
        vec2(button_width, 22.0),
    );
"""
    source = replace_once(source, old_project_rect, "", "remove the old single Project import button geometry")
    source = source.replace("    let button_gap = 8.0;\n", "", 1)

    old_button = r'''    let project_response = ui
        .put(project_rect, egui::Button::new("导入工程").min_size(project_rect.size()))
        .on_hover_text("导入 EffectCraft、AE、AM、NodeVideo 和 CapCut 工程");
    app.auto.add_response("project.importProject", &project_response, "导入工程");
    if project_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importProject", json!({}))
    {
        app.ui.status = error;
    }
'''
    new_buttons = r'''    // EFFECTCRAFT_ANDROID_FIVE_PROJECT_IMPORT_BUTTONS_V1
    // Five independent format-specific actions. Use two columns when the panel is wide
    // enough; stack all five on narrow phone layouts so labels remain readable.
    let import_columns = if rect.width() < 250.0 { 1 } else { 2 };
    let import_button_full_width = (rect.width() - 16.0).max(40.0);
    let import_button_width = if import_columns == 1 {
        import_button_full_width
    } else {
        ((rect.width() - 24.0) * 0.5).max(56.0)
    };
    let import_left = rect.min.x + 8.0;
    let import_right = import_left + import_button_width + 8.0;
    let import_top = media_rect.max.y + 4.0;
    let import_pitch = 27.0;
    let import_row_y = |index: usize| {
        let row = if import_columns == 1 { index } else { index / 2 };
        import_top + row as f32 * import_pitch
    };
    let import_column_x = |index: usize| {
        if import_columns == 1 || index % 2 == 0 { import_left } else { import_right }
    };

    let import_ae_desktop_rect = Rect::from_min_size(
        pos2(import_column_x(0), import_row_y(0)), vec2(import_button_width, 24.0)
    );
    let import_ae_mobile_rect = Rect::from_min_size(
        pos2(import_column_x(1), import_row_y(1)), vec2(import_button_width, 24.0)
    );
    let import_am_rect = Rect::from_min_size(
        pos2(import_column_x(2), import_row_y(2)), vec2(import_button_width, 24.0)
    );
    let import_nv_rect = Rect::from_min_size(
        pos2(import_column_x(3), import_row_y(3)), vec2(import_button_width, 24.0)
    );
    let import_capcut_rect = Rect::from_min_size(
        pos2(import_left, import_row_y(4)), vec2(import_button_full_width, 24.0)
    );

    let import_ae_desktop_response = ui
        .put(import_ae_desktop_rect, egui::Button::new("导入电脑版AE工程").min_size(import_ae_desktop_rect.size()))
        .on_hover_text("选择 Adobe After Effects 电脑版 .aep/.aepx 工程");
    app.auto.add_response("project.importAeDesktop", &import_ae_desktop_response, "导入电脑版AE工程");
    if import_ae_desktop_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importAepDesktop", json!({}))
    {
        app.ui.status = error;
    }

    let import_ae_mobile_response = ui
        .put(import_ae_mobile_rect, egui::Button::new("导入手机版AE工程").min_size(import_ae_mobile_rect.size()))
        .on_hover_text("选择手机版 AE 导出的 ZIP 工程包；当前识别包内 .aep/.aepx，其他格式需用真实样例适配");
    app.auto.add_response("project.importAeMobile", &import_ae_mobile_response, "导入手机版AE工程");
    if import_ae_mobile_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importAepMobilePackage", json!({}))
    {
        app.ui.status = error;
    }

    let import_am_response = ui
        .put(import_am_rect, egui::Button::new("导入AM工程").min_size(import_am_rect.size()))
        .on_hover_text("选择 Alight Motion XML 或包含工程和素材的 ZIP");
    app.auto.add_response("project.importAlightMotion", &import_am_response, "导入AM工程");
    if import_am_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importAlightMotionProject", json!({}))
    {
        app.ui.status = error;
    }

    let import_nv_response = ui
        .put(import_nv_rect, egui::Button::new("导入NV工程").min_size(import_nv_rect.size()))
        .on_hover_text("选择 NodeVideo .nv、JSON 或 ZIP 工程包");
    app.auto.add_response("project.importNodeVideo", &import_nv_response, "导入NV工程");
    if import_nv_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importNodeVideoProject", json!({}))
    {
        app.ui.status = error;
    }

    let import_capcut_response = ui
        .put(import_capcut_rect, egui::Button::new("导入CapCut工程").min_size(import_capcut_rect.size()))
        .on_hover_text("选择 CapCut draft_content.json 或包含草稿和素材的 ZIP");
    app.auto.add_response("project.importCapCut", &import_capcut_response, "导入CapCut工程");
    if import_capcut_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importCapCutProject", json!({}))
    {
        app.ui.status = error;
    }
'''
    source = replace_once(source, old_button, new_buttons, "replace the single Import Project button with five format buttons")
    source = replace_once(
        source,
        "    let actions_bottom = if compact_import_layout { project_rect.max.y } else { media_rect.max.y };\n    let hdr = Rect::from_min_size(pos2(rect.min.x, actions_bottom + 6.0), vec2(rect.width(), 20.0));",
        "    let actions_bottom = import_capcut_rect.max.y;\n    let hdr = Rect::from_min_size(pos2(rect.min.x, actions_bottom + 6.0), vec2(rect.width(), 20.0));",
        "move Project panel columns below all five import buttons",
    )
    if MARKER not in source:
        raise SystemExit("Five project import controls were not installed")
    path.write_text(source, encoding="utf-8")


def patch_frontend_pickers(root: Path) -> None:
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    anchor = '        "file.importEffectCraftMobile" => ("path", Ask::Open(&["ecproj", "ecprojx", "zip"])),'
    mappings = '''        "file.importAepMobilePackage" => ("path", Ask::Open(&["zip"])),
        "file.importAlightMotionProject" => ("path", Ask::Open(&["xml", "alight", "zip"])),
        "file.importNodeVideoProject" => ("path", Ask::Open(&["nv", "json", "zip"])),
        "file.importCapCutProject" => ("path", Ask::Open(&["json", "zip"])),
'''
    if all(name in source for name in (
        '"file.importAepMobilePackage" =>',
        '"file.importAlightMotionProject" =>',
        '"file.importNodeVideoProject" =>',
        '"file.importCapCutProject" =>',
    )):
        return
    source = replace_once(source, anchor, mappings + anchor, "add five-button project picker file filters")
    path.write_text(source, encoding="utf-8")


def patch_aep_loss_guard(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/aep_losses.rs"
    source = path.read_text(encoding="utf-8")
    old = 'id == "file.importAep" || id == "file.importAepDesktop"'
    new = old + ' || id == "file.importAepMobilePackage"'
    if new not in source:
        source = replace_once(source, old, new, "apply the original AE loss-confirmation guard to mobile AE packages")
        path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    patch_project_panel(root)
    patch_frontend_pickers(root)
    patch_aep_loss_guard(root)

    project = (root / "crates/ui-egui/src/panels/project.rs").read_text(encoding="utf-8")
    for label in ("导入电脑版AE工程", "导入手机版AE工程", "导入AM工程", "导入NV工程", "导入CapCut工程"):
        if label not in project:
            raise SystemExit(f"Missing independent project import button: {label}")
    frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    for command in ("file.importAepDesktop", "file.importAepMobilePackage",
                    "file.importAlightMotionProject", "file.importNodeVideoProject", "file.importCapCutProject"):
        if f'"{command}" =>' not in frontend:
            raise SystemExit(f"Missing file picker mapping for {command}")
    print("Installed five independent project import buttons with separate desktop AE, mobile AE package, AM, NV and CapCut pickers.")


if __name__ == "__main__":
    main()
