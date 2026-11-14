#!/usr/bin/env python3
"""Make viewer click-drag select the visible layer directly under the pointer."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", ".")).resolve()
    viewer = root / "crates/ui-egui/src/panels/viewer.rs"
    if not viewer.is_file():
        raise SystemExit(f"EffectCraft viewer source not found: {viewer}")

    source = viewer.read_text(encoding="utf-8")
    drag_old = "                } else if let Some(l) = pick(app, ectx, cpt, mods.shift) {"
    drag_new = "                } else if let Some(l) = pick_drag_target(app, ectx, cpt, mods.shift) {"
    click_old = """            _ => {
                if pick(app, ectx, cpt, mods.shift).is_none() {"""
    click_new = """            _ => {
                if pick_drag_target(app, ectx, cpt, mods.shift).is_none() {"""

    if drag_new not in source:
        count = source.count(drag_old)
        if count != 1:
            raise SystemExit(
                "Expected exactly one Selection-tool drag pick site in viewer.rs; "
                f"found {count}. Refusing to patch an unknown source layout."
            )
        source = source.replace(drag_old, drag_new, 1)

    if click_new not in source:
        count = source.count(click_old)
        if count != 1:
            raise SystemExit(
                "Expected exactly one default viewer click selection site; "
                f"found {count}. Refusing to patch an unknown source layout."
            )
        source = source.replace(click_old, click_new, 1)

    helper_marker = "fn edge_pan(app: &mut EffectcraftApp"
    helper = '''/// Select the actual topmost visible layer under a viewer click/drag.
/// Unlike the general picker, this does not prefer a lower already-selected layer
/// when it overlaps the visible layer directly under the pointer. Existing multi-selection
/// is preserved when the grabbed layer is already part of it.
fn pick_drag_target(
    app: &mut EffectcraftApp,
    ectx: &EvalCtx,
    cpt: [f64; 2],
    toggle: bool,
) -> Option<LayerId> {
    if toggle {
        return pick(app, ectx, cpt, true);
    }
    let hit = layer_at(ectx, cpt)?.id;
    if !app.session.state.selected_layers.contains(&hit) {
        if let Err(error) = app.session.execute("layer.select", json!({"layers": [hit.0]})) {
            app.ui.status = error.to_string();
            return None;
        }
    }
    Some(hit)
}

'''
    if "fn pick_drag_target(" not in source:
        if source.count(helper_marker) != 1:
            raise SystemExit("Could not locate the viewer drag helper insertion point.")
        source = source.replace(helper_marker, helper + helper_marker, 1)

    viewer.write_text(source, encoding="utf-8")
    print("Patched viewer click and drag selection to target the visible topmost layer.")


if __name__ == "__main__":
    main()
