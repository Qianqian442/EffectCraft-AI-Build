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
