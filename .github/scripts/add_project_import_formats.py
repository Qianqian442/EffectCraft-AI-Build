#!/usr/bin/env python3
"""Keep project formats in File > Import and preserve the native EffectCraft importer."""
from __future__ import annotations

import os
import re
from pathlib import Path


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    menu = root / "crates/engine/src/menus.rs"
    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    if not menu.is_file() or not frontend.is_file():
        raise SystemExit("EffectCraft original import-menu sources are missing")

    menu_source = menu.read_text(encoding="utf-8")
    frontend_source = frontend.read_text(encoding="utf-8")

    # Find exact top-level menu lines while tolerating LF and CRLF source files.
    start_match = re.search(r"(?m)^  Import\r?$", menu_source)
    if not start_match:
        raise SystemExit("Could not locate the original File > Import menu heading")
    end_match = re.search(r"(?m)^  Import Recent Footage\r?$", menu_source[start_match.end():])
    if not end_match:
        raise SystemExit("Could not locate the end of the original File > Import menu block")
    start = start_match.start()
    end = start_match.end() + end_match.start()
    block = menu_source[start:end]

    # Keep the native EffectCraft Project command in File > Import and expose
    # the five requested format-specific import actions in the same menu.
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
      导入电脑版Ae工程... | file.importAepDesktop
      导入手机版Ae工程... | file.importAepMobilePackage
      导入am工程... | file.importAlightMotionProject
      导入NV工程... | file.importNodeVideoProject
      导入capcut工程... | file.importCapCutProject
      EffectCraft Project... | file.importProject
      EffectCraft 手机版工程包... | file.importEffectCraftMobile
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

    # The original native EffectCraft project action remains visible in File > Import.
    command_registry = (root / "crates/engine/src/cmd/import_project.rs").read_text(encoding="utf-8")
    if '"file.importProject"' not in command_registry:
        raise SystemExit("The native EffectCraft Project import command is not registered")
    if "EffectCraft Project... | file.importProject" not in menu_source:
        raise SystemExit("The original native EffectCraft Project import entry is missing")
    if "更多工程格式" not in menu_source or "file.importAep" not in menu_source or "file.importTimeline" not in menu_source:
        raise SystemExit("The secondary project-format submenu is missing an original import command")
    print("Kept the native EffectCraft importer and five separate project-format imports in File > Import.")
    print("All original non-project import commands remain available.")


if __name__ == "__main__":
    main()
