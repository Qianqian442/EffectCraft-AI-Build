#!/usr/bin/env python3
"""Add safe runtime unloading and deletion for user-installed Ae effect plug-ins."""
from __future__ import annotations
import os
from pathlib import Path

MARKER = "EFFECTCRAFT_PLUGIN_UNINSTALL_V1"

def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)

def patch_registry(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return
    source = replace_once(
        source,
        "static SLOTS: [OnceLock<Arc<dyn EffectPlugin>>; MAX_PLUGINS] = [const { OnceLock::new() }; MAX_PLUGINS];",
        """// EFFECTCRAFT_PLUGIN_UNINSTALL_V1
// Removed slots remain tombstoned. An in-flight renderer may still hold an older EffectSpec
// whose function pointer targets this slot; it must never be redirected to another plug-in.
struct PluginSlot {
    plugin: Option<Arc<dyn EffectPlugin>>,
    used: bool,
}
static SLOTS: [RwLock<PluginSlot>; MAX_PLUGINS] = [const {
    RwLock::new(PluginSlot { plugin: None, used: false })
}; MAX_PLUGINS];""",
        "replace static plug-in slots",
    )
    source = replace_once(
        source,
        """pub fn plugin(id: &str) -> Option<Arc<dyn EffectPlugin>> {
    SLOTS.iter().filter_map(|s| s.get()).find(|p| p.manifest().id == id).cloned()
}""",
        """pub fn plugin(id: &str) -> Option<Arc<dyn EffectPlugin>> {
    SLOTS.iter()
        .filter_map(|slot| slot.read().ok().and_then(|state| state.plugin.clone()))
        .find(|plugin| plugin.manifest().id == id)
}""",
        "plug-in lookup",
    )
    source = replace_once(
        source,
        """    let slot = SLOTS.iter().position(|s| s.get().is_none()).ok_or_else(|| format!("too many plug-ins (at most {MAX_PLUGINS})"))?;
    SLOTS[slot].set(plugin).map_err(|_| "plug-in slot taken".to_string())?;""",
        """    let slot = SLOTS.iter().position(|cell| cell.read().is_ok_and(|state| !state.used))
        .ok_or_else(|| format!("too many plug-ins have been loaded during this app session (at most {MAX_PLUGINS}); restart Ae to reclaim removed slots"))?;
    {
        let mut state = SLOTS[slot].write().map_err(|_| "plug-in slot poisoned".to_string())?;
        if state.used || state.plugin.is_some() {
            return Err("plug-in slot is unavailable".into());
        }
        state.used = true;
        state.plugin = Some(plugin);
    }""",
        "plug-in slot registration",
    )
    source = replace_once(
        source,
        """fn run_slot(slot: usize, ctx: &EffectCtx, mut buf: Buf) -> Buf {
    let Some(plugin) = SLOTS[slot].get() else { return buf };
    let m = plugin.manifest();""",
        """fn run_slot(slot: usize, ctx: &EffectCtx, mut buf: Buf) -> Buf {
    let Some(plugin) = SLOTS.get(slot)
        .and_then(|cell| cell.read().ok())
        .and_then(|state| state.plugin.clone())
    else {
        return buf;
    };
    let m = plugin.manifest();""",
        "plug-in render slot",
    )
    unregister = """
/// Unregister a dynamically loaded plug-in and return its original source path.
pub fn unregister_plugin(id: &str) -> Result<String, String> {
    let mut specs = plugin_specs().write().map_err(|_| "plug-in registry poisoned".to_string())?;
    let spec_index = specs.iter().position(|spec| spec.id == id)
        .ok_or_else(|| format!("no loaded plug-in with id {id}"))?;
    let slot_index = SLOTS.iter().position(|cell| {
        cell.read().ok().is_some_and(|state| {
            state.plugin.as_ref().is_some_and(|plugin| plugin.manifest().id == id)
        })
    }).ok_or_else(|| format!("plug-in {id} has no active runtime slot"))?;
    let mut slot = SLOTS[slot_index].write().map_err(|_| "plug-in slot poisoned".to_string())?;
    let plugin = slot.plugin.as_ref().ok_or_else(|| format!("plug-in {id} is already unloaded"))?;
    let source = plugin.source();
    slot.plugin = None;
    specs.remove(spec_index);
    Ok(source)
}

"""
    slot_anchor = "/// Each slot needs its own " + chr(96) + "fn" + chr(96) + " (effect render functions are plain function pointers).\n"
    source = replace_once(source, slot_anchor, unregister + slot_anchor, "unregister API insertion")
    path.write_text(source, encoding="utf-8")

EFFECT_HELPERS = r'''
// EFFECTCRAFT_PLUGIN_UNINSTALL_V1
const BUILTIN_EFFECT_MODULES: &[&str] = &[
    "ec_sapphire_glow.wasm", "ec_sapphire_aura.wasm", "ec_sapphire_lensflare.wasm",
    "ec_sapphire_blur.wasm", "ec_sapphire_distort.wasm", "ec_sapphire_stylize.wasm",
    "ec_sapphire_glint.wasm", "ec_sapphire_rays.wasm", "ec_sapphire_halftone.wasm",
    "ec_sapphire_pixelsort.wasm", "ec_rsmb_motion_blur.wasm", "ec_looks_studio.wasm",
    "ec_sapphire_textureflux.wasm",
    "craft_glow.wasm", "craft_chromatic.wasm", "craft_camera_shake.wasm",
    "craft_displacer.wasm", "craft_halftone_dither.wasm", "craft_vhs_glitch.wasm",
    "craft_pixel_sort.wasm", "craft_anamorphic_flare.wasm",
    "craft_motion_blur_curves.wasm", "craft_reveal.wasm",
];

/// Only user WASM/WAT modules stored directly in Ae's app-owned Plug-ins folder can be deleted.
fn managed_plugin_source(s: &Session, source: &str) -> Option<std::path::PathBuf> {
    let config_dir = s.config.as_ref()?.dir()?;
    let plugins_dir = config_dir.join("Plug-ins").canonicalize().ok()?;
    let path = std::path::Path::new(source).canonicalize().ok()?;
    let extension = path.extension().and_then(|value| value.to_str())?;
    if !extension.eq_ignore_ascii_case("wasm") && !extension.eq_ignore_ascii_case("wat") {
        return None;
    }
    if path.parent() != Some(plugins_dir.as_path()) {
        return None;
    }
    let name = path.file_name()?.to_str()?;
    if BUILTIN_EFFECT_MODULES.contains(&name) {
        return None;
    }
    Some(path)
}

/// Persist a user-selected module in Ae's private folder; never delete the user's original file.
fn persist_plugin_module(s: &Session, source: &str, bytes: &[u8]) -> std::result::Result<(String, bool), String> {
    let extension = std::path::Path::new(source).extension().and_then(|value| value.to_str()).unwrap_or("");
    if !extension.eq_ignore_ascii_case("wasm") && !extension.eq_ignore_ascii_case("wat") {
        return Ok((source.to_string(), false));
    }
    let Some(config_dir) = s.config.as_ref().and_then(|config| config.dir()) else {
        return Ok((source.to_string(), false));
    };
    let plugins_dir = config_dir.join("Plug-ins");
    std::fs::create_dir_all(&plugins_dir).map_err(|error| format!("无法创建 Ae 插件目录：{error}"))?;
    let canonical_dir = plugins_dir.canonicalize().map_err(|error| format!("无法解析 Ae 插件目录：{error}"))?;
    if let Ok(existing) = std::path::Path::new(source).canonicalize()
        && existing.parent() == Some(canonical_dir.as_path())
    {
        return Ok((existing.to_string_lossy().into_owned(), false));
    }
    let original_name = std::path::Path::new(source).file_name()
        .and_then(|value| value.to_str()).unwrap_or("effect.wasm");
    let safe_name = original_name.chars()
        .map(|character| if character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-') { character } else { '_' })
        .take(150)
        .collect::<String>();
    let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default().as_nanos();
    let destination = canonical_dir.join(format!("imported_{stamp}_{safe_name}"));
    s.services.store_file(&destination.to_string_lossy(), bytes)
        .map_err(|error| format!("无法保存插件到 Ae 私有插件目录：{error}"))?;
    Ok((destination.to_string_lossy().into_owned(), true))
}

/// Remove a user-installed module file and unregister its runtime.
fn plugins_unload(s: &mut Session, p: &Value) -> Result<Value> {
    let id = str_p(p, "id").ok_or_else(|| bad("effect.plugins.unload", "missing plug-in id"))?;
    if p.get("confirmed").and_then(Value::as_bool) != Some(true) {
        return Err(bad("effect.plugins.unload", "explicit confirmation is required"));
    }
    let plugin = effectcraft_effects::plugin::plugin(id)
        .ok_or_else(|| bad("effect.plugins.unload", format!("no loaded plug-in {id}")))?;
    let source = plugin.source();
    drop(plugin);
    let path = managed_plugin_source(s, &source)
        .ok_or_else(|| bad("effect.plugins.unload", "内置插件或不在 Ae 私有插件目录中的文件不可删除"))?;
    let file_bytes = s.services.read_file(&path.to_string_lossy())
        .map_err(|error| bad("effect.plugins.unload", format!("无法读取插件文件：{error}")))?;
    std::fs::remove_file(&path)
        .map_err(|error| bad("effect.plugins.unload", format!("无法删除插件文件：{error}")))?;
    if let Err(error) = effectcraft_effects::plugin::unregister_plugin(id) {
        let restore = s.services.store_file(&path.to_string_lossy(), &file_bytes);
        if let Err(restore_error) = restore {
            return Err(bad("effect.plugins.unload", format!("卸载失败：{error}；恢复插件文件也失败：{restore_error}")));
        }
        return Err(bad("effect.plugins.unload", error));
    }
    s.layer_cache.clear();
    if let Some(cache) = s.disk_cache.as_ref() {
        cache.clear();
    }
    s.toast(format!("Removed effect plug-in {id}"));
    Ok(json!({"deleted": id, "source": source, "file_removed": true}))
}

'''

def patch_engine(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        # Recover safely from an older partial application: the marker may exist
        # even when the built-in-module protection constant was never inserted.
        if "BUILTIN_EFFECT_MODULES" not in source:
            constant_start = EFFECT_HELPERS.index("const BUILTIN_EFFECT_MODULES")
            constant_end = EFFECT_HELPERS.index("\n\n/// Only user WASM/WAT modules", constant_start)
            constant_block = EFFECT_HELPERS[constant_start:constant_end] + "\n\n"
            anchor = "/// Only user WASM/WAT modules stored directly in Ae's app-owned Plug-ins folder can be deleted.\n"
            source = replace_once(source, anchor, constant_block + anchor, "recover built-in plug-in protection list")
            path.write_text(source, encoding="utf-8")
        return
    list_anchor = "/// " + chr(96) + "effect.plugins.list" + chr(96) + ": the registered plug-in effects (WebAssembly or Rust).\n"
    source = replace_once(source, list_anchor, EFFECT_HELPERS + list_anchor, "plug-in uninstall helpers")
    old_list = '''        .map(|spec| {
            let p = plugin::plugin(spec.id);
            let m = p.as_ref().map(|p| p.manifest().clone());
            json!({
                "id": spec.id,
                "name": spec.name,
                "category": spec.category,
                "version": m.as_ref().map(|m| m.version.clone()),
                "author": m.as_ref().map(|m| m.author.clone()),
                "description": m.as_ref().map(|m| m.description.clone()),
                "source": p.map(|p| p.source()),
                "params": spec.params.iter().map(|p| p.id).collect::<Vec<_>>(),
            })
        })'''
    new_list = '''        .map(|spec| {
            let p = plugin::plugin(spec.id);
            let m = p.as_ref().map(|p| p.manifest().clone());
            let source = p.as_ref().map(|p| p.source()).unwrap_or_default();
            let can_delete = managed_plugin_source(s, &source).is_some();
            json!({
                "id": spec.id,
                "name": spec.name,
                "category": spec.category,
                "version": m.as_ref().map(|m| m.version.clone()),
                "author": m.as_ref().map(|m| m.author.clone()),
                "description": m.as_ref().map(|m| m.description.clone()),
                "source": source,
                "can_delete": can_delete,
                "params": spec.params.iter().map(|p| p.id).collect::<Vec<_>>(),
            })
        })'''
    source = replace_once(source, old_list, new_list, "plug-in list delete permission")
    old_loop = '''        let r = s.services.read_file(f).map_err(|e| format!("cannot read {f}: {e}")).and_then(|bytes| loader(&bytes, f));
        match r {
            Ok(v) => loaded.push(v),
            Err(e) => errors.push(json!({"path": f, "error": e})),
        }'''
    new_loop = '''        let r = s.services.read_file(f).map_err(|e| format!("cannot read {f}: {e}")).and_then(|bytes| {
            let (load_source, copied) = persist_plugin_module(s, f, &bytes)?;
            match loader(&bytes, &load_source) {
                Ok(value) => Ok(value),
                Err(error) => {
                    if copied {
                        let _ = std::fs::remove_file(&load_source);
                    }
                    Err(error)
                }
            }
        });
        match r {
            Ok(v) => loaded.push(v),
            Err(e) => errors.push(json!({"path": f, "error": e})),
        }'''
    source = replace_once(source, old_loop, new_loop, "persist direct user plug-in imports")
    command_anchor = '''        cmd!(
            "effect.plugins.load",
            "Load Effect Plug-in...",
            [],
            None,
            "{path (.wasm / .wat plug-in, API v1) | folder (loads every .wasm in it)}",
            super::always,
            plugins_load
        ),
'''
    command_replacement = command_anchor + '''        cmd!(
            "effect.plugins.unload",
            "Remove Effect Plug-in",
            [],
            None,
            "{id, confirmed: true} — permanently removes a user-installed module from the app plug-in folder and unloads it",
            super::always,
            plugins_unload
        ),
'''
    source = replace_once(source, command_anchor, command_replacement, "unload command registration")
    path.write_text(source, encoding="utf-8")

def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    plugin_path = root / "crates/effects/src/plugin.rs"
    effect_path = root / "crates/engine/src/cmd/effect.rs"
    for path in (plugin_path, effect_path):
        if not path.is_file():
            raise SystemExit(f"Required plug-in source file is missing: {path}")
    patch_registry(plugin_path)
    patch_engine(effect_path)
    registry = plugin_path.read_text(encoding="utf-8")
    engine = effect_path.read_text(encoding="utf-8")
    required = [
        "pub fn unregister_plugin(id: &str)",
        "fn plugins_unload(",
        '"effect.plugins.unload"',
        '"can_delete": can_delete',
        "persist_plugin_module(s, f, &bytes)",
        "BUILTIN_EFFECT_MODULES",
    ]
    missing = [token for token in required if token not in registry + engine]
    if missing:
        raise SystemExit("Plug-in uninstall integration is incomplete: " + ", ".join(missing))
    print("Added safe plug-in unloading, private module persistence and the effect.plugins.unload command.")
    print("Built-in modules and files outside the app-owned Plug-ins directory are protected.")
    print("Removed render slots remain tombstoned until Ae restarts so in-flight renders cannot be redirected.")

if __name__ == "__main__":
    main()
