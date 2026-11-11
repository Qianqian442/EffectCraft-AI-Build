//! The wasmi-backed [`EffectPlugin`] (plug-in API v1 ABI, see the crate docs).

use std::sync::Mutex;

use wasmi::{Config, Engine, Instance, Linker, Memory, Module, Store, StoreLimits, StoreLimitsBuilder, TypedFunc, WasmParams, WasmResults};

use crate::{EffectPlugin, PLUGIN_API_VERSION, PluginFrame, PluginManifest, PluginParams};

/// Instruction budget per frame: a fixed allowance plus some per pixel. Generous for per-pixel
/// work, but a runaway loop stops instead of hanging the render.
const FUEL_BASE: u64 = 50_000_000;
const FUEL_PER_PIXEL: u64 = 20_000;
/// The most linear memory a plug-in instance may have (a 4K float frame is ~130 MB).
const MAX_MEMORY: usize = 1 << 30;
/// The longest manifest read.
const MAX_MANIFEST: i32 = 1 << 20;

type RenderV1Fn = TypedFunc<(i32, i32, i32, i32, i32, f64, f64), i32>;
type RenderV2Fn = TypedFunc<(i32, i32, i32, i32, i32, i32, i32, f64, f64), i32>;
const MAX_TYPED_VALUES_JSON: usize = 16 * 1024 * 1024;

/// One instantiated module (renders running on several threads each take their own).
struct Inst {
    store: Store<StoreLimits>,
    instance: Instance,
    memory: Memory,
    alloc: TypedFunc<i32, i32>,
    api: u32,
    render_v1: Option<RenderV1Fn>,
    render_v2: Option<RenderV2Fn>,
}

impl Inst {
    fn func<P: WasmParams, R: WasmResults>(&self, name: &str) -> Result<TypedFunc<P, R>, String> {
        self.instance.get_typed_func::<P, R>(&self.store, name).map_err(|_| missing(name))
    }
}

fn missing(name: &str) -> String {
    format!("the module exports no `{name}` (or with the wrong signature)")
}

fn err(e: impl std::fmt::Display) -> String {
    e.to_string()
}

fn instantiate(engine: &Engine, module: &Module) -> Result<Inst, String> {
    let mut store = Store::new(engine, StoreLimitsBuilder::new().memory_size(MAX_MEMORY).instances(1).build());
    store.limiter(|l| l);
    store.set_fuel(FUEL_BASE).map_err(err)?;
    let linker = Linker::<StoreLimits>::new(engine);
    let instance = linker.instantiate_and_start(&mut store, module).map_err(|e| format!("instantiation failed: {e}"))?;
    let memory = instance.get_memory(&store, "memory").ok_or("the module exports no `memory`")?;
    let api = instance.get_typed_func::<(), i32>(&store, "ec_api_version")
        .map_err(|_| missing("ec_api_version"))?
        .call(&mut store, ()).map_err(err)? as u32;
    let alloc = instance.get_typed_func::<i32, i32>(&store, "ec_alloc").map_err(|_| missing("ec_alloc"))?;
    let render_v1 = if api == 1 {
        instance.get_typed_func::<(i32, i32, i32, i32, i32, f64, f64), i32>(&store, "ec_render").ok()
    } else { None };
    let render_v2 = if api == 2 {
        instance.get_typed_func::<(i32, i32, i32, i32, i32, i32, i32, f64, f64), i32>(&store, "ec_render_v2").ok()
    } else { None };
    Ok(Inst { store, instance, memory, alloc, api, render_v1, render_v2 })
}

/// A loaded WebAssembly effect plug-in.
pub struct WasmPlugin {
    manifest: PluginManifest,
    source: String,
    engine: Engine,
    module: Module,
    api: u32,
    /// Idle instances.
    pool: Mutex<Vec<Inst>>,
}

impl WasmPlugin {
    pub fn new(bytes: &[u8], source: &str) -> Result<WasmPlugin, String> {
        let mut config = Config::default();
        config.consume_fuel(true);
        let engine = Engine::new(&config);
        let module = Module::new(&engine, bytes).map_err(|e| format!("not a valid WebAssembly module: {e}"))?;
        if let Some(i) = module.imports().next() {
            return Err(format!("plug-ins can't import anything (the module imports `{}.{}`)", i.module(), i.name()));
        }
        let mut inst = instantiate(&engine, &module)?;
        let v = inst.api;
        if v != 1 && v != PLUGIN_API_VERSION {
            return Err(format!("the module implements unsupported plug-in API {v}"));
        }
        let ptr = inst.func::<(), i32>("ec_manifest_ptr")?.call(&mut inst.store, ()).map_err(err)?;
        let len = inst.func::<(), i32>("ec_manifest_len")?.call(&mut inst.store, ()).map_err(err)?;
        if !(0..=MAX_MANIFEST).contains(&len) {
            return Err(format!("bad manifest length {len}"));
        }
        let mut text = vec![0u8; len as usize];
        inst.memory.read(&inst.store, ptr as u32 as usize, &mut text).map_err(|e| format!("manifest out of bounds: {e}"))?;
        let manifest: PluginManifest = serde_json::from_slice(&text).map_err(|e| format!("bad manifest JSON: {e}"))?;
        if manifest.api != v {
            return Err(format!("module API {v} does not match manifest API {}", manifest.api));
        }
        manifest.validate()?;
        if v == 1 && inst.render_v1.is_none() { return Err(missing("ec_render")); }
        if v == 2 && inst.render_v2.is_none() { return Err(missing("ec_render_v2")); }
        Ok(WasmPlugin { manifest, source: source.to_string(), engine, module, api: v, pool: Mutex::new(vec![inst]) })
    }

