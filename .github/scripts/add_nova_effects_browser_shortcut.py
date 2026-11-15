#!/usr/bin/env python3
"""Expose mobile compatibility effects and verify safe WASM failure behavior."""
from __future__ import annotations

import os
import re
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_NOVA_STYLE_EFFECTS_SHORTCUT_V1"
CATEGORY = "Nova 风格兼容"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {source.count(old)}")
    return source.replace(old, new, 1)


def group_compatibility_effects(path: Path, minimum: int) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing compatibility-effect source: {path}")
    source = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'("category":")[^"]+(")',
        lambda match: match.group(1) + CATEGORY + match.group(2),
        source,
    )
    if count < minimum:
        raise SystemExit(f"{path.name}: expected at least {minimum} manifests, found {count}")
    path.write_text(updated, encoding="utf-8")
    print(f"Grouped {count} mobile compatibility effects under {CATEGORY!r}.")


def verify_wasm_safety(root: Path) -> None:
    wasm = (root / "crates/plugin/src/wasm.rs").read_text(encoding="utf-8")
    plugin = (root / "crates/plugin/src/lib.rs").read_text(encoding="utf-8")
    checks = (
        ("fuel metering", "config.consume_fuel(true)"),
        ("per-frame fuel budget", "FUEL_BASE + FUEL_PER_PIXEL * n as u64"),
        ("bounded linear memory", "memory_size(MAX_MEMORY)"),
        ("no host imports", "plug-ins can't import anything"),
        ("trapped render converted to an error", "ec_render trapped:"),
        ("success-only frame copyback", "Ok(0) => {"),
    )
    for label, token in checks:
        if token not in wasm:
            raise SystemExit(f"Effect safety check failed: missing {label} guard")
    if "fuel limit" not in plugin or "can't escape its sandbox" not in plugin:
        raise SystemExit("Effect safety check failed: WASM sandbox contract changed")
    success = wasm.find("Ok(0) => {")
    copyback = wasm.find("for (px, b) in frame.pixels.iter_mut()", success)
    error_branch = wasm.find("Ok(code) => Err", success)
    if success < 0 or copyback < success or error_branch < copyback:
        raise SystemExit("Effect safety check failed: frame copyback is not success-only")
    print("Verified WASM fuel/memory limits; failed effects cannot copy partial pixels into the frame.")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    header_path = root / "crates/ui-egui/src/header.rs"
    header = header_path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_RESPONSIVE_HEADER_SCROLL_V1" not in header:
        raise SystemExit("Run make_header_scrollable.py before adding the Effects shortcut.")

    if MARKER not in header:
        call_anchor = """            let x = puppet_quick_button(app, scroll_ui, x, cy);
            let x = tool_slots(app, scroll_ui, &p, x, cy);"""
        call_replacement = """            let x = puppet_quick_button(app, scroll_ui, x, cy);
            let x = effects_library_button(app, scroll_ui, &p, x, cy);
            let x = tool_slots(app, scroll_ui, &p, x, cy);"""
        header = replace_once(header, call_anchor, call_replacement, "top-left Effects button call")

        helper_anchor = "/// The brand mark (About) and the Home button; returns the x after them."
        helper = r'''
// EFFECTCRAFT_ANDROID_NOVA_STYLE_EFFECTS_SHORTCUT_V1
/// One tap opens the existing Effects & Presets browser from the mobile toolbar.
fn effects_library_button(
    app: &mut EffectcraftApp,
    ui: &mut egui::Ui,
    p: &egui::Painter,
    x: f32,
    cy: f32,
) -> f32 {
    let t = app.tokens;
    let r = Rect::from_min_size(pos2(x + 2.0, cy - 12.0), vec2(44.0, 24.0));
    let response = ui.interact(
        r,
        egui::Id::new("effectcraft-mobile-effects-library"),
        Sense::click(),
    );
    p.rect_filled(r, 5.0, if response.hovered() { t.hover } else { t.header_bg });
    p.rect_stroke(r, 5.0, Stroke::new(1.0, t.separator), StrokeKind::Inside);
    p.text(r.center(), Align2::CENTER_CENTER, "效果", Tokens::semibold(12.0), t.text);
    app.auto.add("header.effectsLibrary", r, "Effects & Presets");
    if response.clicked()
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "effect.manage", json!({}))
    {
        app.ui.status = error;
    }
    r.max.x + 8.0
}

'''
        header = replace_once(header, helper_anchor, helper + helper_anchor, "Effects shortcut helper")
        if header.count("effects_library_button(app, scroll_ui") != 1:
            raise SystemExit("Effects shortcut must appear exactly once.")
        header_path.write_text(header, encoding="utf-8")
        print("Added the top-left 效果 button to the horizontally scrollable Android toolbar.")
    else:
        print("Top-left Effects shortcut already exists.")

    scripts = Path(__file__).resolve().parent
    group_compatibility_effects(scripts / "sapphire_compat_pack.rs", 11)
    group_compatibility_effects(scripts / "looks_compat_pack.rs", 1)
    verify_wasm_safety(root)
    print("Nova-style compatibility effects and safe WASM failure checks are ready.")


if __name__ == "__main__":
    main()
