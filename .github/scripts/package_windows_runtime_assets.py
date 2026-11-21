#!/usr/bin/env python3
"""Stage checksum-verified Box64, source FEXCore and Windows AEX host artifacts into Ae assets."""
from __future__ import annotations
import argparse
import hashlib
import re
import shutil
import subprocess
import os
import tempfile
import struct
from pathlib import Path

BOX32_SHA256 = "0bfccfc0693c5ec9efc2c85de651704e9d4c279b27185878af228241a1237ae5"

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

def normalize_termux_symlinks(usr_root: Path) -> None:
    """Convert Termux absolute-prefix symlinks to safe relocatable links inside usr/."""
    usr_root = usr_root.resolve()
    prefixes = (
        "/data/data/com.artcraft.effectcraft/files/windows-compat/usr",
        "/data/user/0/com.artcraft.effectcraft/files/windows-compat/usr",
        "/data/data/com.termux/files/usr",
        "/data/user/0/com.termux/files/usr",
        "/usr",
    )
    for link in usr_root.rglob("*"):
        if not link.is_symlink():
            continue
        target = os.readlink(link)
        if target.startswith("/"):
            mapped = None
            for prefix in prefixes:
                if target == prefix or target.startswith(prefix + "/"):
                    suffix = target[len(prefix):].lstrip("/")
                    mapped = usr_root / suffix
                    break
            if mapped is None:
                raise SystemExit(f"QEMU runtime contains an absolute symlink outside the relocatable Termux usr prefix: {link} -> {target}")
            mapped = Path(os.path.normpath(str(mapped)))
            if not mapped.is_relative_to(usr_root):
                raise SystemExit(f"QEMU runtime symlink escapes usr/: {link} -> {target}")
            relative_target = os.path.relpath(mapped, link.parent)
            link.unlink()
            link.symlink_to(relative_target)
            target = relative_target
        resolved = Path(os.path.normpath(str(link.parent / target)))
        if not resolved.is_relative_to(usr_root):
            raise SystemExit(f"QEMU runtime relative symlink escapes usr/: {link} -> {target}")

