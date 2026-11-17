#!/usr/bin/env python3
"""Show the Ae×am in-app brand only on the independent AM editing surface."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_AM_LAYOUT_BRAND_AE_X_AM_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source and old not in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/am_editor.rs"
    if not path.is_file():
        raise SystemExit(f"Independent AM editor source not found: {path}")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("AM page already carries the Ae×am brand.")
        return

    source = replace_once(
        source,
        'let layout_rect = Rect::from_min_size(pos2(rect.min.x + 43.0, rect.min.y + 7.0), vec2(62.0, 30.0));',
        'let layout_rect = Rect::from_min_size(pos2(rect.min.x + 43.0, rect.min.y + 7.0), vec2(82.0, 30.0));',
        "widen AM layout selector for Ae×am label",
    )
    source = replace_once(
        source,
        'let layout_response = button(ui, layout_rect, "AM ▾", "am-layout");',
        'let layout_response = button(ui, layout_rect, "Ae×am ▾", "am-layout");',
        "brand the AM layout selector",
    )
    source = "// " + MARKER + "\n" + source

    if 'button(ui, layout_rect, "Ae×am ▾", "am-layout")' not in source:
        raise SystemExit("Ae×am selector label was not installed.")
    if 'button(ui, layout_rect, "AM ▾", "am-layout")' in source:
        raise SystemExit("Old AM-only selector label remains.")
    path.write_text(source, encoding="utf-8")
    print("AM editing surface now displays Ae×am; the original Ae workspace and launcher label are unchanged.")


if __name__ == "__main__":
    main()
