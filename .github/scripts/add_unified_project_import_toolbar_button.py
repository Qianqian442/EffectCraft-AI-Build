#!/usr/bin/env python3
"""Add a real unified project-import shortcut beside the existing plug-in toolbar entry."""
from __future__ import annotations

import os
import re
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

    # make_header_scrollable.py moves the toolbar into a child Ui named scroll_ui and
    # places the Puppet shortcut between the plug-in button and the tool slots. Match
    # the actual plug-in call, regardless of which Ui variable the layout uses.
    call_pattern = re.compile(
        r"(?m)^(?P<indent>[ \\t]*)let x = plugin_import_button\\(app, (?P<ui>ui|scroll_ui), x, cy\\);[ \\t]*$"
    )
    matches = list(call_pattern.finditer(source))
    if len(matches) != 1:
        raise SystemExit(
            "Could not uniquely locate the existing top-left plug-in toolbar call "
            f"(expected 1, found {len(matches)})."
        )

    match = matches[0]
    ui_name = match.group("ui")
    insert_at = match.end()
    source = (
        source[:insert_at]
        + f"\\n{match.group('indent')}let x = project_import_button(app, {ui_name}, x, cy);"
        + source[insert_at:]
    )

    function_anchor = "/// The tool slots (with group separators after camera tools and pan-behind); returns the x after them.\\n"
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
    print("Added a unified project-import button beside the existing top-left plug-in shortcut.")
    print("The button invokes the original file.importProject picker; all existing File > Import entries remain unchanged.")


if __name__ == "__main__":
    main()
