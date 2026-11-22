#!/usr/bin/env python3
"""Safely inventory Adobe After Effects plug-in packages without executing them.

This is the intake layer for the Android Ae compatibility pipeline. It deliberately
preserves the distinction between native SDK binaries, scripts, CEP/UXP panels,
presets, and project files. Actual execution/translation is handled by separate
runtimes and must be verified independently.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

MAX_ENTRIES = 4096
MAX_TOTAL = 1024 * 1024 * 1024
MAX_ENTRY = 256 * 1024 * 1024

NATIVE = {".aex", ".pbk", ".pbg", ".dll", ".so", ".dylib"}
SCRIPT = {".jsx", ".jsxbin"}
PRESET = {".ffx"}
PROJECT = {".aep", ".aepx"}
CEP_ARCHIVE = {".zxp"}
UXP_ARCHIVE = {".ccx"}
ARCHIVE = {".zip", ".zxp", ".ccx"}


def safe_member(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name:
        return False
    p = PurePosixPath(name)
    return not p.is_absolute() and all(part not in ("", ".", "..") for part in p.parts)


def family_for(path: str) -> str:
    p = PurePosixPath(path)
    ext = p.suffix.lower()
    parts = {part.lower() for part in p.parts}
    if ext in PROJECT:
        return "project_not_plugin"
    if ext in PRESET:
        return "animation_preset"
    if ext in NATIVE:
        return "native_ae_plugin_candidate"
    if ext in SCRIPT:
        return "extendscript_or_compiled_extendscript"
    if ext in CEP_ARCHIVE or "csxs" in parts or "cep" in parts:
        return "cep_extension_candidate"
    if ext in UXP_ARCHIVE or p.name.lower() == "manifest.json":
        return "uxp_extension_candidate"
    if ext in {".html", ".css", ".js", ".json"} and ("csxs" in parts or "cep" in parts):
        return "cep_extension_resource"
    return "supporting_resource_or_unknown"


def inspect_manifest(name: str, data: bytes) -> dict:
    result = {"path": name, "valid_json": False}
    try:
        obj = json.loads(data.decode("utf-8-sig"))
        result["valid_json"] = isinstance(obj, dict)
        if isinstance(obj, dict):
            for key in ("id", "name", "version", "manifestVersion", "host", "entrypoints", "requiredPermissions"):
                if key in obj:
                    result[key] = obj[key]
    except (UnicodeDecodeError, json.JSONDecodeError):
        result["error"] = "manifest.json is not valid UTF-8 JSON"
    return result


def inspect_zip(path: Path) -> dict:
    files = []
    manifests = []
    skipped = []
    total = 0
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError(f"archive contains more than {MAX_ENTRIES} entries")
        for info in infos:
            if info.is_dir():
                continue
            if not safe_member(info.filename):
                skipped.append({"path": info.filename, "reason": "unsafe archive path"})
                continue
            if info.file_size > MAX_ENTRY:
                skipped.append({"path": info.filename, "reason": "entry exceeds 256 MiB"})
                continue
            total += info.file_size
            if total > MAX_TOTAL:
                raise ValueError("archive expands beyond 1 GiB safety limit")
            family = family_for(info.filename)
            row = {"path": info.filename, "bytes": info.file_size, "family": family}
            files.append(row)
            if PurePosixPath(info.filename).name.lower() == "manifest.json":
                manifests.append(inspect_manifest(info.filename, zf.read(info)))
    return summarize(path.name, files, manifests, skipped, total)


def inspect_directory(path: Path) -> dict:
    files = []
    manifests = []
    skipped = []
    total = 0
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        try:
            rel = item.relative_to(path).as_posix()
            if not safe_member(rel):
                skipped.append({"path": rel, "reason": "unsafe relative path"})
                continue
            size = item.stat().st_size
            if size > MAX_ENTRY:
                skipped.append({"path": rel, "reason": "file exceeds 256 MiB"})
                continue
            total += size
            if total > MAX_TOTAL:
                raise ValueError("directory exceeds 1 GiB inspection limit")
            files.append({"path": rel, "bytes": size, "family": family_for(rel)})
            if item.name.lower() == "manifest.json":
                manifests.append(inspect_manifest(rel, item.read_bytes()))
        except OSError as exc:
            skipped.append({"path": str(item), "reason": str(exc)})
    return summarize(path.name, files, manifests, skipped, total)


def summarize(name: str, files: list[dict], manifests: list[dict], skipped: list[dict], total: int) -> dict:
    counts: dict[str, int] = {}
    for item in files:
        counts[item["family"]] = counts.get(item["family"], 0) + 1
    return {
        "package": name,
        "total_bytes": total,
        "file_count": len(files),
        "counts": counts,
        "files": files,
        "manifests": manifests,
        "skipped": skipped,
        "execution_performed": False,
        "compatibility_status": "inventory_only_not_executed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="A plug-in file, ZIP/ZXP/CCX archive, or extracted package directory")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path (default: stdout)")
    args = parser.parse_args()
    path = args.path
    if path.is_dir():
        report = inspect_directory(path)
    elif path.is_file() and zipfile.is_zipfile(path):
        report = inspect_zip(path)
    elif path.is_file():
        report = summarize(path.name, [{
            "path": path.name,
            "bytes": path.stat().st_size,
            "family": family_for(path.name),
        }], [], [], path.stat().st_size)
    else:
        raise SystemExit(f"Input does not exist: {path}")
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + os.linesep, encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
