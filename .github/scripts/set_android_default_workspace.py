#!/usr/bin/env python3
"""Enlarge only the Android composition image while keeping every UI control in place."""
from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")

    path = root / "crates/ui-egui/src/panels/viewer.rs"
    source = path.read_text(encoding="utf-8")
    old = '    let fit = ((area.width() - 40.0) / cw).min((area.height() - 40.0) / ch).max(0.01);'
    new = '''    // EFFECTCRAFT_ANDROID_LARGER_COMPOSITION_NO_CONTROL_SHIFT_V1
    // Reduce only the empty margin around the composition image. Dock geometry, panel
    // boundaries, toolbars, buttons and their hit targets remain unchanged.
    #[cfg(target_os = "android")]
    let fit_padding = 12.0;
    #[cfg(not(target_os = "android"))]
    let fit_padding = 40.0;
    let fit = ((area.width() - fit_padding) / cw).min((area.height() - fit_padding) / ch).max(0.01);'''
    count = source.count(old)
    if count == 0:
        if "EFFECTCRAFT_ANDROID_LARGER_COMPOSITION_NO_CONTROL_SHIFT_V1" not in source:
            raise SystemExit("Could not find the original composition fit calculation")
    elif count != 1:
        raise SystemExit(f"Expected one composition fit calculation, found {count}")
    else:
        source = source.replace(old, new, 1)
        path.write_text(source, encoding="utf-8")

    check = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_LARGER_COMPOSITION_NO_CONTROL_SHIFT_V1" not in check:
        raise SystemExit("Android composition zoom marker missing")
    if 'let fit_padding = 12.0;' not in check or 'let fit_padding = 40.0;' not in check:
        raise SystemExit("Composition fit padding settings were not applied")
    print("Applied a larger Android composition image inside the unchanged viewer area; all controls keep their original positions.")
    

if __name__ == "__main__":
    main()