def replace_java_hash(path: Path, constant: str, digest: str) -> None:
    source = path.read_text(encoding="utf-8")
    pattern = rf'(private static final String {re.escape(constant)} = ")[0-9a-f]{{64}}(";)'
    updated, count = re.subn(pattern, rf'\g<1>{digest}\g<2>', source, count=1)
    if count != 1:
        raise SystemExit(f"{path}: could not uniquely update {constant}")
    path.write_text(updated, encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--box32-dir", type=Path, required=True)
    parser.add_argument("--fexcore-dir", type=Path, required=True)
    parser.add_argument("--box86-dir", type=Path, default=None)
    parser.add_argument("--qemu-dir", type=Path, default=None)
    parser.add_argument("--x64-host-dir", type=Path, required=True)
    parser.add_argument("--x86-host-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--bridge-java", type=Path, required=True)
    args = parser.parse_args()

    fexcore = require_one(args.fexcore_dir, "fexcore-arm64ec.tar.zst")
    fexcore_sidecar = require_one(args.fexcore_dir, "fexcore-arm64ec.tar.zst.sha256")
    sidecar_match = re.search(r"(?i)\b([0-9a-f]{64})\b", fexcore_sidecar.read_text(encoding="ascii"))
    if not sidecar_match:
        raise SystemExit("FEXCore SHA-256 sidecar is malformed")
    fexcore_hash = sidecar_match.group(1).lower()
    if sha256(fexcore).lower() != fexcore_hash:
        raise SystemExit("FEXCore ARM64EC/WoW64 archive SHA-256 mismatch")
    if fexcore.stat().st_size <= 1024:
        raise SystemExit("FEXCore source-built DLL archive is unexpectedly small")

    box86 = None
    box86_hash = None
    if args.box86_dir is not None and args.box86_dir.is_dir():
        box86_archives = [
            item for item in args.box86_dir.rglob("box86-android-armv7.tar.zst")
            if item.is_file() and not item.is_symlink()
        ]
        if box86_archives:
            if len(box86_archives) != 1:
                raise SystemExit(f"Expected at most one Box86 archive, found {len(box86_archives)}")
            box86 = box86_archives[0]
            box86_sidecar = require_one(args.box86_dir, "box86-android-armv7.tar.zst.sha256")
            box86_match = re.search(r"(?i)\b([0-9a-f]{64})\b", box86_sidecar.read_text(encoding="ascii"))
            if not box86_match:
                raise SystemExit("Box86 SHA-256 sidecar is malformed")
            box86_hash = box86_match.group(1).lower()
            if sha256(box86).lower() != box86_hash:
                raise SystemExit("Box86 ARMv7 archive SHA-256 mismatch")


    qemu_archive = None
    qemu_hash = None
    if args.qemu_dir is not None and args.qemu_dir.is_dir():
        qemu_packages = sorted(
            item for item in args.qemu_dir.rglob("*.deb")
            if item.is_file() and not item.is_symlink()
        )
        if qemu_packages:
            with tempfile.TemporaryDirectory(prefix="ae-qemu-deb-") as temp_dir:
                unpack_root = Path(temp_dir) / "unpacked"
                unpack_root.mkdir(parents=True)
                for package in qemu_packages:
                    subprocess.run(
                        ["dpkg-deb", "-x", str(package), str(unpack_root)],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                binaries = list(unpack_root.rglob("qemu-x86_64"))
                if len(binaries) != 1:
                    raise SystemExit(
                        f"Expected exactly one QEMU x86_64 Linux-user binary in the packages, found {len(binaries)}"
                    )
                binary = binaries[0]
                termux_usr = next((parent for parent in binary.parents if parent.name == "usr"), None)
                if termux_usr is None or not termux_usr.is_dir():
                    raise SystemExit("QEMU package did not contain an identifiable usr runtime prefix")
                normalized = Path(temp_dir) / "normalized"
                shutil.copytree(termux_usr, normalized / "usr", symlinks=True)
                normalize_termux_symlinks(normalized / "usr")
                readelf = subprocess.run(
                    ["readelf", "-h", str(normalized / "usr/bin/qemu-x86_64")],
                    check=True, capture_output=True, text=True,
                ).stdout
                if "ELF64" not in readelf or "AArch64" not in readelf:
                    raise SystemExit("QEMU user-mode binary is not Android ARM64 ELF64")
                staging = Path(temp_dir) / "qemu-stage"
                staging.mkdir()
                shutil.copytree(normalized / "usr", staging / "usr", symlinks=True)
                (staging / "README.txt").write_text(
                    "QEMU x86_64 Linux-user runtime for Android ARM64.\\n"
                    "This translates Linux x86_64 ELF programs; it is not a Windows PE loader.\\n"
                    "A matching x86_64 Wine/glibc guest rootfs is still required for Windows AEX hosting.\\n",
                    encoding="utf-8",
                )
                archive_path = Path(temp_dir) / "qemu-android-arm64.tar.zst"
                subprocess.run(
                    ["tar", "--zstd", "-cf", str(archive_path), "-C", str(staging), "."],
                    check=True,
                )
                qemu_hash = sha256(archive_path)
                qemu_archive = Path(tempfile.gettempdir()) / f"ae-qemu-{qemu_hash}.tar.zst"
                shutil.copyfile(archive_path, qemu_archive)

    box32 = require_one(args.box32_dir, "box64-box32-android-arm64.tar.zst")
    if sha256(box32).lower() != BOX32_SHA256:
        raise SystemExit("BOX32 runtime archive SHA-256 mismatch")
    checksums = list(args.box32_dir.rglob("box64-box32-android-arm64.tar.zst.sha256"))
    if len(checksums) != 1 or BOX32_SHA256 not in checksums[0].read_text(encoding="ascii").lower():
        raise SystemExit("BOX32 checksum sidecar is missing or does not match the pinned digest")

    x64 = require_one(args.x64_host_dir, "effectcraft-aex-host.exe")
    x86 = require_one(args.x86_host_dir, "effectcraft-aex-host.exe")
    validate_pe(x64, 0x8664)
    validate_pe(x86, 0x014C)
    x64_hash, x86_hash = sha256(x64), sha256(x86)

    license_file = require_one(args.x64_host_dir, "AEXLO-MIT-LICENSE")
    if license_file.stat().st_size == 0:
        raise SystemExit("AEXLO MIT license from the pinned source checkout is empty")
    license_hash = sha256(license_file)
    copy_verified(license_file, args.assets_dir / "licenses/AEXLO-MIT-LICENSE", license_hash)
    copy_verified(box32, args.assets_dir / "windows-compat/box64-box32-android-arm64.tar.zst", BOX32_SHA256)
    copy_verified(fexcore, args.assets_dir / "windows-compat/fexcore-arm64ec-wow64.tar.zst", fexcore_hash)
    if box86 is not None and box86_hash is not None:
        copy_verified(box86, args.assets_dir / "windows-compat/box86-android-armv7.tar.zst", box86_hash)
    if qemu_archive is not None and qemu_hash is not None:
        copy_verified(qemu_archive, args.assets_dir / "windows-compat/qemu-x86_64-linux-user-android-arm64.tar.zst", qemu_hash)
        qemu_archive.unlink(missing_ok=True)
    copy_verified(x64, args.assets_dir / "windows-compat/aex-host-x64.exe", x64_hash)
    copy_verified(x86, args.assets_dir / "windows-compat/aex-host-x86.exe", x86_hash)

    # Host binaries are built from a pinned source revision on Windows runners. Their hash is
    # calculated from the artifact in this run and baked into the APK-side asset verifier.
    replace_java_hash(args.bridge_java, "FEXCORE_ASSET_SHA256", fexcore_hash)
    if box86_hash is not None:
        replace_java_hash(args.bridge_java, "BOX86_ASSET_SHA256", box86_hash)
    if qemu_hash is not None:
        replace_java_hash(args.bridge_java, "QEMU_ASSET_SHA256", qemu_hash)
    replace_java_hash(args.bridge_java, "AEX_HOST_X64_SHA256", x64_hash)
    replace_java_hash(args.bridge_java, "AEX_HOST_X86_SHA256", x86_hash)

    sidecars = [
        (args.assets_dir / "windows-compat/box64-box32-android-arm64.tar.zst", BOX32_SHA256),
        (args.assets_dir / "windows-compat/fexcore-arm64ec-wow64.tar.zst", fexcore_hash),
        (args.assets_dir / "windows-compat/aex-host-x64.exe", x64_hash),
        (args.assets_dir / "windows-compat/aex-host-x86.exe", x86_hash),
    ]
    if box86_hash is not None:
        sidecars.append((args.assets_dir / "windows-compat/box86-android-armv7.tar.zst", box86_hash))
    if qemu_hash is not None:
        sidecars.append((args.assets_dir / "windows-compat/qemu-x86_64-linux-user-android-arm64.tar.zst", qemu_hash))
    for source, digest in sidecars:
        sidecar = source.with_name(source.name + ".sha256")
        sidecar.write_text(f"{digest}  {source.name}\n", encoding="ascii")

    license_sidecar = args.assets_dir / "licenses/AEXLO-MIT-LICENSE.sha256"
    license_sidecar.write_text(f"{license_hash}  AEXLO-MIT-LICENSE\n", encoding="ascii")

    print("Verified and staged runtime assets:")
    print(f"  Box64 BOX32 Android ARM64: {BOX32_SHA256}")
    print(f"  Source-built FEXCore ARM64EC/WoW64: {fexcore_hash}")
    print("  Box86 ARMv7 optional fallback: " + (box86_hash or "not packaged in this build"))
    print("  QEMU x86_64 Linux-user optional fallback: " + (qemu_hash or "not packaged in this build"))
    print(f"  Windows x64 AEX host: {x64_hash}")
    print(f"  Windows x86 AEX host: {x86_hash}")
    print(f"  AEXLO MIT license from pinned aexlo source: {license_hash}")
    print("Updated the APK Java asset verifier with the exact host hashes from this workflow run.")

if __name__ == "__main__":
    main()
