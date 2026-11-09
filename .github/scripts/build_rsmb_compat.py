#!/usr/bin/env python3
"""Compile the standalone Android RSMB-style directional-blur compatibility effect."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


EFFECT_ID = "org.effectcraft.compat.rsmb-motion-blur"


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    source = Path(__file__).with_name("sapphire_compat_pack.rs")
    if not source.is_file():
        raise SystemExit(f"Missing RSMB compatibility renderer source: {source}")

    output = root / "assets" / "rsmb-compat"
    output.mkdir(parents=True, exist_ok=True)
    target = output / "ec_rsmb_motion_blur.wasm"
    rustc = os.environ.get("RUSTC", "rustc")
    command = [
        rustc, "--edition=2024", "--target=wasm32-unknown-unknown",
        "--crate-type=cdylib", "-C", "opt-level=z", "-C", "panic=abort",
        "--cfg", "sapphire_motion", str(source), "-o", str(target),
    ]
    print("Building standalone RSMB compatibility effect:", " ".join(command))
    subprocess.run(command, check=True)

    data = target.read_bytes()
    if len(data) < 1024 or data[:8] != b"\x00asm\x01\x00\x00\x00":
        raise SystemExit(f"Invalid or unexpectedly small RSMB WASM module: {target}")
    if EFFECT_ID.encode("utf-8") not in data:
        raise SystemExit(f"RSMB WASM does not contain its expected standalone effect id: {EFFECT_ID}")
    for export in (b"ec_api_version", b"ec_manifest_ptr", b"ec_manifest_len", b"ec_alloc", b"ec_render"):
        if export not in data:
            raise SystemExit(f"RSMB WASM export missing: {export.decode()}")

    bundle = {
        "name": "EffectCraft RSMB-style directional blur compatibility effect",
        "version": "1.0.0",
        "format": "EffectCraft sandboxed WebAssembly effect module",
        "desktop_binary_support": False,
        "notice": "Android directional-blur recreation only; it is not the original RE:Vision Effects RSMB plug-in or its motion-vector estimation.",
        "effects": [{
            "id": EFFECT_ID,
            "file": target.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "api": 1,
        }],
    }
    (output / "bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built standalone RSMB compatibility module at {target}")


if __name__ == "__main__":
    main()
