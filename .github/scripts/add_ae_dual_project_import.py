#!/usr/bin/env python3
"""Add separate desktop and mobile After Effects project import entries."""
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
            raise SystemExit(f"Required AE import source is missing: {path}")

    aep_source = aep.read_text(encoding="utf-8")
    if "pub(crate) fn import_aep(" not in aep_source:
        raise SystemExit("The original AE importer is not exposed to the import-format router")

    # Extract an AE project and its sibling media safely from a mobile ZIP package.
    replace_once(
        am_nv,
        """        if lower.ends_with(".ecproj") || lower.ends_with(".ecprojx") {
            project_file = Some(destination);
        } else if project_file.is_none() && (lower.ends_with("draft_content.json") || lower.ends_with(".capcut.json")) {""",
        """        if lower.ends_with(".ecproj") || lower.ends_with(".ecprojx") {
            project_file = Some(destination);
        } else if (lower.ends_with(".aep") || lower.ends_with(".aepx")) && project_file.is_none() {
            project_file = Some(destination);
        } else if project_file.is_none() && (lower.ends_with("draft_content.json") || lower.ends_with(".capcut.json")) {""",
        "recognize AE projects inside mobile project ZIP packages",
    )
    replace_once(
        am_nv,
        'let file = project_file.ok_or_else(|| err("This ZIP does not contain a NodeVideo .nv project or an Alight Motion XML project"))?;',
        'let file = project_file.ok_or_else(|| err("This ZIP does not contain a supported EffectCraft, After Effects, NodeVideo or Alight Motion project"))?;',
        "mobile package missing-project explanation",
    )
    mobile_package = """pub fn import_aep_mobile_package(s: &mut Session, path: &str, options: &J) -> Result<J> {
    let (actual, _package_root) = extract_project_zip(s, path)?;
    if !matches!(ext(&actual).as_str(), "aep" | "aepx") {
        return Err(err("The selected mobile package must contain one .aep or .aepx After Effects project file"));
    }
    let mut params = options.as_object().cloned().unwrap_or_default();
    params.insert("path".into(), J::String(actual));
    super::aep::import_aep(s, &J::Object(params))
}

"""
    replace_once(
        am_nv,
        "#[cfg(test)]\nmod tests {",
        mobile_package + "#[cfg(test)]\nmod tests {",
        "mobile AE package import command helper",
    )

    # Allow the mobile package's extracted file to be read from app-private storage.
    replace_once(
        aep,
        '    let bytes = s.services.read_file(&path).map_err(|e| EngineError::Other(format!("cannot read {path}: {e}")))?;',
        """    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(_) => s.services.read_file(&path).map_err(|e| EngineError::Other(format!("cannot read {path}: {e}")))?,
    };""",
        "read extracted mobile AE project from app-private storage",
    )

    mobile_command = """fn import_aep_mobile(s: &mut Session, p: &Value) -> Result<Value> {
    let path = str_p(p, "path").ok_or_else(|| bad("file.importAepMobile", "missing path"))?.to_string();
    if path.to_ascii_lowercase().ends_with(".zip") {
        return super::am_nv::import_aep_mobile_package(s, &path, p);
    }
    import_aep(s, p)
}

"""
    replace_once(
        aep,
        "pub fn specs() -> Vec<CommandSpec> {",
        mobile_command + "pub fn specs() -> Vec<CommandSpec> {",
        "mobile AE import command handler",
    )
    replace_once(
        aep,
        "pub fn specs() -> Vec<CommandSpec> {\n    vec![cmd!(",
        """pub fn specs() -> Vec<CommandSpec> {
    vec![
        cmd!("file.importAepDesktop", "AE Desktop Project...", ["File", "Import"], None,
            "{path (.aep or .aepx)} — imports a desktop After Effects project with the standard AE importer",
            always, import_aep),
        cmd!("file.importAepMobile", "AE Mobile Project Package...", ["File", "Import"], None,
            "{path (.aep/.aepx or .zip containing one AE project)} — imports a mobile AE project and its collected media",
            always, import_aep_mobile),
        cmd!("""
        ,
        "register separate desktop and mobile AE import commands",
    )

    replace_once(
        frontend,
        '        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),',
        """        "file.importAepDesktop" => ("path", Ask::Open(&["aep", "aepx"])),
        "file.importAepMobile" => ("path", Ask::Open(&["aep", "aepx", "zip"])),
        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),""",
        "separate desktop and mobile AE file pickers",
    )
    replace_once(
        menu,
        "      After Effects Project... | file.importAep\n",
        """      AE 电脑版工程... | file.importAepDesktop
      AE 手机版工程包... | file.importAepMobile
      After Effects Project... | file.importAep
""",
        "show separate AE desktop and mobile import menu entries",
    )

    # Both dedicated entries retain the existing dry-run / unsupported-loss confirmation.
    replace_once(
        losses,
        '    let command = if id == "file.importAep" {\n        Some("file.importAep")',
        """    let command = if matches!(id, "file.importAep" | "file.importAepDesktop" | "file.importAepMobile") {
        Some(id)""",
        "protect the dedicated AE import commands with the existing loss confirmation",
    )

    aep_now = aep.read_text(encoding="utf-8")
    am_nv_now = am_nv.read_text(encoding="utf-8")
    frontend_now = frontend.read_text(encoding="utf-8")
    menu_now = menu.read_text(encoding="utf-8")
    losses_now = losses.read_text(encoding="utf-8")
    required = [
        "file.importAepDesktop",
        "file.importAepMobile",
        "import_aep_mobile",
    ]
    if any(token not in aep_now for token in required):
        raise SystemExit("Separate AE desktop/mobile command registration is incomplete")
    if "pub fn import_aep_mobile_package" not in am_nv_now or 'lower.ends_with(".aep")' not in am_nv_now:
        raise SystemExit("Mobile AE ZIP package extraction is not wired to the existing AEP importer")
    if '"file.importAepMobile" => ("path", Ask::Open(&["aep", "aepx", "zip"]))' not in frontend_now:
        raise SystemExit("The mobile AE picker does not accept the supported project/package types")
    if "AE 电脑版工程... | file.importAepDesktop" not in menu_now or "AE 手机版工程包... | file.importAepMobile" not in menu_now:
        raise SystemExit("The two separate AE import menu options are not visible")
    if '"file.importAepMobile"' not in losses_now:
        raise SystemExit("The mobile AE import path is missing the loss confirmation guard")
    print("Added separate AE desktop and mobile import entries.")
    print("Desktop: .aep/.aepx. Mobile: .aep/.aepx or a ZIP containing one AE project and its media.")
    print("Both entries retain the original AE parser and loss-preview confirmation.")


if __name__ == "__main__":
    main()
