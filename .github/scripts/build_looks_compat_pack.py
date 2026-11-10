#!/usr/bin/env python3
"""Compile and validate the expanded Looks-style Android grading module."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

EFFECT_ID = "org.effectcraft.looks.studio"


def load_manifest(source: str) -> dict:
    match = re.search(r'const MANIFEST: &str = r#"(.*?)"#;', source, re.S)
    if not match:
        raise SystemExit("Looks source has no embedded plugin manifest")
    try:
        manifest = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Looks plugin manifest is invalid JSON: {exc}") from exc
    if manifest.get("id") != EFFECT_ID or manifest.get("api") != 1:
        raise SystemExit("Looks plugin manifest id or API version is incorrect")
    params = manifest.get("params", [])
    ids = [item.get("id") for item in params]
    if len(ids) != len(set(ids)):
        raise SystemExit("Looks plugin manifest contains duplicate parameter ids")
    flat_count = sum(4 if item.get("type") == "color" else 1 for item in params)
    needed = re.search(r"const PARAMS_NEEDED: usize = (\d+);", source)
    if not needed or int(needed.group(1)) != flat_count:
        raise SystemExit(f"Looks parameter layout mismatch: manifest has {flat_count} values")
    if len(params) < 60:
        raise SystemExit(f"Expanded Looks manifest unexpectedly has only {len(params)} controls")
    required = {
        "preset", "exposure", "temperature", "shadow_color", "highlight_color",
        "hsl_red_hue", "hsl_blue_sat", "curve_midtones", "grain", "vignette",
        "bloom", "halation", "dehaze", "clarity", "sharpen",
    }
    missing = required.difference(ids)
    if missing:
        raise SystemExit("Looks manifest is missing controls: " + ", ".join(sorted(missing)))
    return manifest


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    source = Path(__file__).with_name("looks_compat_pack.rs")
    if not source.is_file():
        raise SystemExit(f"Missing Looks-style effect source: {source}")

    source_text = source.read_text(encoding="utf-8")
    manifest = load_manifest(source_text)
    output = root / "assets" / "looks-compat"
    output.mkdir(parents=True, exist_ok=True)
    target = output / "ec_looks_studio.wasm"
    rustc = os.environ.get("RUSTC", "rustc")
    command = [
        rustc, "--edition=2024", "--target=wasm32-unknown-unknown",
        "--crate-type=cdylib", "-C", "opt-level=z", "-C", "panic=abort",
        str(source), "-o", str(target),
    ]
    print("Building:", " ".join(command))
    subprocess.run(command, check=True)

    data = target.read_bytes()
    if len(data) < 1024 or data[:8] != b"\\x00asm\\x01\\x00\\x00\\x00":
        raise SystemExit(f"Invalid or unexpectedly small Looks WASM module: {target}")
    for token in (EFFECT_ID, "HSL", "曲线", "色彩分级", "胶片光晕", "高光泛光"):
        if token.encode("utf-8") not in data:
            raise SystemExit(f"Looks WASM is missing manifest feature token: {token}")
    for export in (b"ec_api_version", b"ec_manifest_ptr", b"ec_manifest_len", b"ec_alloc", b"ec_render"):
        if export not in data:
            raise SystemExit(f"WASM export missing: {export.decode()} in {target.name}")

    bundle = {
        "name": "EffectCraft Looks Studio",
        "version": manifest["version"],
        "format": "EffectCraft sandboxed WebAssembly effect module",
        "desktop_binary_support": False,
        "parameter_count": len(manifest["params"]),
        "flattened_value_count": sum(4 if item.get("type") == "color" else 1 for item in manifest["params"]),
        "effects": [{
            "id": EFFECT_ID, "file": target.name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "api": 1,
        }],
    }
    (output / "bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8"
    )
    print(
        f"Built Looks Studio {manifest['version']} with "
        f"{len(manifest['params'])} controls / "
        f"{bundle['flattened_value_count']} values: {target} ({len(data)} bytes)"
    )


if __name__ == "__main__":
    main()
