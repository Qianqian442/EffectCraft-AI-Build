#!/usr/bin/env python3
"""Backport the native After Effects AEP exporter into the pinned source tree."""
from __future__ import annotations
import os
import shutil
from pathlib import Path

def once(src, old, new, label):
    if new in src:
        return src
    if src.count(old) != 1:
        raise SystemExit(f"{label}: expected one insertion point")
    return src.replace(old, new, 1)

def extract_rust_fn(source, signature):
    start = source.find(signature)
    if start < 0:
        raise SystemExit(f"Missing upstream function: {signature}")
    brace = source.find("{", start)
    depth = 0
    in_string = False
    escaped = False
    for i in range(brace, len(source)):
        ch = source[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1] + "\n"
    raise SystemExit("Could not parse the upstream Rust function body")

def patch_aep(root, upstream):
    src = upstream / "crates/aep/src"
    dst = root / "crates/aep/src"
    shutil.copy2(src / "export.rs", dst / "export.rs")
    shutil.copytree(src / "export", dst / "export", dirs_exist_ok=True)
    p = dst / "lib.rs"
    s = p.read_text()
    s = once(s, "pub mod container;\npub mod import;\n",
             "pub mod container;\npub mod export;\npub mod import;\n", "AEP module registration")
    p.write_text(s)

    p = dst / "container/effect_map.rs"
    s = p.read_text()
    extra = """/// Reverse lookup by After Effects match name.
pub fn by_match_name(match_name: &str) -> Option<&'static EffectMap> {
    EFFECTS.iter().find(|m| m.match_name == match_name)
}

/// Reverse lookup by EffectCraft effect id.
pub fn by_effect(effect: &str) -> Option<&'static EffectMap> {
    EFFECTS.iter().find(|m| m.effect == effect)
}

"""
    s = once(s, "/// The EffectCraft parameters Hue/Saturation's master values",
             extra + "/// The EffectCraft parameters Hue/Saturation's master values", "effect lookup helpers")
    p.write_text(s)

    p = dst / "container/style_map.rs"
    s = p.read_text()
    s = once(s, "impl StyleMap {\n    /// A parameter's full match name",
             "impl StyleMap {\n    /// The switch-group match name.\n    pub fn switch_name(&self) -> String {\n        format!(\"{}/enabled\", self.ae)\n    }\n\n    /// A parameter's full match name",
             "style switch-name helper")
    marker = "/// The style with this switch-group prefix.\npub fn by_ae(prefix: &str) -> Option<&'static StyleMap> {\n    STYLES.iter().find(|s| s.ae == prefix)\n}\n"
    repl = marker + "\n/// Reverse lookup by EffectCraft style id.\npub fn by_ec(id: &str) -> Option<&'static StyleMap> {\n    STYLES.iter().find(|s| s.ec == id)\n}\n"
    s = once(s, marker, repl, "style reverse lookup")
    p.write_text(s)

    p = dst / "container/effects.rs"
    s = p.read_text()
    s = once(s, "                && let Some(b) = u.bytes()\n            {",
             "                && let Some(b) = u.bytes()\n                && !b.is_empty()\n            {", "empty popup label guard")
    p.write_text(s)

def patch_engine(root, upstream):
    upstream_aep = (upstream / "crates/engine/src/cmd/aep.rs").read_text()
    export_fn = extract_rust_fn(upstream_aep, "fn export_aep(s: &mut Session, p: &Value) -> Result<Value>")
    write_anchor = '    s.services.write_file(&path, &res.bytes).map_err(|e| EngineError::Other(format!("cannot write {path}: {e}")))?;'
    export_fn = once(
        export_fn,
        write_anchor,
        write_anchor + '\n    s.events.push(crate::Event::Frontend { command: "effectcraft.projectExported".into(), params: json!({"path": path, "format": "Ae"}) });',
        "emit the AE export-complete event only after the .aep file is written",
    )
    export_fn = export_fn.replace(
        "AepExportError::Refused(_) => {\n            EngineError::Refused { losses: e.to_string(), advice: \"nothing was written: pass allowLosses to export anyway, or dryRun for the full report\" }\n        }",
        "AepExportError::Refused(_) => EngineError::Other(format!(\"{e} (nothing was written; inspect the report before exporting with allowLosses)\")),"
    )
    p = root / "crates/engine/src/cmd/aep.rs"
    s = p.read_text()
    if "use effectcraft_aep::export::{AepExportError, ExportOptions};" not in s:
        s = once(s, "use effectcraft_aep::import::{AepImportError, ImportOptions};\n",
                 "use effectcraft_aep::export::{AepExportError, ExportOptions};\nuse effectcraft_aep::import::{AepImportError, ImportOptions};\n",
                 "AEP export imports")
    if "fn export_aep(s: &mut Session" not in s:
        s = once(s, "pub fn specs() -> Vec<CommandSpec> {", export_fn + "\npub fn specs() -> Vec<CommandSpec> {", "AEP export function")
    old = """        import_aep
    )]
}"""
    new = """        import_aep
    ),
    cmd!(
        "file.exportAep",
        "Adobe After Effects Project...",
        ["File", "Export"],
        None,
        "{path (.aep), allowLosses?: bool, dryRun?: bool}",
        always,
        export_aep
    )]
}"""
    s = once(s, old, new, "AEP export command registration")
    p.write_text(s)

    p = root / "crates/engine/src/menus.rs"
    s = p.read_text()
    s = once(s, "    Add to Render Queue | renderQueue.add\n    Adobe Premiere Pro Project... | file.exportTimeline\n",
             "    Add to Render Queue | renderQueue.add\n    Adobe After Effects Project... | file.exportAep\n    Adobe Premiere Pro Project... | file.exportTimeline\n",
             "AEP export menu row")
    p.write_text(s)

    p = root / "crates/ui-egui/src/menus/frontend.rs"
    s = p.read_text()
    if '"file.exportAep" => ("path", Ask::Save("Project.aep".into())),' not in s:
        s = once(s, '        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),\n',
                 '        "file.exportAep" => ("path", Ask::Save("Project.aep".into())),\n        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),\n',
                 "AEP save picker")
        p.write_text(s)

    p = root / "crates/ui-egui/src/panels/aep_losses.rs"
    s = p.read_text()
    if 'Some("file.exportAep")' not in s:
        marker = """    } else {
        None
    };
    let Some(command) = command else { return Ok(false) };
"""
        repl = """    } else if id == "file.exportAep" {
        Some("file.exportAep")
    } else {
        None
    };
    let Some(command) = command else { return Ok(false) };
"""
        s = once(s, marker, repl, "AEP export loss prompt")
        p.write_text(s)

def main():
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    upstream = Path(os.environ["AEP_EXPORT_SOURCE_DIR"]).resolve()
    if not root.is_dir() or not upstream.is_dir():
        raise SystemExit("Required source checkouts are missing")
    patch_aep(root, upstream)
    patch_engine(root, upstream)
    print("Installed native After Effects .aep export modules and command.")

if __name__ == "__main__":
    main()
