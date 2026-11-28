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

type RenderFn = TypedFunc<(i32, i32, i32, i32, i32, f64, f64), i32>;

/// One instantiated module (renders running on several threads each take their own).
struct Inst {
    store: Store<StoreLimits>,
    instance: Instance,
    memory: Memory,
    alloc: TypedFunc<i32, i32>,
    render: RenderFn,
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

/// Validate dimensions and compute the host/WASM transfer buffer without integer overflow.
fn transfer_size(width: u32, height: u32, pixels: usize, params: usize) -> Result<(usize, usize), String> {
    if width == 0 || height == 0 || width > i32::MAX as u32 || height > i32::MAX as u32 {
        return Err("invalid frame dimensions for a 32-bit plug-in".into());
    }
    let expected_pixels = (width as usize)
        .checked_mul(height as usize)
        .ok_or_else(|| "frame pixel count overflow".to_string())?;
    if expected_pixels != pixels {
        return Err("frame dimensions do not match the pixel buffer".into());
    }
    let params_bytes = params.checked_mul(8)
        .ok_or_else(|| "plug-in parameter buffer size overflow".to_string())?;
    let pixel_bytes = pixels.checked_mul(16)
        .ok_or_else(|| "plug-in pixel buffer size overflow".to_string())?;
    let total = params_bytes.checked_add(pixel_bytes)
        .ok_or_else(|| "plug-in transfer buffer size overflow".to_string())?;
    if total > MAX_MEMORY || total > i32::MAX as usize {
        return Err(format!("plug-in frame transfer exceeds the {} MiB safety limit", MAX_MEMORY / (1024 * 1024)));
    }
    Ok((params_bytes, total))
}

fn instantiate(engine: &Engine, module: &Module) -> Result<Inst, String> {
    let mut store = Store::new(engine, StoreLimitsBuilder::new().memory_size(MAX_MEMORY).instances(1).build());
    store.limiter(|l| l);
    store.set_fuel(FUEL_BASE).map_err(err)?;
    let linker = Linker::<StoreLimits>::new(engine);
    let instance = linker.instantiate_and_start(&mut store, module).map_err(|e| format!("instantiation failed: {e}"))?;
    let memory = instance.get_memory(&store, "memory").ok_or("the module exports no `memory`")?;
    let alloc = instance.get_typed_func::<i32, i32>(&store, "ec_alloc").map_err(|_| missing("ec_alloc"))?;
    let render = instance.get_typed_func::<(i32, i32, i32, i32, i32, f64, f64), i32>(&store, "ec_render").map_err(|_| missing("ec_render"))?;
    Ok(Inst { store, instance, memory, alloc, render })
}

/// A loaded WebAssembly effect plug-in.
pub struct WasmPlugin {
    manifest: PluginManifest,
    source: String,
    engine: Engine,
    module: Module,
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
        let version = inst.func::<(), i32>("ec_api_version")?;
        let v = version.call(&mut inst.store, ()).map_err(err)?;
        if v != PLUGIN_API_VERSION as i32 {
            return Err(format!("the module implements plug-in API {v}, this build implements API {PLUGIN_API_VERSION}"));
        }
        let ptr = inst.func::<(), i32>("ec_manifest_ptr")?.call(&mut inst.store, ()).map_err(err)?;
        let len = inst.func::<(), i32>("ec_manifest_len")?.call(&mut inst.store, ()).map_err(err)?;
        if !(0..=MAX_MANIFEST).contains(&len) {
            return Err(format!("bad manifest length {len}"));
        }
        let mut text = vec![0u8; len as usize];
        inst.memory.read(&inst.store, ptr as u32 as usize, &mut text).map_err(|e| format!("manifest out of bounds: {e}"))?;
        let manifest: PluginManifest = serde_json::from_slice(&text).map_err(|e| format!("bad manifest JSON: {e}"))?;
        manifest.validate()?;
        Ok(WasmPlugin { manifest, source: source.to_string(), engine, module, pool: Mutex::new(vec![inst]) })
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
        let n = frame.pixels.len();
        let (params_bytes, total) = transfer_size(frame.width, frame.height, n, params.flat.len())?;
        let mut inst = self.take()?;
        inst.store.set_fuel(FUEL_BASE + FUEL_PER_PIXEL * n as u64).map_err(err)?;
        let base = inst.alloc.call(&mut inst.store, total as i32).map_err(err)? as u32 as usize;
        // The plug-in returns a signed i32 pointer. Reject wrapped/negative pointers and
        // ranges that cannot be represented by the host ABI before writing into WASM memory.
        let end = base.checked_add(total).ok_or_else(|| "plug-in buffer address overflow".to_string())?;
        if base > i32::MAX as usize || end > i32::MAX as usize {
            return Err("ec_alloc returned a buffer outside the 32-bit plug-in address range".into());
        }
        // Parameters, then pixels (little-endian, as WebAssembly memory is).
        let mut buf: Vec<u8> = Vec::with_capacity(total);
        for v in params.flat {
            buf.extend_from_slice(&v.to_le_bytes());
        }
        for px in frame.pixels.iter() {
            for c in px {
                buf.extend_from_slice(&c.to_le_bytes());
            }
        }
        inst.memory.write(&mut inst.store, base, &buf).map_err(|e| format!("ec_alloc returned a buffer out of bounds: {e}"))?;
        let px_ptr = (base + params_bytes) as i32;
        let r = inst
            .render
            .call(&mut inst.store, (px_ptr, frame.width as i32, frame.height as i32, base as i32, params.flat.len() as i32, time, frame.scale))
            .map_err(|e| format!("ec_render trapped: {e}"));
        let r = match r {
            Ok(0) => {
                inst.memory.read(&inst.store, base + params_bytes, &mut buf[params_bytes..]).map_err(err)?;
                for (px, b) in frame.pixels.iter_mut().zip(buf[params_bytes..].as_chunks::<16>().0.iter()) {
                    for (c, v) in px.iter_mut().zip(b.as_chunks::<4>().0.iter()) {
                        *c = f32::from_le_bytes([v[0], v[1], v[2], v[3]]);
                    }
                }
                Ok(())
            }
            Ok(code) => Err(format!("ec_render returned error {code}")),
            Err(e) => Err(e),
        };
        if r.is_ok() {
            self.give_back(inst);
        }
        r
    }
}


#[cfg(test)]
mod transfer_size_tests {
    use super::transfer_size;

    #[test]
    fn accepts_consistent_small_frame() {
        assert_eq!(transfer_size(2, 2, 4, 3), Ok((24, 88)));
    }

    #[test]
    fn rejects_mismatched_dimensions() {
        assert!(transfer_size(2, 2, 3, 0).is_err());
    }

    #[test]
    fn rejects_zero_or_unrepresentable_dimensions() {
        assert!(transfer_size(0, 2, 0, 0).is_err());
        assert!(transfer_size(u32::MAX, 2, 0, 0).is_err());
    }

    #[test]
    fn rejects_transfer_larger_than_runtime_memory_limit() {
        assert!(transfer_size(16_384, 16_384, 16_384usize * 16_384usize, 0).is_err());
    }
}
