#!/usr/bin/env python3
"""Fill the Android composition viewer with the largest aspect-preserving preview."""
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
    // Use the viewer's previously empty margins: keep the comp's aspect ratio and
    // enlarge it until the viewer is filled; overflow is clipped to the existing viewer.
    // Dock geometry, panel boundaries, toolbars, buttons and their hit targets remain unchanged.
    #[cfg(target_os = "android")]
    let fit_padding = 12.0;
    #[cfg(not(target_os = "android"))]
    let fit_padding = 40.0;
    #[cfg(target_os = "android")]
    let fit = ((area.width() - fit_padding) / cw)
        .max((area.height() - fit_padding) / ch)
        .max(0.01);
    #[cfg(not(target_os = "android"))]
    let fit = ((area.width() - fit_padding) / cw)
        .min((area.height() - fit_padding) / ch)
        .max(0.01);'''
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
    required = (
        "EFFECTCRAFT_ANDROID_LARGER_COMPOSITION_NO_CONTROL_SHIFT_V1",
        "let fit_padding = 12.0;",
        "let fit_padding = 40.0;",
        "Dock geometry, panel boundaries, toolbars, buttons and their hit targets remain unchanged.",
        "let fit = ((area.width() - fit_padding) / cw)",
        ".max((area.height() - fit_padding) / ch)",
    )
    missing = [item for item in required if item not in check]
    if missing:
        raise SystemExit(f"Android preview fill verification failed: {missing}")
    print("Android preview now grows into the existing viewer's empty margins without moving controls; non-Android fit behavior is unchanged.")


if __name__ == "__main__":
    main()
