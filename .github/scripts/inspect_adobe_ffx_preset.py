#!/usr/bin/env python3
"""Read-only triage for opaque Adobe After Effects .ffx animation presets.

This tool deliberately does not claim to decode the proprietary preset format.
It records bounded metadata and readable strings to guide a later, licensed
format implementation. It never executes or modifies the input file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_STRINGS = 512
MAX_STRING_LENGTH = 240
ASCII_RUN = re.compile(rb"[\x20-\x7e]{4,}")
UTF16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")


def extract_strings(data: bytes) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip()
        if len(value) < 4 or value in seen or len(found) >= MAX_STRINGS:
            return
        seen.add(value)
        found.append(value[:MAX_STRING_LENGTH])

    for match in ASCII_RUN.finditer(data):
        add(match.group().decode("ascii", errors="replace"))
    for match in UTF16_RUN.finditer(data):
        add(match.group()[::2].decode("ascii", errors="replace"))
    return found


def inspect_ffx(path: Path) -> dict:
    if path.suffix.lower() != ".ffx":
        raise ValueError("input must have an .ffx extension")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"preset exceeds {MAX_FILE_BYTES // (1024 * 1024)} MiB read-only inspection limit")
    data = path.read_bytes()
    strings = extract_strings(data)
    indicators = ("adobe", "after effects", "effect", "keyframe", "opacity",
                  "position", "scale", "rotation", "adbe", "matchname")
    matched = sorted({
        token for token in indicators
        if any(token in value.lower() for value in strings)
    })
    return {
        "file": path.name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_hex": data[:32].hex(),
        "readable_string_count": len(strings),
        "readable_strings": strings,
        "heuristic_indicators": matched,
        "format_status": "opaque_binary_unparsed",
        "translation_status": "not_implemented",
        "execution_performed": False,
        "input_modified": False,
        "warnings": [
            "This is bounded read-only triage, not a decoder for the proprietary FFX format.",
            "Readable strings and keyword matches do not prove that preset properties or keyframes were recovered.",
            "No preset was applied, no project was changed, and no code was executed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = inspect_ffx(args.path)
    except (OSError, ValueError) as exc:
        report = {
            "file": args.path.name,
            "format_status": "inspection_failed",
            "execution_performed": False,
            "error": str(exc),
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
