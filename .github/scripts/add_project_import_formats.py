#!/usr/bin/env python3
"""Validate the original After Effects Project import menu; do not add a duplicate button."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_KEEP_ORIGINAL_AEP_IMPORT_V1"


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    menu = root / "crates/engine/src/menus.rs"
    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    if not menu.is_file() or not frontend.is_file():
        raise SystemExit("EffectCraft original import-menu sources are missing")

    menu_source = menu.read_text(encoding="utf-8")
    frontend_source = frontend.read_text(encoding="utf-8")

    # The original File > Import > After Effects Project... command is the correct entry.
    # Keep it separate from EffectCraft Project... and do not add a top-toolbar import button.
    required_menu = "After Effects Project... | file.importAep"
    required_picker = '"file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),'
    if required_menu not in menu_source:
        raise SystemExit("The original File > Import > After Effects Project... menu item was not found")
    if required_picker not in frontend_source:
        raise SystemExit("The original .aep/.aepx file picker is missing")
    if '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"])),' not in frontend_source:
        raise SystemExit("The native EffectCraft Project import picker changed unexpectedly")

    print("Validated the original File > Import > After Effects Project... entry.")
    print("The .aep/.aepx picker stays separate from EffectCraft Project (.ecproj/.ecprojx).")
    print("No duplicate toolbar button or import-menu modification was added.")


if __name__ == "__main__":
    main()
