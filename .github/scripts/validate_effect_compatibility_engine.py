#!/usr/bin/env python3
"""Remove an obsolete experimental candidate-builder stub from the imported-effect adapter."""
from __future__ import annotations
import os
from pathlib import Path

root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
path = root / "crates/engine/src/cmd/effect.rs"
source = path.read_text(encoding="utf-8")
start = source.find("fn compatibility_candidate(")
if start >= 0:
    end = source.find("fn compatibility_replace_all(", start)
    if end < 0:
        raise SystemExit("Found an obsolete compatibility candidate helper but no batch replacement function")
    source = source[:start] + source[end:]
    path.write_text(source, encoding="utf-8")
if "fn compatibility_replace_all(" not in source:
    raise SystemExit("The one-tap effect compatibility engine command is missing")
if '"effect.compatibility.replaceAll"' not in source:
    raise SystemExit("The one-tap effect compatibility command is not registered")
print("Verified that the batch replacement command has no experimental unused candidate stub.")
