#!/usr/bin/env python3
"""Make the bundled RSMB-style effect easier to control on Android touch screens."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_RSMB_TOUCH_CONTROLS_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    path = root / "crates/ui-egui/src/panels/effect_controls/rows.rs"
    if not root.is_dir() or not path.is_file():
        raise SystemExit("EFFECTCRAFT_DIR must point to EffectCraft source with effect_controls/rows.rs")

    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("RSMB touch-friendly Effect Controls are already patched.")
        return

    # Give the slider disclosure/twirl a usable finger target without moving it over the stopwatch.
    source = replace_once(
        source,
        'let tw = Rect::from_center_size(pos2(swr.min.x - 9.0, cy), vec2(10.0, 10.0));',
        'let tw = Rect::from_center_size(pos2(swr.min.x - 9.0, cy), vec2(18.0, 18.0));',
        "Effect Controls slider touch target",
    )

    old = '''            Node::Prop(pr) => {
                if matches!(pr.ui, ParamUi::Hidden) || pr.three_d_only && !layer.is_3d() || !fx.shown(layer, ectx, &pr.match_id) {
'''
    new = '''            Node::Prop(pr) => {
                // EFFECTCRAFT_ANDROID_RSMB_TOUCH_CONTROLS_V1
                // On a touch device, expand this compatibility effect's sliders once when first shown.
                // Users can then drag the full-width tracks instead of trying to scrub tiny number fields.
                if ui.input(|i| i.has_touch_screen())
                    && fx.effect == "org.effectcraft.sapphire.compat.rsmb-style-motion-blur"
                    && matches!(pr.ui, ParamUi::Slider { .. })
                {
                    let opened_id = egui::Id::new(("ec-rsmb-touch-open-once", pr.uid));
                    let was_initialized = ui.ctx().data(|d| d.get_temp::<bool>(opened_id).unwrap_or(false));
                    if !was_initialized {
                        app.ui.fx_slider_open.insert(pr.uid);
                        ui.ctx().data_mut(|d| d.insert_temp(opened_id, true));
                    }
                }
                if matches!(pr.ui, ParamUi::Hidden) || pr.three_d_only && !layer.is_3d() || !fx.shown(layer, ectx, &pr.match_id) {
'''
    source = replace_once(source, old, new, "RSMB touch slider auto-expansion")

    if MARKER not in source or 'vec2(18.0, 18.0)' not in source or 'ec-rsmb-touch-open-once' not in source:
        raise SystemExit("RSMB touch-control integration verification failed")

    path.write_text(source, encoding="utf-8")
    print("Expanded the slider touch target and auto-opened RSMB compatibility sliders once on touch devices.")


if __name__ == "__main__":
    main()
