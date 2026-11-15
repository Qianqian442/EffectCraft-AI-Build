#!/usr/bin/env python3
"""Bundle the prebuilt MIT-licensed CraftPlugins API-v1 WASM effects without changing native effects."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

UPSTREAM_COMMIT = "c50a4b51e58dbfac3aa0a9cfd945d023aeb011e6"
MARKER = "EFFECTCRAFT_ANDROID_CRAFTPLUGINS_BUNDLE_V1"

MODULES = (
    ("craft_glow.wasm", "org.craftplugins.glow"),
    ("craft_chromatic.wasm", "org.craftplugins.chromatic"),
    ("craft_camera_shake.wasm", "org.craftplugins.shake"),
    ("craft_displacer.wasm", "org.craftplugins.displacer"),
    ("craft_halftone_dither.wasm", "org.craftplugins.halftone"),
    ("craft_vhs_glitch.wasm", "org.craftplugins.vhs"),
    ("craft_pixel_sort.wasm", "org.craftplugins.pixelsort"),
    ("craft_anamorphic_flare.wasm", "org.craftplugins.anamorphic"),
    ("craft_motion_blur_curves.wasm", "org.craftplugins.motionblurcurves"),
    ("craft_reveal.wasm", "org.craftplugins.reveal"),
)

EXPORTED_SYMBOLS = (
    b"ec_api_version",
    b"ec_manifest_ptr",
    b"ec_manifest_len",
    b"ec_alloc",
    b"ec_render",
)

def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    artcraft = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    upstream = Path(os.environ.get("CRAFT_PLUGINS_DIR", "")).resolve()
    if not effectcraft.is_dir() or not artcraft.is_dir() or not upstream.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR, ARTCRAFT_DIR and CRAFT_PLUGINS_DIR must all exist")

    readme = (upstream / "README.md").read_text(encoding="utf-8")
    license_source = upstream / "LICENSE"
    if "API-v1" not in readme or "MIT License" not in license_source.read_text(encoding="utf-8"):
        raise SystemExit("The pinned CraftPlugins source does not match the expected API-v1/MIT project")

    dist = upstream / "dist"
    output = effectcraft / "assets" / "craft-plugins"
    output.mkdir(parents=True, exist_ok=True)

    records: list[tuple[str, str, int, str]] = []
    for filename, effect_id in MODULES:
        source = dist / filename
        if not source.is_file():
            raise SystemExit(f"Missing prebuilt upstream WASM module: {source}")
        data = source.read_bytes()
        if len(data) < 1024 or data[:8] != b"\x00asm\x01\x00\x00\x00":
            raise SystemExit(f"Invalid or truncated WASM v1 binary: {filename}")
        missing = [symbol.decode("ascii") for symbol in EXPORTED_SYMBOLS if symbol not in data]
        if missing:
            raise SystemExit(f"{filename} is missing required EffectCraft API-v1 exports: {missing}")
        if effect_id.encode("utf-8") not in data:
            raise SystemExit(f"{filename} does not contain expected manifest id {effect_id}")
        (output / filename).write_bytes(data)
        records.append((filename, effect_id, len(data), hashlib.sha256(data).hexdigest()))

    (output / "LICENSE").write_text(license_source.read_text(encoding="utf-8"), encoding="utf-8")

    builder_path = artcraft / "lib" / "build-common.sh"
    builder = builder_path.read_text(encoding="utf-8")
    if MARKER not in builder:
        builder = replace_once(
            builder,
            'let bundled_modules: [(&str, &[u8]); 12] = [',
            'let bundled_modules: [(&str, &[u8]); 22] = [',
            "built-in WASM module array length",
        )
        module_entries = "".join(
            f'            ("{filename}", include_bytes!("../../../assets/craft-plugins/{filename}")),\n'
            for filename, _ in MODULES
        )
        builder = replace_once(
            builder,
            '            ("ec_looks_studio.wasm", include_bytes!("../../../assets/looks-compat/ec_looks_studio.wasm")),\n        ];',
            '            ("ec_looks_studio.wasm", include_bytes!("../../../assets/looks-compat/ec_looks_studio.wasm")),\n'
            f'{module_entries}        ];',
            "built-in WASM module array insertion",
        )
        builder = replace_once(
            builder,
            'const BUILTIN_EFFECTS_VERSION: &str = "4.0.0";',
            'const BUILTIN_EFFECTS_VERSION: &str = "5.0.0";',
            "built-in effects cache version",
        )
        builder = replace_once(
            builder,
            '        log::info!("EFFECTCRAFT_ANDROID_WASM_PLUGIN_AUTOLOAD_V1: scanning {}", plugins_dir.display());',
            '''        // EFFECTCRAFT_ANDROID_CRAFTPLUGINS_BUNDLE_V1
        // Preserve the MIT license notice next to the bundled third-party WASM modules.
        if let Err(error) = std::fs::write(
            plugins_dir.join("CraftPlugins-MIT-LICENSE.txt"),
            include_str!("../../../assets/craft-plugins/LICENSE"),
        ) {
            log::warn!("Could not write CraftPlugins MIT license notice: {error}");
        }
        log::info!("EFFECTCRAFT_ANDROID_WASM_PLUGIN_AUTOLOAD_V1: scanning {}", plugins_dir.display());''',
            "CraftPlugins MIT license installation",
        )
        builder_path.write_text(builder, encoding="utf-8")
    else:
        required = ['const BUILTIN_EFFECTS_VERSION: &str = "5.0.0";']
        required.extend(f'include_bytes!("../../../assets/craft-plugins/{filename}")' for filename, _ in MODULES)
        missing = [item for item in required if item not in builder]
        if missing:
            raise SystemExit("CraftPlugins bundle marker exists but expected entries are missing: " + "; ".join(missing))

    print(f"Bundled {len(records)} prebuilt EffectCraft API-v1 CraftPlugins modules from {UPSTREAM_COMMIT}:")
    for filename, effect_id, size, digest in records:
        print(f"  {filename}: {effect_id}, {size} bytes, sha256={digest}")
    print("Kept the original 12 built-in EffectCraft modules; total bundled modules are now 22.")
    print("Installed the upstream MIT license notice beside the bundled plug-ins.")
    print("No native EffectCraft effects, effect menu actions, or project-export commands were replaced.")


if __name__ == "__main__":
    main()
