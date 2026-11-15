#!/usr/bin/env python3
"""Resolve curve presets from the exact playhead time shown by the Android Timeline."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_SOURCE_V3"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Timeline curve picker already uses the displayed playhead time.")
        return

    source = replace_once(
        source,
        "fn android_playhead_curve_segment(app: &EffectcraftApp) -> Option<AndroidCurveSegment> {",
        "fn android_playhead_curve_segment(app: &EffectcraftApp, playhead: Tick) -> Option<AndroidCurveSegment> {",
        "use the visible timeline playhead in the curve resolver",
    )
    source = replace_once(
        source,
        "    let playhead = app.session.time_of(comp_id);\n",
        "",
        "remove the independently sampled composition time",
    )

    # Keyframe selection itself can identify the owning layer even if the layer row
    # is not selected. Include those layer IDs before the resolver's empty-target check.
    layer_anchor = """    for (layer_id, _) in &app.session.state.selected_props {
        if !layer_ids.contains(layer_id) {
            layer_ids.push(*layer_id);
        }
    }
    if layer_ids.is_empty() {"""
    layer_replacement = """    for (layer_id, _) in &app.session.state.selected_props {
        if !layer_ids.contains(layer_id) {
            layer_ids.push(*layer_id);
        }
    }
    for key in &app.session.state.selected_keys {
        if !layer_ids.contains(&key.layer) {
            layer_ids.push(key.layer);
        }
    }
    if layer_ids.is_empty() {"""
    source = replace_once(source, layer_anchor, layer_replacement, "selected keyframe owning-layer resolution")

    # If the user selected keyframes rather than the property row, use those keyframes
    # to identify the property before searching all properties on the selected layer.
    old_selected = """    let mut selected_segments = Vec::new();
    for (layer_id, prop_uid) in &app.session.state.selected_props {
        let Some(layer) = comp.layer(*layer_id) else { continue };
        let Some(prop) = layer.props.find(*prop_uid) else { continue };
        android_collect_curve_property(prop, layer, comp_id.0, playhead, &mut selected_segments);
    }
"""
    new_selected = """    let mut selected_property_refs = app.session.state.selected_props.clone();
    for key in &app.session.state.selected_keys {
        let key_ref = (key.layer, key.prop);
        if !selected_property_refs.contains(&key_ref) {
            selected_property_refs.push(key_ref);
        }
    }
    let mut selected_segments = Vec::new();
    for (layer_id, prop_uid) in &selected_property_refs {
        let Some(layer) = comp.layer(*layer_id) else { continue };
        let Some(prop) = layer.props.find(*prop_uid) else { continue };
        android_collect_curve_property(prop, layer, comp_id.0, playhead, &mut selected_segments);
    }
"""
    source = replace_once(source, old_selected, new_selected, "selected keyframe property resolution")

    source = replace_once(
        source,
        "fn android_curve_quick_access(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {",
        "fn android_curve_quick_access(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect, playhead: Tick) {",
        "pass the visible playhead into the curve picker",
    )
    source = replace_once(
        source,
        "android_playhead_curve_segment(app)",
        "android_playhead_curve_segment(app, playhead)",
        "use the visible playhead for curve lookup",
    )

    # The Timeline layout stores the same Tick used for the visible blue CTI. Pass it
    # through directly rather than sampling session time again after drawing the panel.
    source = replace_once(
        source,
        "    android_curve_quick_access(app, ui, rect);\n",
        "    android_curve_quick_access(app, ui, rect, g.tl.time);\n",
        "use the Timeline's displayed current-time indicator",
    )

    marker_anchor = "const EXPR_MAX_LINES: usize = 100;\n"
    source = replace_once(
        source,
        marker_anchor,
        marker_anchor + "// " + MARKER + "\n",
        "curve playhead source marker",
    )
    path.write_text(source, encoding="utf-8")

    final = path.read_text(encoding="utf-8")
    required = (
        MARKER,
        "android_playhead_curve_segment(app, playhead)",
        "android_curve_quick_access(app, ui, rect, g.tl.time)",
        "app.session.state.selected_keys",
        "layer_ids.push(key.layer)",
    )
    missing = [item for item in required if item not in final]
    if missing:
        raise SystemExit("Curve playhead fix failed verification: " + "; ".join(missing))
    print("Curve presets now resolve from the visible Timeline CTI and selected keyframes/properties.")


if __name__ == "__main__":
    main()
