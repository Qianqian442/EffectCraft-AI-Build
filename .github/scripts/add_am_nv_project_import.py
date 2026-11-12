#!/usr/bin/env python3
"""Install the Alight Motion / NodeVideo project importer into the Android EffectCraft source."""
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
    scripts = Path(__file__).resolve().parent
    importer_source = scripts / "am_nv.rs"
    if not importer_source.is_file():
        raise SystemExit("The Alight Motion / NodeVideo importer source is missing")

    target = root / "crates/engine/src/cmd/am_nv.rs"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(importer_source.read_text(encoding="utf-8"), encoding="utf-8")

    # roxmltree is already pinned in Cargo.lock as a transitive workspace dependency.
    root_cargo = root / "Cargo.toml"
    replace_once(root_cargo, 'rayon = "1"\n', 'rayon = "1"\nroxmltree = "0.21.2"\n',
                 "workspace XML parser dependency")
    engine_cargo = root / "crates/engine/Cargo.toml"
    replace_once(engine_cargo, 'web-time = { workspace = true }\n',
                 'web-time = { workspace = true }\nroxmltree = { workspace = true }\n',
                 "engine XML parser dependency")

    lock_path = root / "Cargo.lock"
    lock = lock_path.read_text(encoding="utf-8")
    marker = 'name = "effectcraft-engine"\n'
    start = lock.find(marker)
    if start < 0:
        raise SystemExit("Could not find effectcraft-engine in Cargo.lock")
    end = lock.find("\n[[package]]", start)
    if end < 0:
        raise SystemExit("Could not find the end of the effectcraft-engine lock entry")
    block = lock[start:end]
    if '"roxmltree"' not in block:
        if ' "rayon",\n' not in block:
            raise SystemExit("Could not find the engine dependency insertion point in Cargo.lock")
        block = block.replace(' "rayon",\n', ' "rayon",\n "roxmltree",\n', 1)
        lock_path.write_text(lock[:start] + block + lock[end:], encoding="utf-8")

    cmd_registry = root / "crates/engine/src/cmd.rs"
    replace_once(cmd_registry, "mod import_project;\n",
                 "mod am_nv;\nmod import_project;\n", "project import module registration")

    import_project = root / "crates/engine/src/cmd/import_project.rs"
    replace_once(
        import_project,
        "fn import_project(s: &mut Session, p: &Value) -> Result<Value> {",
        "pub(crate) fn import_project(s: &mut Session, p: &Value) -> Result<Value> {",
        "allow the ZIP importer to merge an extracted EffectCraft project package",
    )
    replace_once(
        import_project,
        '    lower.ends_with(".ecproj") || lower.ends_with(".ecprojx")\n',
        '    lower.ends_with(".ecproj") || lower.ends_with(".ecprojx") || lower.ends_with(".nv") || lower.ends_with(".zip") || lower.ends_with(".alight") || lower.ends_with(".xml") || lower.ends_with(".aep") || lower.ends_with(".aepx") || lower.ends_with(".json")\n',
        "AE, NodeVideo and project package routing",
    )
    replace_once(
        import_project,
        '    let path = str_p(p, "path").ok_or_else(|| bad(C, "missing `path` (.ecproj)"))?.to_string();\n    let (mut sub, saved_by) = read_project(s, &path)?;',
        '    let path = str_p(p, "path").ok_or_else(|| bad(C, "missing project path"))?.to_string();\n    let lower = path.to_ascii_lowercase();\n    if lower.ends_with(".aep") || lower.ends_with(".aepx") {\n        return super::aep::import_aep(s, p);\n    }\n    if !lower.ends_with(".ecproj") && !lower.ends_with(".ecprojx") {\n        return super::am_nv::import_path(s, &path);\n    }\n    let (mut sub, saved_by) = read_project(s, &path)?;',
        "route AE, AM and NV projects through the original project import control",
    )
    replace_once(
        import_project,
        '"{path (.ecproj or .ecprojx)} — merges the project into a folder named after the file; returns {folder, items, comps, rootComps, primaryComp (the only root comp, else null), missingMedia, warnings}"',
        '"{path (.ecproj/.ecprojx/.nv/.zip/.xml/.alight/.json)} — imports into a new project folder and reports missing media or unsupported features"',
        "project import command format documentation",
    )

    aep_cmd = root / "crates/engine/src/cmd/aep.rs"
    replace_once(
        aep_cmd,
        "fn import_aep(s: &mut Session, p: &Value) -> Result<Value> {",
        "pub(crate) fn import_aep(s: &mut Session, p: &Value) -> Result<Value> {",
        "make the original AE importer callable from the unified project importer",
    )

    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    replace_once(
        frontend,
        '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"])),',
        '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx", "nv", "zip", "xml", "alight", "aep", "aepx", "json"])),',
        "original Import Project picker formats",
    )

    if not target.is_file() or "pub fn import_path" not in target.read_text(encoding="utf-8"):
        raise SystemExit("Alight Motion / NodeVideo import implementation was not installed")
    if "mod am_nv;" not in cmd_registry.read_text(encoding="utf-8"):
        raise SystemExit("Alight Motion / NodeVideo import command module is not registered")

    # The unified "Import Project" button dispatches file.importProject. When its
    # selected file is an AEP/AEPX, make the same dry-run / loss-consent dialog guard
    # run as the dedicated file.importAep menu item. Keep the pending command as
    # file.importAep so "Import Anyway" cannot fall back through the generic importer.
    aep_losses = root / "crates/ui-egui/src/panels/aep_losses.rs"
    old_guard = """pub fn guard(app: &mut EffectcraftApp, id: &str, params: &Value) -> Result<bool, String> {
    if id != "file.importAep" || params.get("allowLosses") == Some(&Value::Bool(true)) || params.get("dryRun") == Some(&Value::Bool(true)) {
        return Ok(false);
    }
    let mut dry = params.as_object().cloned().unwrap_or_default();
    dry.insert("dryRun".into(), Value::Bool(true));
    let r = app.session.execute(id, Value::Object(dry)).map_err(|e| e.to_string())?;
    let report = r.get("report").cloned().unwrap_or(Value::Null);
    if report["losses"].as_array().is_none_or(|l| l.is_empty()) {
        return Ok(false);
    }
    app.dialog_state.aep_losses.command = Some((id.to_string(), params.clone(), report));
    app.dialog = Some(Dialog::AepLosses);
    Ok(true)
}"""
    new_guard = """pub fn guard(app: &mut EffectcraftApp, id: &str, params: &Value) -> Result<bool, String> {
    let command = if id == "file.importAep" {
        Some("file.importAep")
    } else if id == "file.importProject"
        && params.get("path").and_then(Value::as_str).is_some_and(|path| {
            let lower = path.to_ascii_lowercase();
            lower.ends_with(".aep") || lower.ends_with(".aepx")
        })
    {
        Some("file.importAep")
    } else {
        None
    };
    let Some(command) = command else { return Ok(false) };
    if params.get("allowLosses") == Some(&Value::Bool(true)) || params.get("dryRun") == Some(&Value::Bool(true)) {
        return Ok(false);
    }
    let mut dry = params.as_object().cloned().unwrap_or_default();
    dry.insert("dryRun".into(), Value::Bool(true));
    let r = app.session.execute(command, Value::Object(dry)).map_err(|e| e.to_string())?;
    let report = r.get("report").cloned().unwrap_or(Value::Null);
    if report["losses"].as_array().is_none_or(|l| l.is_empty()) {
        return Ok(false);
    }
    app.dialog_state.aep_losses.command = Some((command.to_string(), params.clone(), report));
    app.dialog = Some(Dialog::AepLosses);
    Ok(true)
}"""
    replace_once(aep_losses, old_guard, new_guard, "route unified AEP import through loss confirmation")
    aep_test = """    #[test]
    fn unified_import_project_routes_aep_through_loss_guard() {
        let mut app = EffectcraftApp::new(effectcraft_engine::Session::default());
        let result = guard(&mut app, "file.importProject", &json!({"path": "/no/such/file.aep"}));
        assert!(result.is_err(), "AEP selection must run the AEP dry-run instead of bypassing it");
        assert!(app.dialog.is_none());
    }

"""
    test_marker = "    #[test]\n    fn agents_and_consented_calls_are_not_asked() {"
    replace_once(aep_losses, test_marker, aep_test + test_marker, "AEP route dry-run regression test")
    if "id == \"file.importProject\"" not in aep_losses.read_text(encoding="utf-8"):
        raise SystemExit("The unified AEP import is not guarded against silent loss")
    print("Unified Import Project AEP/AEPX picks now use the same dry-run and user loss-confirmation dialog.")
    print("Installed Alight Motion XML, NodeVideo .nv, CapCut draft_content.json and ZIP project import.")
    print("The existing EffectCraft Project import control now routes .aep/.aepx, .nv/.zip, AM XML and CapCut JSON; the dedicated AE menu stays available.")
    print("Unsupported effects, 3D conversions and missing media are reported to the user.")


if __name__ == "__main__":
    main()
