#!/usr/bin/env python3
"""Relocate native Project import to the Project panel and group other project import formats."""
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

    start = menu_source.find("  Import\\n")
    end = menu_source.find("  Import Recent Footage\\n", start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate the original File > Import menu block")
    block = menu_source[start:end]

    # Move the native EffectCraft Project entry to the Project panel's dedicated
    # Import Project button. Keep the original command and all other import commands.
    required_entries = [
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
    if any(entry not in block for entry in required_entries):
        missing = [entry for entry in required_entries if entry not in block]
        raise SystemExit("Original import commands are missing: " + "; ".join(missing))

    # Preserve the old AE/Premiere import commands under one secondary submenu so the
    # primary File > Import list is less crowded. The unified Project-panel button handles
    # EffectCraft, AE, AM, NodeVideo and CapCut formats through file.importProject.
    unified_block = """  Import
    File... | file.import
    Multiple Files... | file.importMultiple
    更多工程格式
      Adobe Premiere Pro Project... | file.importTimeline
      After Effects Project... | file.importAep
    Placeholder... | file.importPlaceholder
    Solid... | file.importSolid
    Lottie... | file.importLottie
    Vanishing Point (.vpe)... | file.importVanishingPoint
    Essential Graphics Template... | essential.importTemplate
"""
    menu_source = menu_source[:start] + unified_block + menu_source[end:]
    menu.write_text(menu_source, encoding="utf-8")

    if '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"])),' not in frontend_source:
        raise SystemExit("The original EffectCraft Project picker changed unexpectedly")
    if '"file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),' not in frontend_source:
        raise SystemExit("The original After Effects project picker changed unexpectedly")
    if "file_dialog_async" not in frontend_source:
        raise SystemExit("The original asynchronous file-picker pathway is missing")

    # file.importProject remains registered and will be surfaced as a Project-panel button.
    command_registry = (root / "crates/engine/src/cmd/import_project.rs").read_text(encoding="utf-8")
    if '"file.importProject"' not in command_registry:
        raise SystemExit("The native EffectCraft Project import command is not registered")
    if "EffectCraft Project... | file.importProject" in menu_source:
        raise SystemExit("The duplicate native Project menu entry is still visible")
    if "更多工程格式" not in menu_source or "file.importAep" not in menu_source or "file.importTimeline" not in menu_source:
        raise SystemExit("The secondary project-format submenu is missing an original import command")
    print("Moved the native Project import action to the Project panel; AE/Premiere imports remain available under More Project Formats.")
    print("All original import commands remain registered; only the duplicate visible entry was relocated.")


if __name__ == "__main__":
    main()
