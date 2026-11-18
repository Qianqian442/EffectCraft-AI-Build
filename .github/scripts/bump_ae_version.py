#!/usr/bin/env python3
"""Bump the Android Ae build from pinned EffectCraft v0.21.1 to app version 0.22.1."""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

SOURCE_VERSION = "0.21.1"
TARGET_VERSION = "0.22.1"
PACKAGE_PREFIX = "effectcraft"


def package_field(block: str, field: str) -> str | None:
    match = re.search(
        rf'(?m)^[ \t]*{re.escape(field)}[ \t]*=[ \t]*"([^"]+)"[ \t]*$',
        block,
    )
    return match.group(1) if match else None


def is_effectcraft_workspace_package(block: str) -> bool:
    name = package_field(block, "name")
    version = package_field(block, "version")
    has_source = re.search(r"(?m)^[ \t]*source[ \t]*=", block)
    return bool(
        name
        and version
        and not has_source
        and (name == PACKAGE_PREFIX or name.startswith(PACKAGE_PREFIX + "-"))
        and version == SOURCE_VERSION
    )


def bump_workspace_manifest(root: Path) -> None:
    path = root / "Cargo.toml"
    source = path.read_text(encoding="utf-8")
    sections = list(re.finditer(r"(?m)^\[workspace\.package\][ \t]*$", source))
    if len(sections) != 1:
        raise SystemExit("Could not uniquely locate [workspace.package] in Cargo.toml.")
    start = sections[0].end()
    next_section = re.search(r"(?m)^\[[^\]]+\][ \t]*$", source[start:])
    end = start + next_section.start() if next_section else len(source)
    section = source[start:end]
    current = package_field(section, "version")
    if current == TARGET_VERSION:
        print("Workspace manifest already targets Ae 0.22.1.")
        return
    if current != SOURCE_VERSION:
        raise SystemExit(
            f"Expected pinned workspace version {SOURCE_VERSION}, found {current!r}."
        )
    updated, count = re.subn(
        rf'(?m)^[ \t]*version[ \t]*=[ \t]*"{re.escape(SOURCE_VERSION)}"[ \t]*$',
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
    remaining_old: list[str] = []

    for block in parts[1:]:
        if is_effectcraft_workspace_package(block):
            # IMPORTANT: [ \t]* is intentional. Using \s* here consumes the blank
            # lines before the next [[package]] header and corrupts Cargo.lock.
            block, count = re.subn(
                rf'(?m)^[ \t]*version[ \t]*=[ \t]*"{re.escape(SOURCE_VERSION)}"[ \t]*$',
                f'version = "{TARGET_VERSION}"',
                block,
                count=1,
            )
            if count != 1:
                raise SystemExit("Could not update a local EffectCraft package in Cargo.lock.")
            changed += 1

        name = package_field(block, "name")
        version = package_field(block, "version")
        has_source = re.search(r"(?m)^[ \t]*source[ \t]*=", block)
        if (
            name
            and version == SOURCE_VERSION
            and not has_source
            and (name == PACKAGE_PREFIX or name.startswith(PACKAGE_PREFIX + "-"))
        ):
            remaining_old.append(name)
        rebuilt.append(block)

    if remaining_old:
        raise SystemExit(
            "Cargo.lock still has old local EffectCraft packages: "
            + ", ".join(remaining_old)
        )

    updated = "[[package]]".join(rebuilt)
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as error:
        raise SystemExit(
            f"Cargo.lock would be invalid after the version bump: {error}"
        ) from error

    if changed:
        path.write_text(updated, encoding="utf-8")
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
    section_start = source.find("[workspace.package]")
    if section_start < 0:
        raise SystemExit("The workspace package section disappeared after the version bump.")
    next_section = re.search(
        r"(?m)^\[[^\]]+\][ \t]*$",
        source[section_start + len("[workspace.package]"):],
    )
    section_end = (
        section_start + len("[workspace.package]") + next_section.start()
        if next_section
        else len(source)
    )
    final_section = source[section_start:section_end]
    if package_field(final_section, "version") != TARGET_VERSION:
        raise SystemExit("Ae version bump verification failed; expected Cargo workspace 0.22.1.")
    print(f"Ae application and workspace version set to {TARGET_VERSION}.")


if __name__ == "__main__":
    main()
