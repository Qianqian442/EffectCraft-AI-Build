#!/usr/bin/env python3
"""Add touch-sized Undo/Redo controls to the Android top toolbar."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_UNDO_REDO_BUTTONS_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Android Undo/Redo toolbar controls are already installed.")
        return

    old_show = """    let x = snapping_toggle(app, ui, &p, x, cy);
    right_side(app, ui, &p, rect, x, cy);
}"""
    new_show = """    let x = snapping_toggle(app, ui, &p, x, cy);
    let x = android_undo_redo_buttons(app, ui, &p, x + 6.0, cy);
    right_side(app, ui, &p, rect, x, cy);
}"""
    source = replace_once(source, old_show, new_show, "Undo/Redo toolbar insertion")

    anchor = "/// Right side: community buttons, appearance and workspaces; `left` is where the tools end.\n"
    helper = r'''
// EFFECTCRAFT_ANDROID_UNDO_REDO_BUTTONS_V1
/// Direct, touch-sized access to the engine's existing branching edit history.
fn android_undo_redo_buttons(
    app: &mut EffectcraftApp,
    ui: &mut egui::Ui,
    p: &egui::Painter,
    mut x: f32,
    cy: f32,
) -> f32 {
    let ctx = ui.ctx().clone();
    let t = app.tokens;
    let actions = [
        ("header.undo", "撤销", "edit.undo", !app.session.history.undo.is_empty()),
        ("header.redo", "重做", "edit.redo", !app.session.history.redo.is_empty()),
    ];
    for (id, label, command, enabled) in actions {
        let rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(38.0, 26.0));
        let response = ui.interact(
            rect,
            egui::Id::new(id),
            if enabled { Sense::click() } else { Sense::hover() },
        );
        let fill = if !enabled {
            t.panel_bg.gamma_multiply(0.55)
        } else if response.hovered() {
            t.accent.gamma_multiply(0.25)
        } else {
            t.panel_bg
        };
        p.rect_filled(rect, 5.0, fill);
        p.rect_stroke(rect, 5.0, Stroke::new(1.0, t.separator), StrokeKind::Inside);
        p.text(
            rect.center(),
            Align2::CENTER_CENTER,
            label,
            Tokens::semibold(10.5),
            if enabled { t.text } else { t.text_dim },
        );
        app.auto.add(id, rect, label);
        if response.clicked() {
            if let Err(error) = crate::menus::invoke(app, &ctx, command, json!({})) {
                app.ui.status = error;
            }
        }
        x += 42.0;
    }
    x + 2.0
}

'''
    source = replace_once(source, anchor, helper + anchor, "Undo/Redo toolbar helper")
    path.write_text(source, encoding="utf-8")

    final = path.read_text(encoding="utf-8")
    if MARKER not in final or 'crate::menus::invoke(app, &ctx, command, json!({}))' not in final:
        raise SystemExit("Undo/Redo controls did not connect to the engine history commands")
    print("Installed touch-sized Undo and Redo toolbar controls backed by edit.undo and edit.redo.")
    print("Buttons disable automatically when the corresponding history stack is empty.")


if __name__ == "__main__":
    main()
