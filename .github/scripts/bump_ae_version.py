#!/usr/bin/env python3
"""Bump the Android Ae build from the pinned v0.21.1 source baseline to app version 0.22.1."""
from __future__ import annotations

import re
from pathlib import Path
import os

SOURCE_VERSION = "0.21.1"
TARGET_VERSION = "0.22.1"
PACKAGE_PREFIX = "effectcraft"


def is_effectcraft_workspace_package(block: str) -> bool:
    name = re.search(r'(?m)^name\s*=\s*"([^"]+)"\s*$', block)
    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', block)
    has_source = re.search(r'(?m)^source\s*=', block)
    return bool(
        name
        and version
        and not has_source
        and (name.group(1) == PACKAGE_PREFIX or name.group(1).startswith(PACKAGE_PREFIX + "-"))
        and version.group(1) == SOURCE_VERSION
    )


def bump_workspace_manifest(root: Path) -> None:
    path = root / "Cargo.toml"
    source = path.read_text(encoding="utf-8")
    sections = list(re.finditer(r"(?m)^\[workspace\.package\]\s*$", source))
    if len(sections) != 1:
        raise SystemExit("Could not uniquely locate [workspace.package] in Cargo.toml.")
    start = sections[0].end()
    next_section = re.search(r"(?m)^\[[^\]]+\]\s*$", source[start:])
    end = start + next_section.start() if next_section else len(source)
    section = source[start:end]
    current = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', section)
    if not current:
        raise SystemExit("The workspace package version is missing.")
    if current.group(1) == TARGET_VERSION:
        print("Workspace manifest already targets Ae 0.22.1.")
        return
    if current.group(1) != SOURCE_VERSION:
        raise SystemExit(f"Expected pinned workspace version {SOURCE_VERSION}, found {current.group(1)!r}.")
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
    rebuilt = [parts[0]]
    changed = 0
    remaining_old = []
    for block in parts[1:]:
        if is_effectcraft_workspace_package(block):
            block, count = re.subn(
                rf'(?m)^version\s*=\s*"{re.escape(SOURCE_VERSION)}"\s*$',
                f'version = "{TARGET_VERSION}"',
                block,
                count=1,
            )
            if count != 1:
                raise SystemExit("Could not update a local EffectCraft package in Cargo.lock.")
            changed += 1
        name = re.search(r'(?m)^name\s*=\s*"([^"]+)"\s*$', block)
        version = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', block)
        has_source = re.search(r'(?m)^source\s*=', block)
        if (name and version and not has_source
                and (name.group(1) == PACKAGE_PREFIX or name.group(1).startswith(PACKAGE_PREFIX + "-"))
                and version.group(1) == SOURCE_VERSION):
            remaining_old.append(name.group(1))
        rebuilt.append(block)
    if remaining_old:
        raise SystemExit("Cargo.lock still has old local EffectCraft packages: " + ", ".join(remaining_old))
    if changed:
        path.write_text("[[package]]".join(rebuilt), encoding="utf-8")
        print(f"Updated {changed} local EffectCraft workspace packages in Cargo.lock.")
    else:
        print("Cargo.lock already targets Ae 0.22.1.")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    bump_workspace_manifest(root)
    bump_lockfile(root)
    source = (root / "Cargo.toml").read_text(encoding="utf-8")
    section_start = source.index("[workspace.package]")
    section_end_match = re.search(r"(?m)^\[[^\]]+\]\s*$", source[section_start + len("[workspace.package]"):])
    section_end = section_start + len("[workspace.package]") + (section_end_match.start() if section_end_match else len(source))
    final_section = source[section_start:section_end]
    if not re.search(r'(?m)^version\s*=\s*"0\.22\.1"\s*$', final_section):
        raise SystemExit("Ae version bump verification failed; expected Cargo workspace 0.22.1.")
    print(f"Ae application and workspace version set to {TARGET_VERSION}.")


if __name__ == "__main__":
    main()
