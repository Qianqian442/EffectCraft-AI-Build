#!/usr/bin/env python3
"""Consolidate all supported project formats behind one Import Project menu entry."""
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

    # Keep the two everyday actions visible and group less-used import commands.
    # AE, AM, NodeVideo and CapCut formats are handled by the one unified Project picker.
    import_start = menu_source.find("  Import\\n")
    import_end = menu_source.find("  Import Recent Footage\\n", import_start)
    if import_start < 0 or import_end < 0:
        raise SystemExit("Could not locate the original File > Import menu block")
    import_block = menu_source[import_start:import_end]
    if "EffectCraft Project... | file.importProject" not in import_block and "导入工程... | file.importProject" not in import_block:
        raise SystemExit("The original EffectCraft Project import command was not found")

    unified_block = """  Import
    导入素材... | file.import
    导入工程... | file.importProject
    更多导入类型
      Multiple Files... | file.importMultiple
      Placeholder... | file.importPlaceholder
      Solid... | file.importSolid
      Lottie... | file.importLottie
      Vanishing Point (.vpe)... | file.importVanishingPoint
      Essential Graphics Template... | essential.importTemplate
"""
    menu_source = menu_source[:import_start] + unified_block + menu_source[import_end:]
    import_block = menu_source[import_start:import_start + len(unified_block)]
    if import_block.count("导入工程... | file.importProject") != 1:
        raise SystemExit("The unified project importer must appear exactly once in the Import menu")
    if "file.importAep" in import_block or "file.importTimeline" in import_block:
        raise SystemExit("A duplicate AE/Premiere project import entry remains in the visible Import menu")

    required_picker = '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"])),'
    if required_picker not in frontend_source:
        raise SystemExit("The original EffectCraft Project file picker changed unexpectedly")
    if "file_dialog_async" not in frontend_source:
        raise SystemExit("The original asynchronous file-picker pathway is missing")

    menu.write_text(menu_source, encoding="utf-8")
    print("Consolidated supported EffectCraft, AE, AM, NodeVideo and CapCut project formats into one Import Project menu item.")
    print("Generic File / Multiple Files media import controls remain separate; no project format support was removed.")


if __name__ == "__main__":
    main()
