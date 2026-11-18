#!/usr/bin/env python3
"""Bump the Android Ae build from the pinned v0.21.1 source baseline to app version 0.22.1."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

SOURCE_VERSION = "0.21.1"
TARGET_VERSION = "0.22.1"
PACKAGE_PREFIX = "effectcraft"


def bump_workspace_manifest(root: Path) -> None:
    path = root / "Cargo.toml"
    source = path.read_text(encoding="utf-8")
    metadata = tomllib.loads(source)
    actual = metadata.get("workspace", {}).get("package", {}).get("version")
    if actual == TARGET_VERSION:
        print("Workspace manifest already targets Ae 0.22.1.")
        return
    if actual != SOURCE_VERSION:
        raise SystemExit(f"Expected pinned workspace version {SOURCE_VERSION}, found {actual!r}.")
    sections = list(re.finditer(r"(?m)^\[workspace\.package\]\s*$", source))
    if len(sections) != 1:
        raise SystemExit("Could not uniquely locate [workspace.package] in Cargo.toml.")
    start = sections[0].end()
    next_section = re.search(r"(?m)^\[[^\]]+\]\s*$", source[start:])
    end = start + next_section.start() if next_section else len(source)
    section = source[start:end]
    updated, count = re.subn(
        rf'(?m)^version\s*=\s*"{re.escape(SOURCE_VERSION)}"\s*$',
        f'version = "{TARGET_VERSION}"',
        section,
        count=1,
    )
    if count != 1:
        raise SystemExit("Could not uniquely bump the workspace package version.")
    path.write_text(source[:start] + updated + source[end:], encoding="utf-8")


def bump_lockfile(root: Path) -> None:
    path = root / "Cargo.lock"
    source = path.read_text(encoding="utf-8")
    parts = source.split("[[package]]")
    changed = 0
    rebuilt = [parts[0]]
    for block in parts[1:]:
        parsed = tomllib.loads("[[package]]" + block)
        package = parsed["package"]
        name = package.get("name", "")
        is_workspace_package = (
            name == PACKAGE_PREFIX
            or name.startswith(PACKAGE_PREFIX + "-")
        ) and "source" not in package
        if is_workspace_package and package.get("version") == SOURCE_VERSION:
            block, count = re.subn(
                rf'(?m)^version\s*=\s*"{re.escape(SOURCE_VERSION)}"\s*$',
                f'version = "{TARGET_VERSION}"',
                block,
                count=1,
            )
            if count != 1:
                raise SystemExit(f"Could not update Cargo.lock entry for {name}.")
            changed += 1
        rebuilt.append(block)
    if changed == 0:
        remaining = [
            p for p in tomllib.loads(path.read_text(encoding="utf-8")).get("package", [])
            if p.get("name", "").startswith(PACKAGE_PREFIX)
            and p.get("version") == SOURCE_VERSION
        ]
        if remaining:
            raise SystemExit("Cargo.lock still contains old local EffectCraft package versions.")
        print("Cargo.lock already targets Ae 0.22.1.")
        return
    path.write_text("[[package]]".join(rebuilt), encoding="utf-8")
    print(f"Updated {changed} local EffectCraft workspace packages in Cargo.lock.")


def main() -> None:
    import os

    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    bump_workspace_manifest(root)
    bump_lockfile(root)
    final = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    version = final["workspace"]["package"]["version"]
    if version != TARGET_VERSION:
        raise SystemExit(f"Ae version bump verification failed: {version}")
    print(f"Ae application and workspace version set to {TARGET_VERSION}.")


if __name__ == "__main__":
    main()
