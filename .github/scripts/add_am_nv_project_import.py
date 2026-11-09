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
        '    lower.ends_with(".ecproj") || lower.ends_with(".ecprojx")\n',
        '    lower.ends_with(".ecproj") || lower.ends_with(".ecprojx") || lower.ends_with(".nv") || lower.ends_with(".zip") || lower.ends_with(".alight") || lower.ends_with(".xml") || lower.ends_with(".aep") || lower.ends_with(".aepx")\n',
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
        '"{path (.ecproj/.ecprojx/.nv/.zip/.xml/.alight)} — imports into a new project folder and reports missing media or unsupported features"',
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
        '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx", "nv", "zip", "xml", "alight", "aep", "aepx"])),',
        "original Import Project picker formats",
    )

    if not target.is_file() or "pub fn import_path" not in target.read_text(encoding="utf-8"):
        raise SystemExit("Alight Motion / NodeVideo import implementation was not installed")
    if "mod am_nv;" not in cmd_registry.read_text(encoding="utf-8"):
        raise SystemExit("Alight Motion / NodeVideo import command module is not registered")
    print("Installed Alight Motion XML and NodeVideo .nv / ZIP project import.")
    print("The existing EffectCraft Project import control now routes .aep/.aepx, .nv/.zip and AM XML; the dedicated AE menu stays available.")
    print("Unsupported effects, 3D conversions and missing media are reported to the user.")


if __name__ == "__main__":
    main()
