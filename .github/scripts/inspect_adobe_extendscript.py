#!/usr/bin/env python3
"""Read-only lexical capability scan for Adobe ExtendScript (.jsx) source files.

This is not an ExtendScript parser or runtime. It never evaluates source and
does not claim that EffectCraft's scripting API implements Adobe's AE DOM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MAX_SOURCE_BYTES = 8 * 1024 * 1024

API_GROUPS = {
    "after_effects_project_dom": (
        r"\bapp\s*\.\s*(?:project|activeItem|activeViewer|beginUndoGroup|endUndoGroup|executeCommand|settings)\b",
        r"\b(?:CompItem|FootageItem|AVLayer|TextLayer|ShapeLayer|PropertyGroup|Property|KeyframeEase|MarkerValue)\b",
    ),
    "scriptui_panels": (r"\bScriptUI\b", r"\bnew\s+(?:Window|Panel)\b"),
    "filesystem_access": (r"\b(?:File|Folder)\s*(?:\(|\.|\b)",),
    "external_process_or_bridge": (
        r"\bBridgeTalk\b", r"\bExternalObject\b",
        r"\bsystem\s*\.\s*callSystem\b", r"\b(?:app|system)\s*\.\s*scheduleTask\b",
    ),
    "network_or_socket": (r"\bSocket\b", r"\b(?:Socket|BridgeTalk)\s*\.\s*(?:open|send)\b"),
    "extendscript_runtime_globals": (
        r"\b\$\s*\.\s*(?:global|evalFile|writeln|os|locale)\b",
        r"(?m)^\s*#(?:target|targetengine|include)\b",
    ),
}

REQUIRED_LAYERS = {
    "after_effects_project_dom": "Adobe After Effects scripting DOM bridge",
    "scriptui_panels": "ScriptUI-compatible panel/window adapter",
    "filesystem_access": "permission-scoped File/Folder adapter",
    "external_process_or_bridge": "isolated BridgeTalk/external-process compatibility layer",
    "network_or_socket": "sandboxed network/socket adapter",
    "extendscript_runtime_globals": "ExtendScript runtime globals and directive handling",
}


def strip_comments_and_strings(source: str) -> str:
    # Lexical approximation: preserve directives and code, blank comments and quoted strings.
    pattern = r"""(?s)/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'"""
    return re.sub(pattern, " ", source)


def inspect_jsx(path: Path) -> dict:
    if path.suffix.lower() != ".jsx":
        raise ValueError("input must have a .jsx extension; JSXBIN is not source text")
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError(f"source exceeds {MAX_SOURCE_BYTES // (1024 * 1024)} MiB inspection limit")
    raw = path.read_bytes()
    source = raw.decode("utf-8-sig", errors="replace")
    code = strip_comments_and_strings(source)
    capabilities = []
    for group, patterns in API_GROUPS.items():
        matches = []
        for pattern in patterns:
            matches.extend(match.group(0).strip() for match in re.finditer(pattern, code))
        if matches:
            capabilities.append({
                "capability": group,
                "evidence": sorted(set(matches))[:40],
                "required_layer": REQUIRED_LAYERS[group],
                "status": "requires_compatibility_layer_not_verified",
            })
    return {
        "file": path.name,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": "utf-8-with-replacement",
        "capabilities": capabilities,
        "detected_capability_count": len(capabilities),
        "analysis_status": "lexical_scan_only",
        "execution_performed": False,
        "script_modified": False,
        "warnings": [
            "This scan is not a JavaScript/ExtendScript parser; matches are heuristic.",
            "A detected API reference does not prove that the API is called or supported.",
            "No script was evaluated and no After Effects project was opened or changed.",
            "JSXBIN is compiled ExtendScript and is not decoded by this source scanner.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = inspect_jsx(args.path)
    except (OSError, ValueError) as exc:
        report = {
            "file": args.path.name,
            "analysis_status": "inspection_failed",
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
