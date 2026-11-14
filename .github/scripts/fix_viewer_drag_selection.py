#!/usr/bin/env python3
"""Synchronize viewer layer clicks with Project-panel file selection and keyframing."""

from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_PROJECT_FILE_VIEWER_SELECTION_V2"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", ".")).resolve()
    viewer = root / "crates/ui-egui/src/panels/viewer.rs"
    if not viewer.is_file():
        raise SystemExit(f"EffectCraft viewer source not found: {viewer}")

    source = viewer.read_text(encoding="utf-8")
    if MARKER in source:
        print("Viewer file/layer selection synchronization is already present.")
        return

    # A drag may move a layer only after a completed click has selected it. The first
    # press-drag on an unselected layer is deliberately not converted into a move or marquee.
    drag_old = "                } else if let Some(l) = pick(app, ectx, cpt, mods.shift) {"
    drag_new = """                } else if layer_at(ectx, cpt).is_some_and(|layer| {
                    !app.session.state.selected_layers.contains(&layer.id)
                }) {
                    // Require a completed click to select a layer before a later drag moves it.
                    None
                } else if let Some(l) = pick_selected_drag_target(app, ectx, cpt) {"""
    source = replace_once(source, drag_old, drag_new, "Selection-tool first-drag guard")

    # A normal viewer click selects exactly the visible topmost layer, its Project-panel
    # source item and the layer itself. Shift-click retains the native toggle behavior.
    click_old = """            _ => {
                if pick(app, ectx, cpt, mods.shift).is_none() {"""
    click_new = """            _ => {
                if pick_click_target(app, ectx, cpt, mods.shift).is_none() && !mods.shift {"""
    source = replace_once(source, click_old, click_new, "Viewer click/file selection")

    # Clicking away from an active free-transform box still follows the same layer/file
    # selection rules; a blank click clears both selection models.
    ft_old = """            Tool::Selection if ft.is_some() && ft.as_ref().and_then(|f| ov::begin_ft_drag(f, pos, &map)).is_none() => {
                // Clicking away from the free-transform box ends it.
                ov::end_free_transform(&ctx);
            }"""
    ft_new = """            Tool::Selection if ft.is_some() && ft.as_ref().and_then(|f| ov::begin_ft_drag(f, pos, &map)).is_none() => {
                // Clicking away from the free-transform box ends it and selects the clicked target.
                ov::end_free_transform(&ctx);
                if pick_click_target(app, ectx, cpt, mods.shift).is_none() && !mods.shift {
                    let _ = app.session.execute("edit.deselectAll", json!({}));
                    app.session.state.project_selection.clear();
                }
            }"""
    source = replace_once(source, ft_old, ft_new, "Free-transform click-away selection")

    # The special Roto Brush selection path also synchronizes the Project panel.
    roto_old = """                if pick(app, ectx, cpt, mods.shift).is_none() {
                    let _ = app.session.execute("edit.deselectAll", json!({}));
                }
                app.ui.status = crate::i18n::tr(ROTO_HINT).to_string();"""
    roto_new = """                if pick_click_target(app, ectx, cpt, mods.shift).is_none() && !mods.shift {
                    let _ = app.session.execute("edit.deselectAll", json!({}));
                    app.session.state.project_selection.clear();
                }
                app.ui.status = crate::i18n::tr(ROTO_HINT).to_string();"""
    source = replace_once(source, roto_old, roto_new, "Roto Brush viewer selection")

    # A click on empty canvas clears both the timeline layer selection and the Project-panel
    # file selection; edit.deselectAll alone does not clear project_selection in the engine.
    deselect_old = """                if pick_click_target(app, ectx, cpt, mods.shift).is_none() && !mods.shift {
                    let _ = app.session.execute("edit.deselectAll", json!({}));
                } else if !mods.shift"""
    deselect_new = """                if pick_click_target(app, ectx, cpt, mods.shift).is_none() && !mods.shift {
                    let _ = app.session.execute("edit.deselectAll", json!({}));
                    app.session.state.project_selection.clear();
                } else if !mods.shift"""
    source = replace_once(source, deselect_old, deselect_new, "Blank-canvas full deselection")

    helper_marker = "fn edge_pan(app: &mut EffectcraftApp"
    helper = r'''/// Keep Project-panel file selection synchronized with the selected viewer layers.
fn sync_project_selection_from_viewer(app: &mut EffectcraftApp) {
    let selected_layers = app.session.state.selected_layers.clone();
    let items = if let Some(comp) = app.session.active_comp() {
        let mut items = Vec::new();
        for layer_id in selected_layers {
            if let Some(item) = comp.layer(layer_id).and_then(|layer| layer.source.item())
                && !items.contains(&item)
            {
                items.push(item);
            }
        }
        items
    } else {
        Vec::new()
    };
    app.session.state.project_selection = items;
}

/// A completed click selects the topmost visible layer and its source file.
/// Plain click makes it the sole selection; Shift-click preserves native toggle semantics.
fn pick_click_target(
    app: &mut EffectcraftApp,
    ectx: &EvalCtx,
    cpt: [f64; 2],
    toggle: bool,
) -> Option<LayerId> {
    let hit = if toggle {
        pick(app, ectx, cpt, true)?
    } else {
        let hit = layer_at(ectx, cpt)?.id;
        let already_only = app.session.state.selected_layers.len() == 1
            && app.session.state.selected_layers.first() == Some(&hit);
        if !already_only {
            if let Err(error) = app.session.execute("layer.select", json!({"layers": [hit.0]})) {
                app.ui.status = error.to_string();
                return None;
            }
        }
        hit
    };
    sync_project_selection_from_viewer(app);
    Some(hit)
}

/// A move gesture is available only when the topmost layer was selected before the drag began.
fn pick_selected_drag_target(
    app: &mut EffectcraftApp,
    ectx: &EvalCtx,
    cpt: [f64; 2],
) -> Option<LayerId> {
    let hit = layer_at(ectx, cpt)?.id;
    if !app.session.state.selected_layers.contains(&hit) {
        return None;
    }
    sync_project_selection_from_viewer(app);
    Some(hit)
}

'''
    if source.count(helper_marker) != 1:
        raise SystemExit("Could not locate the viewer helper insertion point.")
    source = source.replace(helper_marker, helper + helper_marker, 1)

    source = source.replace(
        "/// A move gesture is available only when the topmost layer was selected before the drag began.",
        f"/// {MARKER}\n/// A move gesture is available only when the topmost layer was selected before the drag began.",
        1,
    )
    viewer.write_text(source, encoding="utf-8")
    print("Viewer clicks now select the matching Project-panel file and timeline layer.")
    print("Keyframing can target the selected file's matching layer.")
    print("Blank clicks clear both selections; moving requires a prior selection click.")


if __name__ == "__main__":
    main()
