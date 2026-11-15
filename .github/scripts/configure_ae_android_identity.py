#!/usr/bin/env python3
"""Set the user-facing Android app label to Ae and advance the app patch version safely."""
from __future__ import annotations

import os
import re
from pathlib import Path


OLD_VERSION = "0.21.1"
NEW_VERSION = "0.21.2"
PACKAGE_ID = "com.artcraft.effectcraft"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if new in source:
        return source
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one safe patch point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    cargo = effectcraft / "Cargo.toml"
    lock = effectcraft / "Cargo.lock"
    generator = builder / "lib/android_project.py"

    if not cargo.is_file() or not lock.is_file() or not generator.is_file():
        raise SystemExit("Missing the EffectCraft Cargo workspace or Android manifest generator.")

    manifest = cargo.read_text(encoding="utf-8")
    version_line = f'version = "{OLD_VERSION}"'
    if version_line in manifest:
        manifest = replace_once(manifest, version_line, f'version = "{NEW_VERSION}"', "workspace patch version")
        cargo.write_text(manifest, encoding="utf-8")
    elif f'version = "{NEW_VERSION}"' not in manifest:
        raise SystemExit("Unexpected workspace version; refusing to make an unsafe version change.")

    lock_text = lock.read_text(encoding="utf-8")
    package_pattern = re.compile(
        r'(?m)(\[\[package\]\]\nname = "effectcraft[^"]*"\nversion = )"0\.21\.1"'
    )
    lock_text, updated = package_pattern.subn(r'\g<1>"0.21.2"', lock_text)
    if updated == 0 and 'name = "effectcraft"\nversion = "0.21.2"' not in lock_text:
        raise SystemExit("Could not find the pinned EffectCraft workspace packages in Cargo.lock.")
    if updated not in (0, 37):
        raise SystemExit(f"Expected 37 EffectCraft workspace lockfile versions to update, found {updated}.")
    if updated:
        lock.write_text(lock_text, encoding="utf-8")

    source = generator.read_text(encoding="utf-8")
    # Use the same application ID and a monotonic versionCode for every APK built
    # from this repository. Android accepts an in-place APK update only when the
    # signing certificate matches and the incoming versionCode is not older.
    source = replace_once(
        source,
        "import sys\\nimport tomllib\\n",
        "import sys\\nimport os\\nimport tomllib\\n",
        "Android build-number environment import",
    )
    source = replace_once(
        source,
        "    code = version_code(version)\\n",
        "    code = version_code(version)\\n"
        "    build_number = os.environ.get(\\"GITHUB_RUN_NUMBER\\", \\"\\")\\n"
        "    if build_number.isdigit():\\n"
        "        code = max(code, 50_000_000 + int(build_number))\\n",
        "monotonic APK versionCode",
    )
    old_app = '    application = android_meta.get("application") or {}'
    new_app = '''    application = dict(android_meta.get("application") or {})
    # Ae is the user-facing Android app label. Keep the applicationId and all
    # internal EffectCraft identifiers unchanged for in-place updates and project compatibility.
    application["label"] = "Ae"'''
    source = replace_once(source, old_app, new_app, "Android application display label")
    generator.write_text(source, encoding="utf-8")

    # Update visible About text only; keep internal crate names and package identifiers intact.
    header_path = effectcraft / "crates/ui-egui/src/header.rs"
    if header_path.is_file():
        header_source = header_path.read_text(encoding="utf-8")
        header_source = header_source.replace('"About EffectCraft"', '"About Ae"')
        header_path.write_text(header_source, encoding="utf-8")

    if PACKAGE_ID not in generator.read_text(encoding="utf-8") and PACKAGE_ID not in manifest:
        # The package ID is verified again against the built APK; do not rewrite it here.
        print(f"Note: applicationId is configured by the builder; it will be verified as {PACKAGE_ID}.")
    print(f"Prepared Ae Android identity: display label=Ae, version={NEW_VERSION}.")
    print("Android applicationId/signing identity are not changed; existing user data remains in the app's data directory.")


if __name__ == "__main__":
    main()
