#!/usr/bin/env python3
"""Static PE/COFF inspection for Adobe After Effects Windows .aex candidates.

No native code is loaded or executed. The report is an input to the existing
aggressive-port/reconstruction and compatibility-route comparison pipeline.
It does not claim that a binary is runnable or that disassembly equals a port.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

MACHINE = {
    0x014C: "x86",
    0x8664: "x86_64",
    0x01C0: "arm",
    0x01C4: "armv7",
    0xAA64: "arm64",
}
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_SECTIONS = 96
MAX_IMPORTS = 4096
MAX_EXPORTS = 8192


class PEError(ValueError):
    pass


def u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise PEError("truncated 16-bit field")
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise PEError("truncated 32-bit field")
    return struct.unpack_from("<I", data, offset)[0]


def cstring(data: bytes, offset: int, limit: int = 4096) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset, min(len(data), offset + limit))
    if end < 0:
        end = min(len(data), offset + limit)
    return data[offset:end].decode("ascii", errors="replace")


def inspect_pe(path: Path) -> dict:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise PEError(f"file exceeds {MAX_FILE_BYTES // (1024 * 1024)} MiB static-inspection limit")
    data = path.read_bytes()
    result = {
        "file": path.name,
        "size": len(data),
        "format": "unknown",
        "execution_performed": False,
        "compatibility_status": "static_analysis_only",
        "porting_route": "requires_sdk_host_adapter_and_architecture_bridge",
    }
    if len(data) < 64 or data[:2] != b"MZ":
        result["error"] = "missing DOS MZ header"
        return result
    pe_offset = u32(data, 0x3C)
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        result["error"] = "missing or truncated PE signature"
        return result

    coff = pe_offset + 4
    machine = u16(data, coff)
    section_count = u16(data, coff + 2)
    optional_size = u16(data, coff + 16)
    if section_count > MAX_SECTIONS:
        raise PEError(f"unreasonable section count: {section_count}")
    optional = coff + 20
    if optional + optional_size > len(data) or optional_size < 96:
        raise PEError("truncated optional header")
    magic = u16(data, optional)
    if magic == 0x10B:
        bits, directory_offset, number_offset = 32, optional + 96, optional + 92
    elif magic == 0x20B:
        bits, directory_offset, number_offset = 64, optional + 112, optional + 108
    else:
        raise PEError(f"unsupported PE optional-header magic 0x{magic:04x}")

    section_table = optional + optional_size
    sections = []
    for index in range(section_count):
        off = section_table + index * 40
        if off + 40 > len(data):
            raise PEError("truncated section table")
        name = data[off:off + 8].split(b"\0", 1)[0].decode("ascii", "replace")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from("<IIII", data, off + 8)
        sections.append({
            "name": name, "virtual_address": virtual_address,
            "virtual_size": virtual_size, "raw_offset": raw_offset, "raw_size": raw_size,
        })

    def rva_to_offset(rva: int) -> int | None:
        if rva == 0:
            return None
        for section in sections:
            start = section["virtual_address"]
            span = max(section["virtual_size"], section["raw_size"])
            if start <= rva < start + span:
                offset = section["raw_offset"] + (rva - start)
                if 0 <= offset < len(data):
                    return offset
        if rva < len(data):
            return rva
        return None

    result.update({
        "format": "PE",
        "machine": MACHINE.get(machine, f"unknown_0x{machine:04x}"),
        "machine_code": f"0x{machine:04x}",
        "bitness": bits,
        "sections": sections,
    })

    directory_count = min(u32(data, number_offset), 16)
    directories = []
    for i in range(directory_count):
        off = directory_offset + i * 8
        if off + 8 > optional + optional_size:
            break
        directories.append(struct.unpack_from("<II", data, off))
    imports, exports = [], []
    if len(directories) > 1:
        import_rva, _ = directories[1]
        import_off = rva_to_offset(import_rva)
        if import_off is not None:
            for index in range(MAX_IMPORTS):
                off = import_off + index * 20
                if off + 20 > len(data):
                    break
                original_thunk, _, _, name_rva, _ = struct.unpack_from("<IIIII", data, off)
                if not any((original_thunk, name_rva)):
                    break
                name_off = rva_to_offset(name_rva)
                if name_off is not None:
                    imports.append(cstring(data, name_off))
    if directories:
        export_rva, _ = directories[0]
        export_off = rva_to_offset(export_rva)
        if export_off is not None and export_off + 40 <= len(data):
            fields = struct.unpack_from("<IIHHIIIIIII", data, export_off)
            number_names, names_rva = fields[7], fields[9]
            names_off = rva_to_offset(names_rva)
            if names_off is not None:
                for index in range(min(number_names, MAX_EXPORTS)):
                    name_rva = u32(data, names_off + index * 4)
                    name_off = rva_to_offset(name_rva)
                    if name_off is not None:
                        exports.append(cstring(data, name_off))
    result["imports"] = sorted(set(filter(None, imports)))
    result["exports"] = sorted(set(filter(None, exports)))
    result["pipl_strings"] = sorted({
        token.decode("ascii", "ignore")
        for token in (b"Effect", b"AEGP", b"AEIO", b"PiPL", b"EffectMain")
        if token.lower() in data.lower()
    })
    result["likely_ae_plugin"] = path.suffix.lower() == ".aex" and (
        bool(result["pipl_strings"]) or any(name in result["exports"] for name in ("EffectMain", "EntryPoint"))
    )
    result["warnings"] = [
        "Static PE inspection only; no disassembly, relocation, API emulation, or code execution was performed.",
        "CPU translation does not implement the Adobe After Effects SDK host suites or callback ABI.",
    ]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = inspect_pe(args.path)
    except (OSError, PEError) as exc:
        report = {
            "file": args.path.name,
            "execution_performed": False,
            "compatibility_status": "static_analysis_failed",
            "error": str(exc),
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
