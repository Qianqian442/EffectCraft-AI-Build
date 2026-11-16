#!/usr/bin/env python3
"""Add a persistent AM-inspired portrait workspace without changing project data or I/O."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_AM_PORTRAIT_WORKSPACE_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    path = root / "crates/ui-egui/src/dock.rs"
    if not path.is_file():
        raise SystemExit(f"EffectCraft dock source not found: {path}")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("AM-inspired portrait workspace already installed.")
        return

    source = replace_once(
        source,
        "pub const WORKSPACES: &[&str] = &[\n",
        "pub const WORKSPACES: &[&str] = &[\n    // EFFECTCRAFT_AM_PORTRAIT_WORKSPACE_V1\n    \"AM\",\n",
        "register AM workspace in persistent workspace selector",
    )
    source = replace_once(
        source,
        "    match name {\n        \"Animation\" =>",
        """    match name {
        // AM-inspired portrait editing: composition preview on top, a full-width
        // touch-friendly timeline below, and the existing Effect Controls / Effects
        // Presets panels in a lower tab group. All panels still edit the same project.
        "AM" => vsplit(
            Ratio(0.46),
            tabs(&[Composition, Layer], 0),
            vsplit(
                Ratio(0.62),
                tabs(&[Timeline], 0),
                tabs(&[EffectControls, EffectsPresets, Properties, Project], 1),
            ),
        ),
        "Animation" =>""",
        "add AM portrait workspace dock tree",
    )
    path.write_text(source, encoding="utf-8")
    print("Installed AM workspace: portrait-oriented panel stack, native Timeline, and existing Effect Controls/Effects Presets.")


if __name__ == "__main__":
    main()
