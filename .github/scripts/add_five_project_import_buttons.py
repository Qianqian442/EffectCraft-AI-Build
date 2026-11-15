#!/usr/bin/env python3
"""Put five project-format file pickers under the original File > Import menu."""
from __future__ import annotations

import os
import re
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_file_menu(root: Path) -> None:
    path = root / "crates/engine/src/menus.rs"
    source = path.read_text(encoding="utf-8")
    start = re.search(r"(?m)^  Import\r?$", source)
    if not start:
        raise SystemExit("Could not find the original File > Import menu.")
    end = re.search(r"(?m)^  Import Recent Footage\r?$", source[start.end():])
    if not end:
        raise SystemExit("Could not find the end of the original File > Import menu.")
    block_end = start.end() + end.start()
    old_block = source[start.start():block_end]
    required = (
        "导入电脑版AE工程... | file.importAepDesktop",
        "导入手机版AE工程... | file.importAepMobilePackage",
        "导入AM工程... | file.importAlightMotionProject",
        "导入NV工程... | file.importNodeVideoProject",
        "导入CapCut工程... | file.importCapCutProject",
    )
    if all(item in old_block for item in required):
        return

    new_block = """  Import
    File... | file.import
    Multiple Files... | file.importMultiple
    EffectCraft Project... | file.importProject
    ---
    工程格式导入
      导入电脑版AE工程... | file.importAepDesktop
      导入手机版AE工程... | file.importAepMobilePackage
      导入AM工程... | file.importAlightMotionProject
      导入NV工程... | file.importNodeVideoProject
      导入CapCut工程... | file.importCapCutProject
    ---
    Adobe Premiere Pro Project... | file.importTimeline
    Placeholder... | file.importPlaceholder
    Solid... | file.importSolid
    Lottie... | file.importLottie
    Vanishing Point (.vpe)... | file.importVanishingPoint
    Essential Graphics Template... | essential.importTemplate
"""
    source = source[:start.start()] + new_block + source[block_end:]
    path.write_text(source, encoding="utf-8")


def patch_project_format_pickers(root: Path) -> None:
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    entries = (
        '"file.importAepMobilePackage" => ("path", Ask::Open(&["zip"]))',
        '"file.importAlightMotionProject" => ("path", Ask::Open(&["xml", "alight", "zip"]))',
        '"file.importNodeVideoProject" => ("path", Ask::Open(&["nv", "json", "zip"]))',
        '"file.importCapCutProject" => ("path", Ask::Open(&["json", "zip"]))',
    )
    if not all(entry in source for entry in entries):
        anchor = '        "file.importEffectCraftMobile" => ("path", Ask::Open(&["ecproj", "ecprojx", "zip"])),'
        additions = "\n".join("        " + entry + "," for entry in entries) + "\n"
        source = replace_once(source, anchor, additions + anchor, "add dedicated project-format pickers")
        path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    patch_file_menu(root)
    patch_project_format_pickers(root)

    menu = (root / "crates/engine/src/menus.rs").read_text(encoding="utf-8")
    start = re.search(r"(?m)^  Import\r?$", menu)
    end = re.search(r"(?m)^  Import Recent Footage\r?$", menu[start.end():]) if start else None
    if not start or not end:
        raise SystemExit("The final File > Import menu could not be re-read.")
    visible = menu[start.start():start.end() + end.start()]
    for item in (
        "导入电脑版AE工程... | file.importAepDesktop",
        "导入手机版AE工程... | file.importAepMobilePackage",
        "导入AM工程... | file.importAlightMotionProject",
        "导入NV工程... | file.importNodeVideoProject",
        "导入CapCut工程... | file.importCapCutProject",
        "EffectCraft Project... | file.importProject",
        "File... | file.import",
        "Multiple Files... | file.importMultiple",
    ):
        if item not in visible:
            raise SystemExit(f"Missing File > Import action: {item}")

    project = (root / "crates/ui-egui/src/panels/project.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_FIVE_PROJECT_IMPORT_BUTTONS_V1" in project:
        raise SystemExit("Five format buttons must not be placed in the Project panel.")
    if '"file.importProject"' not in project:
        raise SystemExit("The original native EffectCraft Project import button was removed.")

    frontend = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    for command in (
        "file.importAepDesktop", "file.importAepMobilePackage",
        "file.importAlightMotionProject", "file.importNodeVideoProject", "file.importCapCutProject",
    ):
        if f'"{command}" =>' not in frontend:
            raise SystemExit(f"Missing selectable-file mapping for {command}")
    print("Verified five format-specific project imports are in File > Import and original Project-panel import remains.")


if __name__ == "__main__":
    main()
