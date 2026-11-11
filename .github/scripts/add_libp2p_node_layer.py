#!/usr/bin/env python3
"""Add pinned native libp2p dependencies for EffectCraft node discovery."""
from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    manifest = root / "crates/ui-egui/Cargo.toml"
    cargo = manifest.read_text(encoding="utf-8")
    marker = "[target.'cfg(not(target_arch = \"wasm32\"))'.dependencies]\n"
    if marker not in cargo:
        raise SystemExit("native dependency section not found in ui-egui/Cargo.toml")

    dependency = (
        'libp2p = { version = "=0.56.0", default-features = false, '
        'features = ["tokio", "tcp", "quic", "dns", "noise", "yamux", '
        '"relay", "dcutr", "autonat", "identify", "macros", "ed25519"] }\n'
    )
    if 'libp2p = { version = "=0.56.0"' not in cargo:
        cargo = cargo.replace(marker, marker + dependency, 1)
        manifest.write_text(cargo, encoding="utf-8")

    print("Pinned native rust-libp2p dependency installed for Android peer identity and transport.")
    

if __name__ == "__main__":
    main()
