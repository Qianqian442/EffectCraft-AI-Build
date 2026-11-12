#!/usr/bin/env python3
"""Independent PE metadata audit for EffectCraft desktop plug-in imports.

This is a developer-side validation tool only. It never executes a PE file.
Install with: python -m pip install lief
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from itertools import islice

import lief


def audit(path: Path) -> dict:
    binary = lief.parse(str(path))
    if binary is None or not isinstance(binary, lief.PE.Binary):
        raise ValueError(f"{path} is not a PE/COFF image")

    header = binary.header
    optional = binary.optional_header
    imports = []
    for library in binary.imports:
        imports.append({
            "dll": library.name,
            "symbols": [
                entry.name if entry.name else f"ordinal:{entry.ordinal}"
                for entry in islice(library.entries, 512)
            ],
        })

    exports = []
    if binary.has_exports:
        exports = [
            {
                "name": entry.name,
                "address": int(entry.address),
            }
            for entry in islice(binary.exported_functions, 2048)
        ]

    sections = [
        {
            "name": section.name,
            "virtual_address": int(section.virtual_address),
            "virtual_size": int(section.virtual_size),
            "raw_size": int(section.sizeof_raw_data),
            "raw_offset": int(section.pointerto_raw_data),
        }
        for section in binary.sections
    ]

    export_names = {entry["name"] for entry in exports if entry["name"]}
    ae_entrypoints = [
        name for name in (
            "PluginDataEntryFunction2",
            "PluginDataEntryFunction",
            "EffectMain",
            "main",
        ) if name in export_names
    ]

    machine_value = int(header.machine)
    machine = str(header.machine)
    is_64bit = machine_value in (0x8664, 0xAA64, 0xA641, 0xA64E)
    # IMAGE_FILE_DLL is the COFF Characteristics bit 0x2000. Use the numeric
    # PE/COFF ABI value so this tool works across LIEF 0.x and 1.x bindings.
    coff_characteristics = int(header.characteristics)
    return {
        "file": str(path),
        "size": path.stat().st_size,
        "machine": machine,
        "machine_value": machine_value,
        "is_64bit": is_64bit,
        "subsystem": str(optional.subsystem) if optional else None,
        "is_dll": bool(coff_characteristics & 0x2000),
        "entrypoint": int(optional.addressof_entrypoint) if optional else None,
        "sections": sections,
        "imports": imports,
        "exports": exports,
        "ae_entrypoint_candidates": ae_entrypoints,
        "has_tls": bool(binary.has_tls),
        "has_relocations": bool(binary.has_relocations),
        "has_resources": bool(binary.has_resources),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pe_file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = audit(args.pe_file)
    except Exception as exc:  # noqa: BLE001 - command-line audit diagnostics
        print(f"PE audit failed: {exc}", file=sys.stderr)
        return 2

    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)

    print(
        f"PE audit OK: {report['machine']} / "
        f"{len(report['imports'])} imported DLLs / "
        f"{len(report['exports'])} exported symbols",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