    fn take(&self) -> Result<Inst, String> {
        if let Some(i) = self.pool.lock().ok().and_then(|mut p| p.pop()) {
            return Ok(i);
        }
        instantiate(&self.engine, &self.module)
    }

    fn give_back(&self, inst: Inst) {
        if let Ok(mut p) = self.pool.lock() {
            p.push(inst);
        }
    }
}

impl EffectPlugin for WasmPlugin {
    fn manifest(&self) -> &PluginManifest {
        &self.manifest
    }

    fn source(&self) -> String {
        self.source.clone()
    }

    fn render(&self, frame: &mut PluginFrame, params: &PluginParams, time: f64) -> Result<(), String> {
        let pixel_count = frame.pixels.len();
        let params_bytes = params.flat.len().checked_mul(8).ok_or("parameter buffer size overflow")?;
        let pixels_bytes = pixel_count.checked_mul(16).ok_or("pixel buffer size overflow")?;
        let typed_values = if self.api >= 2 {
            serde_json::to_vec(params.values).map_err(|e| format!("typed parameter serialization failed: {e}"))?
        } else {
            Vec::new()
        };
        if typed_values.len() > MAX_TYPED_VALUES_JSON {
            return Err("typed parameter payload exceeds the 16 MB safety limit".into());
        }
        let values_offset = params_bytes.checked_add(pixels_bytes).ok_or("plug-in buffer size overflow")?;
        let total = values_offset.checked_add(typed_values.len()).ok_or("plug-in buffer size overflow")?;
        if total > i32::MAX as usize { return Err("frame too large for a 32-bit plug-in".into()); }

        let mut inst = self.take()?;
        inst.store.set_fuel(FUEL_BASE + FUEL_PER_PIXEL * pixel_count as u64).map_err(err)?;
        let base = inst.alloc.call(&mut inst.store, total as i32).map_err(err)? as u32 as usize;
        let mut buffer: Vec<u8> = Vec::with_capacity(total);
        for value in params.flat { buffer.extend_from_slice(&value.to_le_bytes()); }
        for pixel in frame.pixels.iter() {
            for channel in pixel { buffer.extend_from_slice(&channel.to_le_bytes()); }
        }
        buffer.extend_from_slice(&typed_values);
        inst.memory.write(&mut inst.store, base, &buffer)
            .map_err(|e| format!("ec_alloc returned an invalid buffer: {e}"))?;

        let pixels_ptr = (base + params_bytes) as i32;
        let render_result = if self.api == 1 {
            let render = inst.render_v1.as_ref().ok_or_else(|| missing("ec_render"))?;
            render.call(&mut inst.store, (
                pixels_ptr, frame.width as i32, frame.height as i32,
                base as i32, params.flat.len() as i32, time, frame.scale,
            ))
        } else {
            let render = inst.render_v2.as_ref().ok_or_else(|| missing("ec_render_v2"))?;
            render.call(&mut inst.store, (
                pixels_ptr, frame.width as i32, frame.height as i32,
                base as i32, params.flat.len() as i32,
                (base + values_offset) as i32, typed_values.len() as i32,
                time, frame.scale,
            ))
        }.map_err(|e| format!("plug-in render trapped: {e}"));

        let result = match render_result {
            Ok(0) => {
                inst.memory.read(&inst.store, base + params_bytes, &mut buffer[params_bytes..values_offset]).map_err(err)?;
                for (pixel, bytes) in frame.pixels.iter_mut().zip(buffer[params_bytes..values_offset].as_chunks::<16>().0.iter()) {
                    for (channel, value) in pixel.iter_mut().zip(bytes.as_chunks::<4>().0.iter()) {
                        *channel = f32::from_le_bytes([value[0], value[1], value[2], value[3]]);
                    }
                }
                Ok(())
            }
            Ok(code) => Err(format!("plug-in render returned error {code}")),
            Err(error) => Err(error),
        };
        if result.is_ok() { self.give_back(inst); }
        result
    }
}
