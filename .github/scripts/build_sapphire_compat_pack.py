#!/usr/bin/env python3
"""Compile the built-in Android Sapphire-compatible visual-effect modules to sandboxed WASM."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

VARIANTS = {
    "glow": "org.effectcraft.sapphire.compat.glow",
    "aura": "org.effectcraft.sapphire.compat.glow-aura",
    "lensflare": "org.effectcraft.sapphire.compat.lensflare",
    "blur": "org.effectcraft.sapphire.compat.blur",
    "distort": "org.effectcraft.sapphire.compat.distort",
    "stylize": "org.effectcraft.sapphire.compat.stylize",
}

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    source = Path(__file__).with_name("sapphire_compat_pack.rs")
    if not source.is_file():
        raise SystemExit(f"Missing Sapphire compatibility source: {source}")
    output = root / "assets" / "sapphire-compat"
    output.mkdir(parents=True, exist_ok=True)
    rustc = os.environ.get("RUSTC", "rustc")

    records = []
    for name, effect_id in VARIANTS.items():
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
        "version": "1.3.0",
        "format": "EffectCraft sandboxed WebAssembly effect modules",
        "desktop_binary_support": False,
        "effects": records,
    }
    manifest_path = output / "bundle.json"
    manifest_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built and validated {len(records)} built-in compatibility effects in {output}")

if __name__ == "__main__":
    main()
