#!/usr/bin/env python3
"""Restore the upstream EffectCraft plug-in startup behavior in the Android launcher.

The upstream host already ships the Wasmi runtime, effect.plugins.load/list commands,
the normal Effect menu entry, and script-install commands. The Android builder creates
the same host-backed session and supplies SAF file dialogs. The missing desktop parity
is scanning <settings>/Plug-ins on Android startup.
"""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_WASM_PLUGIN_AUTOLOAD_V1"


def require_text(path: Path, snippets: tuple[str, ...], label: str) -> str:
    if not path.is_file():
        raise SystemExit(f"Missing {label}: {path}")
    content = path.read_text(encoding="utf-8")
    missing = [snippet for snippet in snippets if snippet not in content]
    if missing:
        raise SystemExit(
            f"{label} does not contain the expected upstream integration: "
            + "; ".join(repr(item) for item in missing)
        )
    return content


def main() -> None:
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    artcraft = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not effectcraft.is_dir() or not artcraft.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to the checked-out build sources")

    # Confirm the Android target will use the original sandboxed Wasmi plug-in runtime.
    require_text(
        effectcraft / "crates/host/Cargo.toml",
        (
            'effectcraft-plugin = { workspace = true, features = ["wasm"] }',
            '[target.\'cfg(not(target_arch = "wasm32"))\'.dependencies]',
        ),
        "EffectCraft host manifest",
    )
    require_text(
        effectcraft / "crates/host/src/lib.rs",
        (
            "effectcraft_plugin::wasm_available()",
            "effectcraft_plugin::loader",
        ),
        "EffectCraft host session",
    )
    require_text(
        effectcraft / "crates/engine/src/cmd/effect.rs",
        ('"effect.plugins.list"', '"effect.plugins.load"', "fn plugins_load("),
        "EffectCraft plug-in commands",
    )
    require_text(
        effectcraft / "crates/ui-egui/src/menus/frontend.rs",
        (
            '"effect.plugins.load"',
            'Ask::Open(&["wasm", "wat"])',
            '"file.installScript" | "file.installScriptUIPanel"',
            'Ask::Open(&["jsx", "js"])',
        ),
        "EffectCraft plug-in and script menus",
    )

    builder_file = artcraft / "lib/build-common.sh"
    builder = require_text(
        builder_file,
        (
            '"effectcraft": {',
            "effectcraft_host::session()",
            "inner.session.load_settings();",
        ),
        "ArtCraft Android EffectCraft launcher generator",
    )
    if MARKER in builder:
        print("Android WASM plug-in auto-loading is already patched; nothing to change.")
        return

    anchor = (
        "    inner.session.config = Some(std::sync::Arc::new("
        "@ENGINE@::config::DirConfig::new(dir)));\n"
        "    inner.session.load_settings();"
    )
    if builder.count(anchor) != 1:
        raise SystemExit(
            "Could not uniquely locate the EffectCraft Android startup settings block "
            "in lib/build-common.sh; refusing to patch an unexpected builder version."
        )

    replacement = """    // Keep the plug-in folder before DirConfig takes ownership of the path.
    let plugins_dir = dir.join("Plug-ins");
    inner.session.config = Some(std::sync::Arc::new(@ENGINE@::config::DirConfig::new(dir)));
    // EFFECTCRAFT_ANDROID_WASM_PLUGIN_AUTOLOAD_V1
    // Match desktop startup: load every API-v1 WASM effect in <settings>/Plug-ins.
    if let Err(error) = std::fs::create_dir_all(&plugins_dir) {
        log::warn!("Could not create EffectCraft plug-in folder {}: {error}", plugins_dir.display());
    } else {
        // EFFECTCRAFT_ANDROID_BUILTIN_EFFECTS_V1
        // Ship original compatibility and color-grading modules in the host APK itself.
        const BUILTIN_EFFECTS_VERSION: &str = "1.1.0";
        let bundled_modules: [(&str, &[u8]); 8] = [
            ("ec_sapphire_glow.wasm", include_bytes!("../../../assets/sapphire-compat/ec_sapphire_glow.wasm")),
            ("ec_sapphire_aura.wasm", include_bytes!("../../../assets/sapphire-compat/ec_sapphire_aura.wasm")),
            ("ec_sapphire_lensflare.wasm", include_bytes!("../../../assets/sapphire-compat/ec_sapphire_lensflare.wasm")),
            ("ec_sapphire_blur.wasm", include_bytes!("../../../assets/sapphire-compat/ec_sapphire_blur.wasm")),
            ("ec_sapphire_distort.wasm", include_bytes!("../../../assets/sapphire-compat/ec_sapphire_distort.wasm")),
            ("ec_sapphire_stylize.wasm", include_bytes!("../../../assets/sapphire-compat/ec_sapphire_stylize.wasm")),
            ("ec_sapphire_motion.wasm", include_bytes!("../../../assets/sapphire-compat/ec_sapphire_motion.wasm")),
            ("ec_looks_studio.wasm", include_bytes!("../../../assets/looks-compat/ec_looks_studio.wasm")),
        ];
        let marker_path = plugins_dir.join(".effectcraft-builtin-effects-version");
        let marker_matches = std::fs::read_to_string(&marker_path)
            .map(|value| value.trim() == BUILTIN_EFFECTS_VERSION)
            .unwrap_or(false);
        let module_missing = bundled_modules.iter().any(|(name, _)| !plugins_dir.join(*name).is_file());
        if !marker_matches || module_missing {
            let mut all_written = true;
            for (name, bytes) in bundled_modules.iter() {
                if let Err(error) = std::fs::write(plugins_dir.join(*name), *bytes) {
                    all_written = false;
                    log::warn!("Could not install built-in effect module {name}: {error}");
                }
            }
            if all_written {
                if let Err(error) = std::fs::write(&marker_path, SAPPHIRE_COMPAT_VERSION) {
                    log::warn!("Could not record built-in effect pack version: {error}");
                }
            }
        }
        log::info!("EFFECTCRAFT_ANDROID_WASM_PLUGIN_AUTOLOAD_V1: scanning {}", plugins_dir.display());
        match inner.session.execute(
            "effect.plugins.load",
            serde_json::json!({"folder": plugins_dir.to_string_lossy()}),
        ) {
            Ok(report) => {
                let loaded = report.get("loaded").and_then(|value| value.as_array()).map_or(0, |items| items.len());
                log::info!("EffectCraft Android: loaded {loaded} WASM effect plug-in(s)");
                if let Some(errors) = report.get("errors").and_then(|value| value.as_array()) {
                    for error in errors {
                        log::warn!("EffectCraft WASM plug-in was not loaded: {error}");
                    }
                }
            }
            Err(error) => log::warn!("EffectCraft WASM plug-in folder scan failed: {error}"),
        }
    }
    inner.session.load_settings();"""

    builder = builder.replace(anchor, replacement, 1)
    builder_file.write_text(builder, encoding="utf-8")
    print("Validated the original WASM runtime, plugin commands, and script-install commands.")
    print("Restored Android startup scanning of <app settings>/Plug-ins.")
    print("The upstream Wasmi sandbox, fuel limit, memory allowance, and parallel rendering are unchanged.")


if __name__ == "__main__":
    main()
