#!/usr/bin/env python3
"""Keep one unified AM / NV / AE / CapCut project entry under File > Import."""
from __future__ import annotations

import os
from pathlib import Path


def replace_exact(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source entry, found {count}")
    return source.replace(old, new, 1)


def remove_exact(source: str, old: str, label: str) -> str:
    count = source.count(old)
    if count == 0:
        return source
    if count != 1:
        raise SystemExit(f"{label}: expected one source entry to remove, found {count}")
    return source.replace(old, "", 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    menu = root / "crates/engine/src/menus.rs"
    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    if not menu.is_file() or not frontend.is_file():
        raise SystemExit("EffectCraft original File > Import sources are missing")

    menu_source = menu.read_text(encoding="utf-8")
    frontend_source = frontend.read_text(encoding="utf-8")

    # The existing File > Import submenu is the only home for project importing.
    # Ordinary pictures/videos use the Project panel's media picker; do not expose
    # generic all-file / multiple-file pickers here.
    menu_source = remove_exact(menu_source, "    File... | file.import\n", "generic single-file media import")
    menu_source = remove_exact(menu_source, "    Multiple Files... | file.importMultiple\n", "generic multi-file media import")

    menu_source = replace_exact(
        menu_source,
        "    EffectCraft Project... | file.importProject\n",
        "    导入am/NV/Ae/capcut工程 | file.importProject\n",
        "unified project import menu item",
    )
    menu_source = remove_exact(
        menu_source,
        "    After Effects Project... | file.importAep\n",
        "duplicate dedicated After Effects import menu item",
    )

    # Keep the existing async Android picker. The AM/NV importer step extends the
    # extension list on this one command after this script runs.
    required_picker = '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"])),'
    if required_picker not in frontend_source:
        raise SystemExit("The existing unified EffectCraft project file picker changed unexpectedly")
    if "file_dialog_async" not in frontend_source:
        raise SystemExit("The original asynchronous Android file-picker pathway is missing")

    import_block = menu_source.split("  Import\n", 1)[1].split("  Import Recent Footage", 1)[0]
    if import_block.count("| file.importProject") != 1:
        raise SystemExit("File > Import must expose exactly one unified project-import button")
    if "file.importAep" in import_block:
        raise SystemExit("The separate After Effects project-import row is still visible")
    if "file.importMultiple" in import_block or "file.import |" in import_block:
        raise SystemExit("Generic all-file media pickers must not remain in File > Import")

    menu.write_text(menu_source, encoding="utf-8")
    print("File > Import now shows one project button: 导入 AM / NV / AE / CapCut 工程...")
    print("The one button opens the unified project picker; format-specific import entries are hidden.")
    print("Generic media file pickers were removed from this submenu; picture/video import stays in the Project media picker.")
    print("Plugin import remains a separate plugin-only picker.")


if __name__ == "__main__":
    main()
