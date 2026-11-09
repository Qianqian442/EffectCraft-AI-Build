#!/usr/bin/env python3
"""Route supported external project files through the existing Import Project control."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_UNIFIED_PROJECT_PICKER_AEP_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one matching source block, found {count}")
    return source.replace(old, new, 1)


def patch_frontend(root: Path) -> None:
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Unified project import picker already patched.")
        return

    # Keep the original File > Import Project command and its existing UI location.
    # Native EffectCraft projects remain on file.importProject; AE files are routed to
    # EffectCraft's existing After Effects importer so its loss-report dialog is preserved.
    old_picker = '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"])),'
    new_picker = (
        '// EFFECTCRAFT_ANDROID_UNIFIED_PROJECT_PICKER_AEP_V1\n'
        '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx", "aep", "aepx"])),'
    )
    source = replace_once(source, old_picker, new_picker, "Existing Import Project picker")

    old_dispatch = '''    // Photoshop files ask how to import them first; numbered stills whether to import them as an
    // image sequence.
    let picked = Value::Object(p.clone());
'''
    new_dispatch = '''    // EFFECTCRAFT_ANDROID_UNIFIED_PROJECT_PICKER_AEP_V1
    // Preserve the original Import Project button and position. Route AE project files to the
    // existing AEP importer (including its unsupported-feature/loss confirmation dialog).
    let picked_path = p.get("path").and_then(Value::as_str).unwrap_or_default();
    let picked_ext = std::path::Path::new(picked_path)
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let id = if id == "file.importProject" && matches!(picked_ext.as_str(), "aep" | "aepx") {
        "file.importAep"
    } else {
        id
    };

    // Photoshop files ask how to import them first; numbered stills whether to import them as an
    // image sequence.
    let picked = Value::Object(p.clone());
'''
    source = replace_once(source, old_dispatch, new_dispatch, "Picked-project format dispatch")
    path.write_text(source, encoding="utf-8")
    print("Existing Import Project button now accepts .ecproj/.ecprojx and routes .aep/.aepx to the existing AE importer.")
    print("No toolbar button or layout was moved or duplicated.")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    patch_frontend(root)


if __name__ == "__main__":
    main()
