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


def normalize_package_manifest(path: Path) -> None:
    """Merge repeated TOML tables and remove duplicate keys in Cargo package manifests."""
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    table = ""
    seen_tables: set[str] = set()
    seen_keys: dict[str, set[str]] = {}
    array_table_index = 0

    for line_number, line in enumerate(lines, 1):
        header = re.match(r"^\s*(\[\[.*?\]\]|\[.*?\])\s*(?:#.*)?$", line)
        if header:
            token = header.group(1)
            if token.startswith("[["):
                array_table_index += 1
                table = f"{token}#{array_table_index}"
                output.append(line)
                seen_keys.setdefault(table, set())
                continue
            table_name = token[1:-1].strip()
            if table_name in seen_tables:
                # TOML does not allow a normal table to be declared twice.
                # Merge repeated declarations produced by overlapping patches.
                table = table_name
                continue
            seen_tables.add(table_name)
            table = table_name
            seen_keys.setdefault(table, set())
            output.append(line)
            continue

        key_match = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line)
        if key_match:
            key = key_match.group(1)
            keys = seen_keys.setdefault(table, set())
            if key in keys:
                print(f"Removed duplicate Cargo key: {path}:{line_number} [{table}] {key}")
                continue
            keys.add(key)
        output.append(line)

    normalized = "\n".join(output) + "\n"
    try:
        tomllib.loads(normalized)
    except tomllib.TOMLDecodeError as error:
        line_no = getattr(error, "lineno", None)
        excerpt = ""
        if line_no and 1 <= line_no <= len(output):
            left = max(1, line_no - 2)
            right = min(len(output), line_no + 2)
            excerpt = "\n".join(f"{i}: {output[i - 1]}" for i in range(left, right + 1))
        raise SystemExit(f"Invalid Cargo manifest {path}: {error}\n{excerpt}") from error
    path.write_text(normalized, encoding="utf-8")
    print(f"Validated Cargo manifest: {path}")


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

    # The Android builder parses these manifests before creating the launcher.
    # Validate them here, with file/line diagnostics instead of a late build failure.
    normalize_package_manifest(root / "crates/engine/Cargo.toml")
    normalize_package_manifest(root / "crates/ui-egui/Cargo.toml")


if __name__ == "__main__":
    main()
