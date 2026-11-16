#!/usr/bin/env python3
"""Remove the retired Home layout switch; keep the unrelated Home shortcut cleanup."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_HOME_LAYOUT_SURFACE_MENU_V4"


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/panels/home.rs"
    if not path.is_file():
        raise SystemExit(f"EffectCraft Home panel source is missing: {path}")
    source = path.read_text(encoding="utf-8")

    # The layout chooser now lives in the editing toolbar. If a prior patch has
    # already inserted the Home surface chooser, remove only that exact block.
    if MARKER in source:
        begin = source.index("    // " + MARKER)
        end_marker = "    run_actions(app, &ctx, actions);"
        end = source.find(end_marker, begin)
        if end < 0:
            raise SystemExit("Could not find the end of the obsolete Home layout selector.")
        source = source[:begin] + source[end:]

    # Retain the previously requested removal of the obsolete GitHub shortcut.
    github_entry = '        (Icon::Code, "EffectCraft on GitHub", "help.github"),\n'
    if github_entry in source:
        source = source.replace(github_entry, "", 1)
    elif '"EffectCraft on GitHub"' in source or '"help.github"' in source:
        raise SystemExit("The Home GitHub link changed unexpectedly; refusing an unsafe partial removal.")

    if MARKER in source:
        raise SystemExit("The obsolete Home layout selector is still present.")
    path.write_text(source, encoding="utf-8")
    print("Verified no layout selector is drawn on the Home screen.")
    print("Removed the obsolete EffectCraft GitHub/code-repository shortcut from Home.")


if __name__ == "__main__":
    main()
