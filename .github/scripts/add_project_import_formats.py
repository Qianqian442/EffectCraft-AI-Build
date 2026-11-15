#!/usr/bin/env python3
"""Preserve EffectCraft's original File > Import menu and its existing project-import position."""
from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    menu = root / "crates/engine/src/menus.rs"
    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    if not menu.is_file() or not frontend.is_file():
        raise SystemExit("EffectCraft original import-menu sources are missing")

    menu_source = menu.read_text(encoding="utf-8")
    frontend_source = frontend.read_text(encoding="utf-8")

    start = menu_source.find("  Import\n")
    end = menu_source.find("  Import Recent Footage\n", start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate the original File > Import menu block")
    block = menu_source[start:end]

    # These entries must remain exactly where upstream placed them. This is a validation-only
    # patch: it must never move, rename, group, hide or remove any original import command.
    required_in_order = [
        "    File... | file.import",
        "    Multiple Files... | file.importMultiple",
        "    Adobe Premiere Pro Project... | file.importTimeline",
        "    EffectCraft Project... | file.importProject",
        "    Placeholder... | file.importPlaceholder",
        "    Solid... | file.importSolid",
        "    After Effects Project... | file.importAep",
        "    Lottie... | file.importLottie",
        "    Vanishing Point (.vpe)... | file.importVanishingPoint",
        "    Essential Graphics Template... | essential.importTemplate",
    ]
    positions = [block.find(entry) for entry in required_in_order]
    if any(position < 0 for position in positions):
        missing = [entry for entry, position in zip(required_in_order, positions) if position < 0]
        raise SystemExit("Original File > Import entries are missing: " + "; ".join(missing))
    if positions != sorted(positions):
        raise SystemExit("Original File > Import commands have been moved or reordered")

    if '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"])),' not in frontend_source:
        raise SystemExit("The original EffectCraft Project picker changed unexpectedly")
    if '"file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),' not in frontend_source:
        raise SystemExit("The original After Effects project picker changed unexpectedly")
    if "file_dialog_async" not in frontend_source:
        raise SystemExit("The original asynchronous file-picker pathway is missing")

    # Intentionally do not write menu_source: preserve its original layout and all commands.
    print("Verified the original File > Import menu position and all original import commands; no menu items were moved or removed.")


if __name__ == "__main__":
    main()
