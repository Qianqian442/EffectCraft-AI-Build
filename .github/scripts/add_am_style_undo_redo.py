#!/usr/bin/env python3
"""Add touch-friendly AM-style Undo / Redo buttons to the EffectCraft toolbar."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_AM_UNDO_REDO_BUTTONS_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_icons(root: Path) -> None:
    path = root / "crates/ui-egui/src/icons.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    source = replace_once(
        source,
        "    Pause,\n    StepBack,\n",
        "    Pause,\n    /// Undo the most recent project edit.\n    Undo,\n    /// Redo the most recently undone project edit.\n    Redo,\n    StepBack,\n",
        "add undo and redo icon variants",
    )
    source = replace_once(
        source,
        """        Pause => {
            pen.rect_fill(4.0, 3.0, 6.8, 13.0);
            pen.rect_fill(9.2, 3.0, 12.0, 13.0);
        }
        StepBack => {""",
        """        Pause => {
            pen.rect_fill(4.0, 3.0, 6.8, 13.0);
            pen.rect_fill(9.2, 3.0, 12.0, 13.0);
        }
        // EFFECTCRAFT_ANDROID_AM_UNDO_REDO_BUTTONS_V1
        Undo => {
            pen.line(&[(13.0, 5.0), (10.5, 3.6), (7.7, 3.4), (5.1, 4.6), (3.7, 6.8), (3.6, 9.3), (5.2, 11.8)]);
            pen.fill(&[(2.0, 4.0), (7.0, 4.0), (4.0, 9.0)]);
        }
        Redo => {
            pen.line(&[(3.0, 5.0), (5.5, 3.6), (8.3, 3.4), (10.9, 4.6), (12.3, 6.8), (12.4, 9.3), (10.8, 11.8)]);
            pen.fill(&[(14.0, 4.0), (9.0, 4.0), (12.0, 9.0)]);
        }
        StepBack => {""",
        "draw undo and redo icons",
    )
    path.write_text(source, encoding="utf-8")


def patch_header(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    # The responsive toolbar patch may use a different child UI identifier.
    # Find the actual call and reuse its identifier instead of assuming ui/scroll_ui.
    call_prefix = "let x = tool_slots(app, "
    call_suffix = ", &p, x, cy);"
    matching_lines = [
        line for line in source.splitlines()
        if line.strip().startswith(call_prefix) and line.strip().endswith(call_suffix)
    ]
    if len(matching_lines) != 1:
        raise SystemExit(
            "place touch Undo / Redo controls before the remaining toolbar tools: "
            f"expected one tool_slots() call, found {len(matching_lines)}"
        )

    original_line = matching_lines[0]
    stripped_line = original_line.strip()
    indent = original_line[:len(original_line) - len(original_line.lstrip())]
    ui_name = stripped_line[len(call_prefix):-len(call_suffix)]
    if not ui_name or not ui_name.replace("_", "").isalnum():
        raise SystemExit(f"Unexpected toolbar UI variable for Undo/Redo: {ui_name!r}")

    replacement = "\n".join((
        f"{indent}// {MARKER}",
        f"{indent}let x = history_buttons(app, {ui_name}, &p, x, cy);",
        original_line,
    ))
    source = source.replace(original_line, replacement, 1)

    helper_anchor = "/// The brand mark (About) and the Home button; returns the x after them.\n"
    helper = r'''/// AM-style touch controls for the project's native edit history.
/// Continuous timeline gestures are already coalesced by the engine into one history step.
fn history_buttons(app: &mut EffectcraftApp, ui: &mut egui::Ui, p: &egui::Painter, mut x: f32, cy: f32) -> f32 {
    let t = app.tokens;
    let undo_enabled = !app.session.history.undo.is_empty();
    let undo_rect = Rect::from_min_size(pos2(x, cy - 12.0), vec2(24.0, 24.0));
    let undo = ui
        .add_enabled_ui(undo_enabled, |ui| {
            widgets::icon_button(ui, undo_rect, Icon::Undo, false, &t, egui::Id::unique("header-undo"))
        })
        .inner
        .on_hover_text(tr("Undo"));
    app.auto.add_response("header.undo", &undo, "撤回上一步剪辑操作");
    if undo.clicked()
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "edit.undo", json!({}))
    {
        app.ui.status = error;
    }
    x += 25.0;

    let redo_enabled = !app.session.history.redo.is_empty();
    let redo_rect = Rect::from_min_size(pos2(x, cy - 12.0), vec2(24.0, 24.0));
    let redo = ui
        .add_enabled_ui(redo_enabled, |ui| {
            widgets::icon_button(ui, redo_rect, Icon::Redo, false, &t, egui::Id::unique("header-redo"))
        })
        .inner
        .on_hover_text(tr("Redo"));
    app.auto.add_response("header.redo", &redo, "重做上一步剪辑操作");
    if redo.clicked()
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "edit.redo", json!({}))
    {
        app.ui.status = error;
    }
    x += 29.0;
    p.line_segment([pos2(x, cy - 9.0), pos2(x, cy + 9.0)], Stroke::new(1.0, t.separator));
    x + 6.0
}

'''
    source = replace_once(source, helper_anchor, helper + helper_anchor, "insert the Undo / Redo toolbar handler")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    patch_icons(root)
    patch_header(root)

    icons = (root / "crates/ui-egui/src/icons.rs").read_text(encoding="utf-8")
    header = (root / "crates/ui-egui/src/header.rs").read_text(encoding="utf-8")
    required = (
        "Icon::Undo", "Icon::Redo", '"edit.undo"', '"edit.redo"',
        "!app.session.history.undo.is_empty()", "!app.session.history.redo.is_empty()",
        "EFFECTCRAFT_ANDROID_AM_UNDO_REDO_BUTTONS_V1",
    )
    if not all(token in header for token in required) or "Undo =>" not in icons or "Redo =>" not in icons:
        raise SystemExit("AM-style Undo / Redo controls failed their source verification.")
    print("Installed AM-style touch Undo / Redo controls backed by the native project history.")
    print("Undo and Redo are disabled when their respective history queues are empty.")


if __name__ == "__main__":
    main()
