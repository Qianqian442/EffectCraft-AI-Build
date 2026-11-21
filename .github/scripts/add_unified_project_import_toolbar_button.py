#!/usr/bin/env python3
"""Add a real unified project-import shortcut to the horizontally scrollable toolbar."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1"


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")

    header = root / "crates/ui-egui/src/header.rs"
    source = header.read_text(encoding="utf-8")
    if MARKER in source:
        if 'crate::menus::invoke(app, ui.ctx(), "file.importProject", json!({}))' not in source:
            raise SystemExit("Unified project-import marker exists but is not connected to the native importer.")
        print("Unified project-import toolbar shortcut is already installed.")
        return

    call_anchor = (
        "    let x = plugin_import_button(app, ui, x, cy);\n"
        "    let x = tool_slots(app, ui, &p, x, cy);"
    )
    if source.count(call_anchor) != 1:
        raise SystemExit("Could not uniquely locate the top-left plug-in button and tool slots.")

    source = source.replace(
        call_anchor,
        "    let x = plugin_import_button(app, ui, x, cy);\n"
        "    let x = project_import_button(app, ui, x, cy);\n"
        "    let x = tool_slots(app, ui, &p, x, cy);",
        1,
    )

    function_anchor = "/// The tool slots (with group separators after camera tools and pan-behind); returns the x after them.\n"
    if source.count(function_anchor) != 1:
        raise SystemExit("Could not uniquely locate the toolbar helper insertion point.")

    helper = '''/// EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1
/// Opens the same native unified project picker used by File > Import.
fn project_import_button(app: &mut EffectcraftApp, ui: &mut egui::Ui, x: f32, cy: f32) -> f32 {
    let rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(76.0, 26.0));
    let response = ui
        .put(rect, egui::Button::new("导入工程"))
        .on_hover_text("导入 Ae、AM、NV、CapCut 或 Ae 工程包");
    app.auto.add_response("header.importProject", &response, "导入工程");
    widgets::focus_outline(ui, &response, &app.tokens);
    if response.clicked() {
        match crate::menus::invoke(app, ui.ctx(), "file.importProject", json!({})) {
            Ok(_) => app.ui.status = "已打开统一工程导入；请选择工程文件或工程包。".into(),
            Err(error) => app.ui.status = format!("打开工程导入失败：{error}"),
        }
    }
    x + 82.0
}

'''
    source = source.replace(function_anchor, helper + function_anchor, 1)
    if source.count(MARKER) != 1:
        raise SystemExit("Unified project-import shortcut marker must appear exactly once.")
    if 'crate::menus::invoke(app, ui.ctx(), "file.importProject", json!({}))' not in source:
        raise SystemExit("Unified project-import button is not connected to the native file picker.")
    header.write_text(source, encoding="utf-8")
    print("Added a unified project-import button beside the existing top-left toolbar shortcuts.")
    print("The button invokes the original file.importProject picker; format-specific File > Import entries remain unchanged.")


if __name__ == "__main__":
    main()
