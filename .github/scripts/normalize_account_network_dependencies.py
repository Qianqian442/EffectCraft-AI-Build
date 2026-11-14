#!/usr/bin/env python3
"""Normalize dependencies added by EffectCraft account and public proxy patches."""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

CANONICAL = {
    "ureq": 'ureq = { version = "3.5", features = ["socks-proxy"] }',
    "tungstenite": 'tungstenite = { version = "0.30", default-features = false, features = ["handshake", "rustls-tls-webpki-roots"] }',
    "roxmltree": 'roxmltree = "0.21.2"',
    "zip": 'zip = { version = "9.1.3", default-features = false, features = ["deflate-flate2-zlib-rs"] }',
}
ANCHORS = {
    "ureq": "serde_json = ",
    "tungstenite": "ureq = ",
    "roxmltree": "rayon = ",
    "zip": "wasmi = ",
}


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    manifest = root / "Cargo.toml"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("[workspace.dependencies]")
    except ValueError as exc:
        raise SystemExit("The EffectCraft workspace is missing [workspace.dependencies].") from exc
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    block = lines[start + 1:end]

    # Remove every previous definition of dependencies managed by these patches.
    keys = set(CANONICAL)
    cleaned = []
    for line in block:
        match = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line)
        if match and match.group(1) in keys:
            continue
        cleaned.append(line)
    block = cleaned

    # Insert each dependency exactly once after an upstream anchor.
    for key, canonical in CANONICAL.items():
        anchor = ANCHORS[key]
        positions = [i for i, line in enumerate(block) if line.lstrip().startswith(anchor)]
        if len(positions) != 1:
            raise SystemExit(f"Cannot normalize {key}: expected one {anchor!r} anchor, found {len(positions)}.")
        block.insert(positions[0] + 1, canonical)

    normalized_lines = lines[:start + 1] + block + lines[end:]
    normalized = "\n".join(normalized_lines) + "\n"
    try:
        tomllib.loads(normalized)
    except tomllib.TOMLDecodeError as error:
        line_no = getattr(error, "lineno", None)
        excerpt = ""
        if line_no and 1 <= line_no <= len(normalized_lines):
            left = max(1, line_no - 2)
            right = min(len(normalized_lines), line_no + 2)
            excerpt = "\n".join(f"{i}: {normalized_lines[i - 1]}" for i in range(left, right + 1))
        raise SystemExit(f"Workspace Cargo.toml is still invalid after dependency normalization: {error}\n{excerpt}") from error

    manifest.write_text(normalized, encoding="utf-8")
    print("Workspace Cargo.toml normalized and parsed successfully.")
    print("Exactly one account/network entry each: ureq, tungstenite, roxmltree, zip.")


if __name__ == "__main__":
    main()
