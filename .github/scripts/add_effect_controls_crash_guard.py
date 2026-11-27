#!/usr/bin/env python3
"""Keep a broken Effect Controls UI from taking down the Android editor."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_EFFECT_CONTROLS_GUARD_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    panels_path = root / "crates/ui-egui/src/panels.rs"
    source = panels_path.read_text(encoding="utf-8")

    if MARKER not in source:
        source = replace_once(
            source,
            "use egui::Rect;\n",
            "use egui::Rect;\nuse std::panic::{catch_unwind, AssertUnwindSafe};\n",
            "Effect Controls panic-guard import",
        )
        old = "        PanelKind::EffectControls => effect_controls::show(app, ui, rect),"
        new = '''        PanelKind::EffectControls => {
            // EFFECTCRAFT_ANDROID_EFFECT_CONTROLS_GUARD_V1
            // Applying an effect opens this panel immediately. A faulty custom control/editor
            // must not unwind through eframe and close the whole Android application.
            let shown = catch_unwind(AssertUnwindSafe(|| effect_controls::show(app, ui, rect)));
            if let Err(payload) = shown {
                let detail = payload
                    .downcast_ref::<String>()
                    .map(String::as_str)
                    .or_else(|| payload.downcast_ref::<&str>().copied())
                    .unwrap_or("unknown panic");
                log::error!("Effect Controls panel failed; keeping the effect and returning to Effects & Presets: {detail}");
                app.ui.status = "效果控件显示出错；已保留刚添加的效果，并返回效果列表。".to_string();
                app.show_panel(PanelKind::EffectsPresets);
            }
        },'''
        source = replace_once(source, old, new, "Effect Controls guarded dispatch")
        panels_path.write_text(source, encoding="utf-8")
        print("Added a panic boundary around the Effect Controls panel; a bad effect editor falls back to Effects & Presets.")
    else:
        print("Effect Controls panel crash guard is already installed.")

    # Parameter scrubbing bug: egui Response::drag_delta is cumulative from drag start.
    # Adding that cumulative value to the already-updated project value every frame causes
    # repeated overshoot and a burst of expensive preview refreshes on long touch drags.
    widgets_path = root / "crates/ui-egui/src/widgets.rs"
    widgets = widgets_path.read_text(encoding="utf-8")
    scrub_marker = "EFFECTCRAFT_POINTER_DELTA_SCRUB_V1"
    old_scrub = """    if resp.dragged() {
        let dx = resp.drag_delta().x as f64;
        let mult = ui.input(|i| {
            if i.modifiers.shift {
                10.0
            } else if i.modifiers.command && !proportional_scrub(i.modifiers) {
                0.1
            } else {
                1.0
            }
        });
        let nv = (value + dx * speed * mult).clamp(range.0, range.1);
        if (nv - value).abs() > f64::EPSILON {
            out = Some(nv);
        }
    }"""
    new_scrub = """    if resp.dragged() {
        // EFFECTCRAFT_POINTER_DELTA_SCRUB_V1: use only this frame's motion, not the
        // cumulative distance since drag start. This keeps repeated touch updates linear.
        let dx = ui.input(|i| i.pointer.delta().x as f64);
        let mult = ui.input(|i| {
            if i.modifiers.shift {
                10.0
            } else if i.modifiers.command && !proportional_scrub(i.modifiers) {
                0.1
            } else {
                1.0
            }
        });
        let valid_range = range.0.is_finite() && range.1.is_finite() && range.0 <= range.1;
        let delta = dx * speed * mult;
        let candidate = value + delta;
        if valid_range && dx.is_finite() && speed.is_finite() && value.is_finite()
            && delta.is_finite() && candidate.is_finite()
        {
            let nv = candidate.clamp(range.0, range.1);
            if (nv - value).abs() > f64::EPSILON {
                out = Some(nv);
            }
        }
    }"""
    if scrub_marker not in widgets:
        widgets = replace_once(widgets, old_scrub, new_scrub, "parameter drag delta and finite-value guard")
        widgets_path.write_text(widgets, encoding="utf-8")
        print("Fixed cumulative parameter scrub deltas and rejected non-finite parameter updates.")
    elif "let dx = ui.input(|i| i.pointer.delta().x as f64);" not in widgets:
        raise SystemExit("Parameter scrub marker exists but its incremental pointer-delta implementation is missing.")
    else:
        print("Incremental parameter scrub handling is already installed.")

    # The viewer also has an independent frame-level panic guard that retries on CPU.
    # Verify it remains present so effect renderer failures do not unwind through the UI.
    frames_path = root / "crates/ui-egui/src/frames.rs"
    frames = frames_path.read_text(encoding="utf-8")
    required = (
        "fn render_guarded(&self, job: &Job) -> Option<FrameImage>",
        "std::panic::catch_unwind(std::panic::AssertUnwindSafe",
        "job.src.gpu.as_ref().and_then(|_| attempt(false))",
    )
    missing = [token for token in required if token not in frames]
    if missing:
        raise SystemExit("The preview frame CPU fallback guard is missing: " + "; ".join(missing))
    print("Verified preview rendering retries on CPU if an effect/GPU frame panics.")
    print("Effect Controls failures and preview-render failures are now isolated from the app UI.")


if __name__ == "__main__":
    main()
