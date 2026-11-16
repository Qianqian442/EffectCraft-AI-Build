#!/usr/bin/env python3
"""Keep the five format-specific project import actions in File > Import only."""
from __future__ import annotations

import os
import re
from pathlib import Path


def patch_file_import_menu(root: Path) -> None:
    path = root / "crates/engine/src/menus.rs"
    source = path.read_text(encoding="utf-8")
    start_match = re.search(r"(?m)^  Import\r?$", source)
    if not start_match:
        raise SystemExit("Could not locate the original File > Import menu")
    end_match = re.search(r"(?m)^  Import Recent Footage\r?$", source[start_match.end():])
    if not end_match:
        raise SystemExit("Could not locate the end of File > Import")
    start = start_match.start()
    end = start_match.end() + end_match.start()

    menu = """  Import
    File... | file.import
    Multiple Files... | file.importMultiple
    导入电脑版Ae工程... | file.importAepDesktop
    导入手机版Ae工程... | file.importAepMobilePackage
    导入am工程... | file.importAlightMotionProject
    导入NV工程... | file.importNodeVideoProject
    导入capcut工程... | file.importCapCutProject
    更多工程格式
      自有工程... | file.importProject
      自有工程包... | file.importEffectCraftMobile
      工程压缩包（ZIP/RAR）... | file.extractProjectArchive
      Adobe Premiere Pro Project... | file.importTimeline
      After Effects Project... | file.importAep
    Placeholder... | file.importPlaceholder
    Solid... | file.importSolid
    Lottie... | file.importLottie
    Vanishing Point (.vpe)... | file.importVanishingPoint
    Essential Graphics Template... | essential.importTemplate
"""
    source = source[:start] + menu + source[end:]
    path.write_text(source, encoding="utf-8")

    final = path.read_text(encoding="utf-8")
    required = (
        "导入电脑版Ae工程... | file.importAepDesktop",
        "导入手机版Ae工程... | file.importAepMobilePackage",
        "导入am工程... | file.importAlightMotionProject",
        "导入NV工程... | file.importNodeVideoProject",
        "导入capcut工程... | file.importCapCutProject",
        "自有工程... | file.importProject",
        "自有工程包... | file.importEffectCraftMobile",
        "工程压缩包（ZIP/RAR）... | file.extractProjectArchive",
    )
    for entry in required:
        if entry not in final:
            raise SystemExit("Missing File > Import entry: " + entry)
    project_panel = (root / "crates/ui-egui/src/panels/project.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_FIVE_PROJECT_IMPORT_BUTTONS_V1" in project_panel:
        raise SystemExit("Duplicate project-format buttons remain in the Project panel.")
    if any(label in project_panel for label in (
        "导入电脑版Ae工程", "导入手机版Ae工程", "导入am工程", "导入NV工程", "导入capcut工程"
    )):
        raise SystemExit("Project import labels must stay in File > Import, not the Project panel.")
    print("Installed five independent project import options in File > Import only.")
    print("Registered separate mobile-AE, AM, NV and CapCut file pickers.")
    print("The original EffectCraft importer remains in the File menu; Project panel keeps media import only.")


def patch_frontend_pickers(root: Path) -> None:
    """Register a native file picker for each of the four non-desktop project formats."""
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    mappings = """        "file.extractProjectArchive" => ("path", Ask::Open(&["zip", "rar"])),
        "file.importAepMobilePackage" => ("path", Ask::Open(&["zip"])),
        "file.importAlightMotionProject" => ("path", Ask::Open(&["xml", "alight", "zip"])),
        "file.importNodeVideoProject" => ("path", Ask::Open(&["nv", "json", "zip"])),
        "file.importCapCutProject" => ("path", Ask::Open(&["json", "zip"])),
"""
    am_old = '"file.importAlightMotionProject" => ("path", Ask::Open(&["xml", "alight", "zip"])),'
    am_new = '"file.importAlightMotionProject" => ("path", Ask::Open(&["amproj", "xml", "alight", "zip"])),'
    if am_old in source:
        source = source.replace(am_old, am_new, 1)
    elif am_new not in source:
        raise SystemExit("Could not safely extend the Alight Motion file picker with .amproj")

    required = (
        '"file.extractProjectArchive" =>',
        '"file.importAepMobilePackage" =>',
        '"file.importAlightMotionProject" =>',
        '"file.importNodeVideoProject" =>',
        '"file.importCapCutProject" =>',
    )
    if all(item in source for item in required):
        path.write_text(source, encoding="utf-8")
        return
    anchor = '        "file.importAepDesktop" => ("path", Ask::Open(&["aep", "aepx"])),\n'
    if anchor not in source:
        raise SystemExit("The desktop AE picker mapping must exist before adding other project pickers.")
    source = source.replace(anchor, anchor + mappings, 1)
    path.write_text(source, encoding="utf-8")

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_file_import_menu(root)
    patch_frontend_pickers(root)


if __name__ == "__main__":
    main()
