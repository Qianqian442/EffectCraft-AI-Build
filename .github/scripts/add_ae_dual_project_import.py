#!/usr/bin/env python3
"""Add separate desktop AE and EffectCraft-mobile exported-project import entries."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    aep = root / "crates/engine/src/cmd/aep.rs"
    am_nv = root / "crates/engine/src/cmd/am_nv.rs"
    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    menu = root / "crates/engine/src/menus.rs"
    losses = root / "crates/ui-egui/src/panels/aep_losses.rs"

    for path in (aep, am_nv, frontend, menu, losses):
        if not path.is_file():
            raise SystemExit(f"Required project-import source is missing: {path}")

    aep_source = aep.read_text(encoding="utf-8")
    if "pub(crate) fn import_aep(" not in aep_source:
        raise SystemExit("The original AE desktop importer is not available")
    if "file.importAepDesktop" not in aep_source:
        replace_once(
            aep,
            "pub fn specs() -> Vec<CommandSpec> {\n    vec![cmd!(",
            """pub fn specs() -> Vec<CommandSpec> {
    vec![
        cmd!("file.importAepDesktop", "AE Desktop Project...", ["File", "Import"], None,
            "{path (.aep or .aepx)} — imports an Adobe After Effects desktop project",
            always, import_aep),
        cmd!(""",
            "register the separate desktop AE import command",
        )

    # EffectCraft mobile exports are native .ecproj/.ecprojx files. The Share action
    # packages the collected .ecproj and its Footage directory into a ZIP. Import those
    # formats through the existing native EffectCraft project reader, never the AEP parser.
    am_nv_source = am_nv.read_text(encoding="utf-8")
    if "file.importEffectCraftMobile" not in am_nv_source:
        mobile_command = """fn import_effectcraft_mobile_project(s: &mut Session, p: &J) -> Result<J> {
    let path = p.get("path").and_then(J::as_str)
        .ok_or_else(|| err("缺少 EffectCraft 手机版工程路径"))?.to_string();
    let actual = match ext(&path).as_str() {
        "ecproj" | "ecprojx" => path,
        "zip" => {
            let (actual, _package_root) = extract_project_zip(s, &path)?;
            if !matches!(ext(&actual).as_str(), "ecproj" | "ecprojx") {
                return Err(err("ZIP 中没有找到 EffectCraft 手机版导出的 .ecproj/.ecprojx 工程文件"));
            }
            actual
        }
        _ => return Err(err("手机版工程仅支持 .ecproj、.ecprojx，或包含该工程及素材的 ZIP 包")),
    };
    super::import_project::import_project(s, &json!({"path": actual}))
}

"""
        replace_once(
            am_nv,
            "pub fn specs() -> Vec<CommandSpec> {\n    vec![",
            mobile_command + """pub fn specs() -> Vec<CommandSpec> {
    vec![
        cmd!("file.importEffectCraftMobile", "EffectCraft Mobile Project...", ["File", "Import"], None,
            "{path (.ecproj/.ecprojx or .zip containing an EffectCraft mobile project and collected footage)} — imports a project exported by EffectCraft mobile",
            always, import_effectcraft_mobile_project),
""",
            "register EffectCraft mobile-export project import",
        )

    replace_once(
        am_nv,
        'let file = project_file.ok_or_else(|| err("This ZIP does not contain a NodeVideo .nv project or an Alight Motion XML project"))?;',
        'let file = project_file.ok_or_else(|| err("This ZIP does not contain an EffectCraft .ecproj/.ecprojx, NodeVideo .nv, or Alight Motion XML project"))?;',
        "explain supported project types in ZIP errors",
    )

    frontend_source = frontend.read_text(encoding="utf-8")
    if '        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),' not in frontend_source:
        raise SystemExit("The original After Effects project picker changed unexpectedly")
    replace_once(
        frontend,
        '        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),',
        """        "file.importAepDesktop" => ("path", Ask::Open(&["aep", "aepx"])),
        "file.importEffectCraftMobile" => ("path", Ask::Open(&["ecproj", "ecprojx", "zip"])),
        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),""",
        "add distinct desktop-AE and EffectCraft-mobile file pickers",
    )

    replace_once(
        menu,
        "      After Effects Project... | file.importAep\n",
        """      AE 电脑版工程... | file.importAepDesktop
      EffectCraft 手机版工程... | file.importEffectCraftMobile
      After Effects Project... | file.importAep
""",
        "add distinct desktop AE and EffectCraft mobile import menu entries",
    )

    # Keep the original AE dry-run/loss-consent path and apply it to the new desktop alias.
    replace_once(
        losses,
        '    let command = if id == "file.importAep" {\n        Some("file.importAep")',
        '    let command = if id == "file.importAep" || id == "file.importAepDesktop" {\n        Some(id)',
        "protect the new desktop AE entry with the original loss confirmation",
    )

    aep_now = aep.read_text(encoding="utf-8")
    am_nv_now = am_nv.read_text(encoding="utf-8")
    frontend_now = frontend.read_text(encoding="utf-8")
    menu_now = menu.read_text(encoding="utf-8")
    losses_now = losses.read_text(encoding="utf-8")
    if "file.importAepDesktop" not in aep_now:
        raise SystemExit("The desktop AE command was not registered")
    if "file.importAep" not in aep_now:
        raise SystemExit("The original AE import command was not preserved")
    if "file.importEffectCraftMobile" not in am_nv_now or "import_effectcraft_mobile_project" not in am_nv_now:
        raise SystemExit("The EffectCraft mobile project import command is incomplete")
    if '\"file.importEffectCraftMobile\" => (\"path\", Ask::Open(&[\"ecproj\", \"ecprojx\", \"zip\"]))' not in frontend_now:
        raise SystemExit("The mobile picker must accept .ecproj/.ecprojx and ZIP packages")
    if "AE 电脑版工程... | file.importAepDesktop" not in menu_now:
        raise SystemExit("The desktop AE menu entry is missing")
    if "EffectCraft 手机版工程... | file.importEffectCraftMobile" not in menu_now:
        raise SystemExit("The EffectCraft mobile menu entry is missing")
    if 'id == "file.importAep" || id == "file.importAepDesktop"' not in losses_now:
        raise SystemExit("The desktop AE loss confirmation guard is missing")
    print("Desktop import: .aep/.aepx through the original After Effects importer.")
    print("Mobile import: EffectCraft .ecproj/.ecprojx or the ZIP exported by EffectCraft mobile, including collected footage.")
    print("Original Import Project and original After Effects import commands remain available.")
    print("Mobile EffectCraft projects are routed to the native project reader, not the AEP parser.")


if __name__ == "__main__":
    main()
