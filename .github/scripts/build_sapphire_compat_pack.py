#!/usr/bin/env python3
"""Compile the built-in Android Sapphire-compatible visual-effect modules to sandboxed WASM."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

VARIANTS = {
    "glow": "org.effectcraft.sapphire.compat.glow",
    "aura": "org.effectcraft.sapphire.compat.glow-aura",
    "lensflare": "org.effectcraft.sapphire.compat.lensflare",
    "blur": "org.effectcraft.sapphire.compat.blur",
    "distort": "org.effectcraft.sapphire.compat.distort",
    "stylize": "org.effectcraft.sapphire.compat.stylize",
    "glint": "org.effectcraft.sapphire.compat.glint",
    "rays": "org.effectcraft.sapphire.compat.rays",
    "halftone": "org.effectcraft.sapphire.compat.halftone",
    "pixelsort": "org.effectcraft.sapphire.compat.pixelsort",
}

EXPECTED_FLATTENED_PARAMS = {
    "glow": 3, "aura": 7, "lensflare": 8, "blur": 2, "distort": 5,
    "stylize": 3, "glint": 30, "rays": 31, "halftone": 18, "pixelsort": 20,
}
PARAM_WIDTH = {"slider": 1, "angle": 1, "checkbox": 1, "popup": 1, "point": 2, "color": 4}

def parse_and_validate_manifest(source_text: str, name: str, effect_id: str) -> dict:
    pattern = rf'#\[cfg\({re.escape("sapphire_" + name)}\)\]\s*\{{\s*r#"(.*?)"#\s*\}}'
    match = re.search(pattern, source_text, re.DOTALL)
    if not match:
        raise SystemExit(f"Missing Rust manifest block for {name}")
    try:
        manifest = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid JSON manifest for {name}: {error}") from error
    if manifest.get("api") != 1 or manifest.get("id") != effect_id:
        raise SystemExit(f"Manifest identity/API mismatch for {name}")
    params = manifest.get("params")
    if not isinstance(params, list) or not params:
        raise SystemExit(f"Manifest parameters missing for {name}")
    ids = [param.get("id") for param in params]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise SystemExit(f"Parameter IDs must be non-empty and unique for {name}")
    flattened = 0
    for param in params:
        kind = param.get("type")
        if kind not in PARAM_WIDTH:
            raise SystemExit(f"Unsupported parameter type {kind!r} in {name}")
        if kind == "slider":
            minimum, maximum, default = param.get("min"), param.get("max"), param.get("default")
            if not all(isinstance(value, (int, float)) for value in (minimum, maximum, default)):
                raise SystemExit(f"Slider requires numeric min/max/default in {name}: {param.get('id')}")
            if minimum > maximum or not minimum <= default <= maximum:
                raise SystemExit(f"Slider bounds/default invalid in {name}: {param.get('id')}")
        if kind == "popup":
            options = param.get("options")
            if not isinstance(options, list) or not options:
                raise SystemExit(f"Popup requires options in {name}: {param.get('id')}")
        flattened += PARAM_WIDTH[kind]
    expected = EXPECTED_FLATTENED_PARAMS[name]
    if flattened != expected:
        raise SystemExit(f"{name} flattens to {flattened} values; renderer expects {expected}")
    return manifest

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    source = Path(__file__).with_name("sapphire_compat_pack.rs")
    if not source.is_file():
        raise SystemExit(f"Missing Sapphire compatibility source: {source}")
    output = root / "assets" / "sapphire-compat"
    output.mkdir(parents=True, exist_ok=True)
    rustc = os.environ.get("RUSTC", "rustc")

    records = []
    source_text = source.read_text(encoding="utf-8")
    for name, effect_id in VARIANTS.items():
        parse_and_validate_manifest(source_text, name, effect_id)
        target = output / f"ec_sapphire_{name}.wasm"
        command = [
            rustc, "--edition=2024", "--target=wasm32-unknown-unknown",
            "--crate-type=cdylib", "-C", "opt-level=z", "-C", "panic=abort",
            "--cfg", f"sapphire_{name}", str(source), "-o", str(target),
        ]
        print("Building:", " ".join(command))
        subprocess.run(command, check=True)
        data = target.read_bytes()
        if len(data) < 1024 or data[:8] != b"\x00asm\x01\x00\x00\x00":
            raise SystemExit(f"Invalid or unexpectedly small WASM module: {target}")
        if effect_id.encode("utf-8") not in data:
            raise SystemExit(f"WASM does not contain its expected effect id: {effect_id}")
        for export in (b"ec_api_version", b"ec_manifest_ptr", b"ec_manifest_len", b"ec_alloc", b"ec_render"):
            if export not in data:
                raise SystemExit(f"WASM export missing: {export.decode()} in {target.name}")
        records.append({
            "id": effect_id,
            "file": target.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "api": 1,
        })

    bundle = {
        "name": "EffectCraft Sapphire-compatible effects",
        "version": "2.0.0",
        "format": "EffectCraft sandboxed WebAssembly effect modules",
        "desktop_binary_support": False,
        "effects": records,
    }
    manifest_path = output / "bundle.json"
    manifest_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built and validated {len(records)} built-in compatibility effects in {output}")

if __name__ == "__main__":
    main()
