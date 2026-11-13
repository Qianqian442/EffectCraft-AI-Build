#!/usr/bin/env python3
"""Verify and stage Box64 BOX32 + x86/x64 AEX host build artifacts into APK assets."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import tarfile
from pathlib import Path
from zipfile import ZipFile

BOX32_SHA256 = "0bfccfc0693c5ec9efc2c85de651704e9d4c279b27185878af228241a1237ae5"
X64_HOST_SHA256 = "ed8875e9346f117cb4f61a766dd271a746fecab2db315e6e9fd753b90101511f"
X86_HOST_SHA256 = "d067d8e9e7cf02ab11026dde0b8d6ca5975ecf04cc9e634dac4d0dcf261a1131"
LICENSE_SHA256 = "a49e3f389052312d1803772b91b4773cef5fa66076cbd961720484c43ef925fb"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_one(root: Path, name: str) -> Path:
    matches = [p for p in root.rglob(name) if p.is_file() and not p.is_symlink()]
    if len(matches) != 1:
        raise SystemExit(f"{root}: expected exactly one {name}, found {len(matches)}")
    return matches[0]


def validate_pe(path: Path, expected_machine: int) -> None:
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise SystemExit(f"{path}: invalid DOS header")
        pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
        if pe_offset < 64 or pe_offset > path.stat().st_size - 6:
            raise SystemExit(f"{path}: invalid PE header offset")
        stream.seek(pe_offset)
        pe_header = stream.read(6)
    if len(pe_header) != 6 or pe_header[:4] != b"PE\0\0":
        raise SystemExit(f"{path}: missing PE signature")
    machine = struct.unpack_from("<H", pe_header, 4)[0]
    if machine != expected_machine:
        raise SystemExit(f"{path}: expected PE machine 0x{expected_machine:04x}, got 0x{machine:04x}")


def copy_verified(source: Path, destination: Path, expected: str) -> None:
    actual = sha256(source)
    if actual.lower() != expected.lower():
        raise SystemExit(f"{source}: SHA-256 mismatch expected {expected}, got {actual}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256(destination).lower() != expected.lower():
        raise SystemExit(f"{destination}: destination hash changed during copy")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--box32-dir", type=Path, required=True)
    parser.add_argument("--x64-host-dir", type=Path, required=True)
    parser.add_argument("--x86-host-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    args = parser.parse_args()

    box32 = require_one(args.box32_dir, "box64-box32-android-arm64.tar.zst")
    if sha256(box32).lower() != BOX32_SHA256:
        raise SystemExit("BOX32 runtime archive SHA-256 mismatch")
    # The separately generated checksum file must also agree with the pinned value.
    checksum_candidates = list(args.box32_dir.rglob("box64-box32-android-arm64.tar.zst.sha256"))
    if len(checksum_candidates) != 1:
        raise SystemExit(f"Expected exactly one BOX32 checksum sidecar, found {len(checksum_candidates)}")
    if BOX32_SHA256 not in checksum_candidates[0].read_text(encoding="ascii").lower():
        raise SystemExit("BOX32 archive checksum sidecar does not contain the pinned digest")

    x64 = require_one(args.x64_host_dir, "effectcraft-aex-host.exe")
    # AEX host artifact uses the same basename for both architectures; verify the inputs
    # are separated by run-artifact download directories and use PE Machine + SHA to reject swaps.
    x86 = require_one(args.x86_host_dir, "effectcraft-aex-host.exe")
    validate_pe(x64, 0x8664)
    validate_pe(x86, 0x014C)

    license_x64 = require_one(args.x64_host_dir, "AEXLO-MIT-LICENSE")
    copy_verified(license_x64, args.assets_dir / "licenses/AEXLO-MIT-LICENSE", LICENSE_SHA256)

    copy_verified(box32, args.assets_dir / "windows-compat/box64-box32-android-arm64.tar.zst", BOX32_SHA256)
    copy_verified(x64, args.assets_dir / "windows-compat/aex-host-x64.exe", X64_HOST_SHA256)
    copy_verified(x86, args.assets_dir / "windows-compat/aex-host-x86.exe", X86_HOST_SHA256)

    print("Verified Windows runtime APK assets:")
    print(f"  BOX32 Android ARM64: {BOX32_SHA256}")
    print(f"  Windows x64 AEX host: {X64_HOST_SHA256}")
    print(f"  Windows x86 AEX host: {X86_HOST_SHA256}")
    print(f"  AEXLO MIT license: {LICENSE_SHA256}")


if __name__ == "__main__":
    main()
