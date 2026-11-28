#!/usr/bin/env python3
"""Add an optional purple appearance palette without changing any widget geometry or actions."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source anchor, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    theme_path = root / "crates/ui-egui/src/theme.rs"
    choices_path = root / "crates/engine/src/settings/prefs/choices.rs"
    theme = theme_path.read_text(encoding="utf-8")
    choices = choices_path.read_text(encoding="utf-8")

    marker = "EFFECTCRAFT_PURPLE_THEME_V1"
    if marker not in theme:
        theme = replace_once(
            theme,
            "    Darker,\n    Light,\n",
            "    Darker,\n    /// A dark graphite palette with purple accents.\n    Purple,\n    Light,\n",
            "Purple ThemeKind",
        )
        theme = replace_once(
            theme,
            '            "darker" | "darkest" => Some(ThemeKind::Darker),\n            "light" => Some(ThemeKind::Light),',
            '            "darker" | "darkest" => Some(ThemeKind::Darker),\n            "purple" => Some(ThemeKind::Purple),\n            "light" => Some(ThemeKind::Light),',
            "Purple theme name parser",
        )
        theme = replace_once(
            theme,
            '            ThemeKind::Darker => "darker",\n            ThemeKind::Light => "light",',
            '            ThemeKind::Darker => "darker",\n            ThemeKind::Purple => "purple",\n            ThemeKind::Light => "light",',
            "Purple theme name",
        )
        palette_anchor = """            ThemeKind::Light => Tokens {
                app_bg: Color32::from_rgb(0xb4, 0xb4, 0xb4),"""
        palette = """            // EFFECTCRAFT_PURPLE_THEME_V1: colours only; every layout metric and action is inherited.
            ThemeKind::Purple => Tokens {
                app_bg: Color32::from_rgb(0x14, 0x10, 0x1b),
                header_bg: Color32::from_rgb(0x22, 0x19, 0x2d),
                panel_bg: Color32::from_rgb(0x29, 0x20, 0x35),
                focus: Color32::from_rgb(0x9b, 0x6b, 0xf5),
                accent: Color32::from_rgb(0x9b, 0x6b, 0xf5),
                accent_hover: Color32::from_rgb(0xb4, 0x8c, 0xfa),
                hover: Color32::from_rgb(0x38, 0x2b, 0x47),
                pressed: Color32::from_rgb(0x49, 0x36, 0x5c),
                field_bg: Color32::from_rgb(0x1d, 0x17, 0x26),
                field_border: Color32::from_rgb(0x51, 0x41, 0x67),
                separator: Color32::from_rgb(0x44, 0x36, 0x4f),
                row: Color32::from_rgb(0x29, 0x21, 0x32),
                row_alt: Color32::from_rgb(0x2d, 0x25, 0x37),
                row_selected: Color32::from_rgb(0x46, 0x30, 0x5e),
                hot_text: Color32::from_rgb(0xc0, 0x9e, 0xff),
                tl_bg: Color32::from_rgb(0x1a, 0x14, 0x23),
                tl_ruler_bg: Color32::from_rgb(0x2a, 0x21, 0x36),
                tl_ruler_tick: Color32::from_rgb(0x7b, 0x6a, 0x8a),
                tl_ruler_text: Color32::from_rgb(0xc7, 0xb5, 0xda),
                cti: Color32::from_rgb(0xb4, 0x8c, 0xfa),
                work_area: Color32::from_rgb(0x5a, 0x47, 0x73),
                keyframe_selected: Color32::from_rgb(0xb4, 0x8c, 0xfa),
                timecode: Color32::from_rgb(0xc0, 0x9e, 0xff),
                fx_header: Color32::from_rgb(0x34, 0x28, 0x3f),
                fx_header_active: Color32::from_rgb(0x4b, 0x35, 0x70),
                tl_graph_selected: Color32::from_rgb(0x37, 0x2b, 0x45),
                switch_well: Color32::from_rgb(0x1e, 0x18, 0x28),
                tl_nav_bar: Color32::from_rgb(0x71, 0x5a, 0x90),
                tl_work_area_bar: Color32::from_rgb(0x84, 0x6d, 0xa6),
                expr_bg: Color32::from_rgb(0x1f, 0x17, 0x28),
                ..dark
            },
            ThemeKind::Light => Tokens {
                app_bg: Color32::from_rgb(0xb4, 0xb4, 0xb4),"""
        theme = replace_once(theme, palette_anchor, palette, "Purple token palette")

    choices_marker = "EFFECTCRAFT_PURPLE_THEME_CHOICE_V1"
    if choices_marker not in choices:
        choices = replace_once(
            choices,
            'pub const DARK_THEMES: &[(&str, &str)] = &[("Dark", "dark"), ("Darker", "darker")];',
            '// EFFECTCRAFT_PURPLE_THEME_CHOICE_V1\npub const DARK_THEMES: &[(&str, &str)] = &[(\"Dark\", \"dark\"), (\"Darker\", \"darker\"), (\"紫色\", \"purple\")];',
            "Purple dark-theme choice",
        )
        choices = replace_once(
            choices,
            'pub const THEMES: &[(&str, &str)] = &[("Dark", "dark"), ("Darker", "darker"), ("Light", "light")];',
            'pub const THEMES: &[(&str, &str)] = &[("Dark", "dark"), ("Darker", "darker"), ("紫色", "purple"), ("Light", "light")];',
            "Purple legacy-theme choice",
        )

    if "ThemeKind::Purple => \"purple\"" not in theme or "ThemeKind::Purple => Tokens" not in theme:
        raise SystemExit("Purple theme palette or persistent theme name is incomplete.")
    if '("紫色", "purple")' not in choices:
        raise SystemExit("Purple theme is not selectable in Settings ▸ Appearance.")

    theme_path.write_text(theme, encoding="utf-8")
    choices_path.write_text(choices, encoding="utf-8")
    print("Added the optional purple theme; existing widget positions, sizes, hit targets and commands are unchanged.")


if __name__ == "__main__":
    main()
