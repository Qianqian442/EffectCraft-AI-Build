#!/usr/bin/env python3
"""Compile the original Looks-style Android color-grading module to sandboxed WASM."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


EFFECT_ID = "org.effectcraft.looks.studio"


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    source = Path(__file__).with_name("looks_compat_pack.rs")
    if not source.is_file():
        raise SystemExit(f"Missing Looks-style effect source: {source}")

    output = root / "assets" / "looks-compat"
    output.mkdir(parents=True, exist_ok=True)
    target = output / "ec_looks_studio.wasm"
    rustc = os.environ.get("RUSTC", "rustc")
    command = [
        rustc,
        "--edition=2024",
        "--target=wasm32-unknown-unknown",
        "--crate-type=cdylib",
        "-C", "opt-level=z",
        "-C", "panic=abort",
        str(source),
        "-o", str(target),
    ]
    print("Building:", " ".join(command))
    subprocess.run(command, check=True)

    data = target.read_bytes()
    if len(data) < 1024 or data[:8] != b"\x00asm\x01\x00\x00\x00":
        raise SystemExit(f"Invalid or unexpectedly small Looks WASM module: {target}")
    if EFFECT_ID.encode("utf-8") not in data:
        raise SystemExit(f"WASM does not contain its expected effect id: {EFFECT_ID}")
    for export in (b"ec_api_version", b"ec_manifest_ptr", b"ec_manifest_len", b"ec_alloc", b"ec_render"):
        if export not in data:
            raise SystemExit(f"WASM export missing: {export.decode()} in {target.name}")

    bundle = {
        "name": "EffectCraft Looks Studio",
        "version": "1.0.0",
        "format": "EffectCraft sandboxed WebAssembly effect module",
        "desktop_binary_support": False,
        "effects": [{
            "id": EFFECT_ID,
            "file": target.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "api": 1,
        }],
    }
    manifest_path = output / "bundle.json"
    manifest_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built and validated Looks-style color-grading effect: {target} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
