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

    # One visible project-import command handles EffectCraft, AE, AM, NodeVideo and CapCut.
    # The separate AE and Premiere-specific menu entries caused a crowded, duplicate-looking
    # import menu. The underlying commands remain registered for internal/compatibility use.
    project_item = "EffectCraft Project... | file.importProject"
    unified_item = "导入工程... | file.importProject"
    if project_item not in menu_source and unified_item not in menu_source:
        raise SystemExit("The original EffectCraft Project import command was not found")
    if project_item in menu_source:
        menu_source = menu_source.replace(project_item, unified_item)

    menu_source = menu_source.replace("    After Effects Project... | file.importAep\n", "")
    menu_source = menu_source.replace("    Adobe Premiere Pro Project... | file.importTimeline\n", "")

    # There must be exactly one visible project import entry, regardless of platform menu block.
    visible_project_entries = [
        line for line in menu_source.splitlines()
        if "file.importProject" in line or "file.importAep" in line or "file.importTimeline" in line
    ]
    if sum("file.importProject" in line for line in visible_project_entries) < 1:
        raise SystemExit("Unified Import Project menu item was lost")
    if any("file.importAep" in line or "file.importTimeline" in line for line in visible_project_entries):
        raise SystemExit("A duplicate AE/Premiere project import menu item remains")

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
