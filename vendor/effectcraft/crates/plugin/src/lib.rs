//! # effectcraft-plugin (L3)
//!
//! Loads **WebAssembly effect plug-ins** (plug-in API v1, see `docs/plugins.md`) into the effect
//! registry ([`effectcraft_effects::plugin`]). A plug-in is a `.wasm` (or `.wat`) module with
//! no imports that exports:
//!
//! | export | signature | |
//! |---|---|---|
//! | `memory` | memory | linear memory shared with the host |
//! | `ec_api_version` | `() -> i32` | must return 1 |
//! | `ec_manifest_ptr`, `ec_manifest_len` | `() -> i32` | a UTF-8 JSON [`PluginManifest`] in memory |
//! | `ec_alloc` | `(bytes: i32) -> i32` | a buffer of at least `bytes` bytes, 8-byte aligned; it may reuse the previous one |
//! | `ec_render` | `(pixels: i32, width: i32, height: i32, params: i32, nparams: i32, time: f64, scale: f64) -> i32` | process the pixels in place; 0 = ok |
//!
//! For each render the host asks `ec_alloc` for one buffer holding the parameters (`nparams`
//! little-endian `f64`s) followed by the pixels (`width × height × 4` little-endian `f32`s,
//! premultiplied RGBA, row-major), calls `ec_render`, and reads the pixels back.
//!
//! Modules run in the [wasmi](https://github.com/wasmi-labs/wasmi) interpreter (pure Rust,
//! MIT/Apache-2.0) with deterministic floats, no imports (no files, network or clock) and a
//! fuel limit per frame, so a plug-in can't escape its sandbox, hang the app, or render
//! differently on another machine. The runtime is the `wasm` feature (on for the desktop app and
//! the CLI); without it [`load_wasm`] says plug-ins are unavailable.

#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]

use effectcraft_effects::EffectSpec;
pub use effectcraft_effects::plugin::{EffectPlugin, PLUGIN_API_VERSION, PluginFrame, PluginManifest, PluginParams, register_plugin};

#[cfg(feature = "wasm")]
mod wasm;

/// Whether this build can load WebAssembly plug-ins.
pub fn wasm_available() -> bool {
    cfg!(feature = "wasm")
}

#[cfg(feature = "wasm")]
struct ReidentifiedPlugin {
    inner: std::sync::Arc<dyn EffectPlugin>,
    manifest: PluginManifest,
}

#[cfg(feature = "wasm")]
impl EffectPlugin for ReidentifiedPlugin {
    fn manifest(&self) -> &PluginManifest {
        &self.manifest
    }

    fn source(&self) -> String {
        self.inner.source()
    }

    fn render(&self, frame: &mut PluginFrame, params: &PluginParams, time: f64) -> Result<(), String> {
        self.inner.render(frame, params, time)
    }
}

/// Load and register a WebAssembly plug-in (`bytes` = a `.wasm` binary or `.wat` text;
/// `source` = where it came from, for listings). Returns the registered effect.
pub fn load_wasm(bytes: &[u8], source: &str) -> Result<&'static EffectSpec, String> {
    #[cfg(feature = "wasm")]
    {
        let plugin: std::sync::Arc<dyn EffectPlugin> =
            std::sync::Arc::new(wasm::WasmPlugin::new(bytes, source)?);
        match register_plugin(plugin.clone()) {
            Ok(spec) => Ok(spec),
            Err(first_error) if first_error.contains("already registered") => {
                // Keep both imported effects: never replace an existing effect or block the
                // import solely because another plug-in used the same manifest id.
                let original_id = plugin.manifest().id.clone();
                for copy_index in 2..=(effectcraft_effects::plugin::MAX_PLUGINS + 1) {
                    let mut manifest = plugin.manifest().clone();
                    manifest.id = format!("{original_id}.imported{copy_index}");
                    manifest.name = format!("{}（导入副本 {copy_index}）", manifest.name);
                    let copy: std::sync::Arc<dyn EffectPlugin> =
                        std::sync::Arc::new(ReidentifiedPlugin {
                            inner: plugin.clone(),
                            manifest,
                        });
                    match register_plugin(copy) {
                        Ok(spec) => return Ok(spec),
                        Err(error) if error.contains("already registered") => continue,
                        Err(error) => return Err(error),
                    }
                }
                Err(format!("could not assign a unique id to duplicate plug-in {original_id}: {first_error}"))
            }
            Err(error) => Err(error),
        }
    }
    #[cfg(not(feature = "wasm"))]
    {
        let _ = (bytes, source);
        Err("WebAssembly plug-ins are not available in this build".into())
    }
}

/// [`load_wasm`] for the engine's plug-in loader hook: `{id, name, category, version, api}`.
pub fn loader(bytes: &[u8], source: &str) -> Result<serde_json::Value, String> {
    let spec = load_wasm(bytes, source)?;
    let m = effectcraft_effects::plugin::plugin(spec.id).map(|p| p.manifest().clone());
    Ok(serde_json::json!({
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "version": m.as_ref().map(|m| m.version.clone()).unwrap_or_default(),
        "api": PLUGIN_API_VERSION,
        "params": spec.params.len(),
    }))
}

// Two attributes, so clippy sees `cfg(test)` and treats the module as test code.
#[cfg(test)]
#[cfg(feature = "wasm")]
mod tests;
