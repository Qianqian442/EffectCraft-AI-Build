#!/usr/bin/env python3
"""Fix Escape handling after the import-review answer became a (continue, auto_replace) tuple."""
from __future__ import annotations
import os
from pathlib import Path

root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
path = root / "crates/ui-egui/src/panels/aep_losses.rs"
source = path.read_text(encoding="utf-8")
if "let mut answer: Option<(bool, bool)>" in source:
    old = "answer = Some(false);"
    new = "answer = Some((false, false));"
    if new not in source:
        if source.count(old) != 1:
            raise SystemExit("Escape cancellation assignment did not match the automatic-replacement dialog")
        source = source.replace(old, new, 1)
        path.write_text(source, encoding="utf-8")
print("Verified Escape cancels import and does not run automatic effect replacement.")
