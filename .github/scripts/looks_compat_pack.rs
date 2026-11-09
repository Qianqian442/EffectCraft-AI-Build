use std::cell::RefCell;
use std::vec::Vec;

const MANIFEST: &str = r#"{"api":1,"id":"org.effectcraft.looks.studio","name":"EffectCraft Looks Studio","category":"Looks","version":"1.0.0","author":"EffectCraft","description":"Original Looks-inspired color grading module for Android: film palettes, tonal controls, color wheels, grain and vignette. It is not the proprietary desktop Looks plug-in.","params":[{"id":"preset","name":"风格预设","type":"popup","default":0,"options":["自定义","电影暖调","青橙电影","冷青蓝","复古胶片","黑白胶片","漂白胶片","霓虹夜景"]},{"id":"strength","name":"风格强度","type":"slider","default":0.75,"min":0,"max":1,"decimals":2},{"id":"exposure","name":"曝光","type":"slider","default":0,"min":-3,"max":3,"decimals":2},{"id":"contrast","name":"对比度","type":"slider","default":1,"min":0.5,"max":2,"decimals":2},{"id":"temperature","name":"色温","type":"slider","default":0,"min":-1,"max":1,"decimals":2},{"id":"tint","name":"色调","type":"slider","default":0,"min":-1,"max":1,"decimals":2},{"id":"saturation","name":"饱和度","type":"slider","default":1,"min":0,"max":2,"decimals":2},{"id":"shadows","name":"阴影明暗","type":"slider","default":0,"min":-1,"max":1,"decimals":2},{"id":"highlights","name":"高光明暗","type":"slider","default":0,"min":-1,"max":1,"decimals":2},{"id":"fade","name":"胶片褪色","type":"slider","default":0,"min":0,"max":0.6,"decimals":2},{"id":"grain","name":"胶片颗粒","type":"slider","default":0,"min":0,"max":1,"decimals":2},{"id":"vignette","name":"暗角","type":"slider","default":0,"min":0,"max":1,"decimals":2},{"id":"shadow_color","name":"阴影色轮","type":"color","default":[0.5,0.5,0.5,1]},{"id":"midtone_color","name":"中间调色轮","type":"color","default":[0.5,0.5,0.5,1]},{"id":"highlight_color","name":"高光色轮","type":"color","default":[0.5,0.5,0.5,1]}]}"#;

thread_local! {
    static BUF: RefCell<Vec<u64>> = const { RefCell::new(Vec::new()) };
}

#[unsafe(no_mangle)]
pub extern "C" fn ec_api_version() -> i32 { 1 }

#[unsafe(no_mangle)]
pub extern "C" fn ec_manifest_ptr() -> i32 { MANIFEST.as_ptr() as i32 }

#[unsafe(no_mangle)]
pub extern "C" fn ec_manifest_len() -> i32 { MANIFEST.len() as i32 }

#[unsafe(no_mangle)]
pub extern "C" fn ec_alloc(bytes: i32) -> i32 {
    BUF.with(|cell| {
        let mut buffer = cell.borrow_mut();
        let words = (bytes.max(0) as usize).div_ceil(8);
        if buffer.len() < words { buffer.resize(words, 0); }
        buffer.as_mut_ptr() as i32
    })
}

#[derive(Clone, Copy)]
struct Palette {
    shadows: [f32; 3],
    midtones: [f32; 3],
    highlights: [f32; 3],
    saturation: f32,
    contrast: f32,
    fade: f32,
}

fn palette(index: usize) -> Palette {
    match index {
        1 => Palette {
            shadows: [-0.025, -0.003, 0.045],
            midtones: [0.018, 0.005, -0.006],
            highlights: [0.075, 0.025, -0.032],
            saturation: 1.04, contrast: 1.04, fade: 0.0,
        },
        2 => Palette {
            shadows: [-0.070, 0.018, 0.082],
            midtones: [0.002, 0.010, 0.012],
            highlights: [0.082, 0.022, -0.052],
            saturation: 1.08, contrast: 1.10, fade: 0.0,
        },
        3 => Palette {
            shadows: [-0.025, 0.012, 0.085],
            midtones: [-0.010, 0.002, 0.023],
            highlights: [0.012, 0.022, 0.060],
            saturation: 0.96, contrast: 1.05, fade: 0.0,
        },
        4 => Palette {
            shadows: [0.034, 0.014, -0.008],
            midtones: [0.026, 0.006, -0.010],
            highlights: [0.045, 0.022, 0.002],
            saturation: 0.84, contrast: 0.94, fade: 0.16,
        },
        5 => Palette {
            shadows: [0.006, 0.006, 0.006],
            midtones: [0.0, 0.0, 0.0],
            highlights: [0.008, 0.008, 0.008],
            saturation: 0.0, contrast: 1.22, fade: 0.0,
        },
        6 => Palette {
            shadows: [-0.018, -0.010, 0.008],
            midtones: [0.0, 0.0, 0.0],
            highlights: [0.020, 0.018, 0.014],
            saturation: 0.62, contrast: 1.30, fade: 0.035,
        },
        7 => Palette {
            shadows: [-0.040, -0.002, 0.105],
            midtones: [0.020, -0.016, 0.048],
            highlights: [0.075, -0.025, 0.086],
            saturation: 1.22, contrast: 1.14, fade: 0.0,
        },
        _ => Palette {
            shadows: [0.0; 3], midtones: [0.0; 3], highlights: [0.0; 3],
            saturation: 1.0, contrast: 1.0, fade: 0.0,
        },
    }
}

fn wheel_offset(rgb: &mut [f32; 3], color: &[f64], weight: f32, strength: f32) {
    for channel in 0..3 {
        let offset = (color[channel] as f32 - 0.5) * 0.34 * weight * strength;
        rgb[channel] += offset;
    }
}

fn hash_noise(x: u32, y: u32, frame: u32) -> f32 {
    let mut value = x.wrapping_mul(0x9E37_79B1)
        ^ y.wrapping_mul(0x85EB_CA77)
        ^ frame.wrapping_mul(0xC2B2_AE3D);
    value ^= value >> 16;
    value = value.wrapping_mul(0x7FEB_352D);
    value ^= value >> 15;
    value = value.wrapping_mul(0x846C_A68B);
    value ^= value >> 16;
    (value as f32 / u32::MAX as f32) * 2.0 - 1.0
}

fn smoothstep(edge0: f32, edge1: f32, value: f32) -> f32 {
    let t = ((value - edge0) / (edge1 - edge0).max(1e-5)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn ec_render(
    pixels: i32,
    width: i32,
    height: i32,
    params: i32,
    nparams: i32,
    time: f64,
    _scale: f64,
) -> i32 {
    const PARAMS_NEEDED: usize = 24;
    if width <= 0 || height <= 0 || nparams < PARAMS_NEEDED as i32 { return 1; }
    let Some(count) = (width as usize).checked_mul(height as usize) else { return 1; };
    if count == 0 || count > 32_000_000 { return 1; }

    let values = unsafe { std::slice::from_raw_parts(params as *const f64, nparams as usize) };
    let frame = unsafe { std::slice::from_raw_parts_mut(pixels as *mut [f32; 4], count) };

    let preset = values[0].round().clamp(0.0, 7.0) as usize;
    let strength = values[1].clamp(0.0, 1.0) as f32;
    let exposure = values[2].clamp(-3.0, 3.0) as f32;
    let contrast = values[3].clamp(0.5, 2.0) as f32;
    let temperature = values[4].clamp(-1.0, 1.0) as f32;
    let tint = values[5].clamp(-1.0, 1.0) as f32;
    let saturation = values[6].clamp(0.0, 2.0) as f32;
    let shadows = values[7].clamp(-1.0, 1.0) as f32;
    let highlights = values[8].clamp(-1.0, 1.0) as f32;
    let fade = values[9].clamp(0.0, 0.6) as f32;
    let grain = values[10].clamp(0.0, 1.0) as f32;
    let vignette = values[11].clamp(0.0, 1.0) as f32;
    let shadow_wheel = &values[12..16];
    let midtone_wheel = &values[16..20];
    let highlight_wheel = &values[20..24];

    let style = palette(preset);
    let exposure_gain = 2.0_f32.powf(exposure);
    let effective_contrast = contrast * (1.0 + (style.contrast - 1.0) * strength);
    let effective_saturation = saturation * (1.0 + (style.saturation - 1.0) * strength);
    let effective_fade = (fade + style.fade * strength).clamp(0.0, 0.8);
    let frame_number = (time.max(0.0) * 24.0).floor() as u32;
    let w = width as usize;
    let h = height as usize;
    let inv_w = 1.0 / w.max(1) as f32;
    let inv_h = 1.0 / h.max(1) as f32;
    let aspect = w as f32 / h.max(1) as f32;
    let vignette_radius = (0.52_f32 * (1.0 + aspect.abs().ln().abs() * 0.18)).max(0.35);
    let vignette_inner = vignette_radius * 0.34;

    for (index, pixel) in frame.iter_mut().enumerate() {
        let alpha = pixel[3].max(0.0);
        if alpha <= 1e-6 { continue; }
        let x = (index % w) as f32;
        let y = (index / w) as f32;
        let mut rgb = [
            pixel[0] / alpha,
            pixel[1] / alpha,
            pixel[2] / alpha,
        ];

        for channel in 0..3 { rgb[channel] *= exposure_gain; }

        // White balance: warm/cool temperature and green-magenta tint.
        rgb[0] *= 1.0 + temperature * 0.13 + tint * 0.035;
        rgb[1] *= 1.0 - tint * 0.075;
        rgb[2] *= 1.0 - temperature * 0.13 + tint * 0.035;

        let luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]).max(0.0);
        let shadow_weight = (1.0 - luminance.clamp(0.0, 1.0)).powi(2);
        let highlight_weight = luminance.clamp(0.0, 1.0).powi(2);
        let midtone_weight = (4.0 * luminance.clamp(0.0, 1.0) * (1.0 - luminance.clamp(0.0, 1.0))).clamp(0.0, 1.0);

        // Preset palette, followed by user-adjustable shadow / midtone / highlight wheels.
        for channel in 0..3 {
            rgb[channel] += style.shadows[channel] * shadow_weight * strength;
            rgb[channel] += style.midtones[channel] * midtone_weight * strength;
            rgb[channel] += style.highlights[channel] * highlight_weight * strength;
        }
        wheel_offset(&mut rgb, shadow_wheel, shadow_weight, 1.0);
        wheel_offset(&mut rgb, midtone_wheel, midtone_weight, 1.0);
        wheel_offset(&mut rgb, highlight_wheel, highlight_weight, 1.0);

        // Lift shadows and tame / boost highlights without destroying alpha.
        for channel in 0..3 {
            rgb[channel] += shadows * shadow_weight * 0.16;
            rgb[channel] += highlights * highlight_weight * 0.16;
        }

        let luma = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]).max(0.0);
        for channel in 0..3 {
            let saturated = luma + (rgb[channel] - luma) * effective_saturation;
            let contrasted = (saturated - 0.18) * effective_contrast + 0.18;
            let faded = contrasted * (1.0 - effective_fade) + effective_fade * (0.11 + channel as f32 * 0.006);
            rgb[channel] = faded.max(0.0);
        }

        // Aspect-correct radial vignette.
        if vignette > 0.0 {
            let dx = (x + 0.5) * inv_w - 0.5;
            let dy = (y + 0.5) * inv_h - 0.5;
            let radial = ((dx * aspect).powi(2) + dy.powi(2)).sqrt();
            let mask = smoothstep(vignette_inner, vignette_radius, radial);
            let factor = (1.0 - mask * vignette * 0.78).clamp(0.0, 1.0);
            for channel in 0..3 { rgb[channel] *= factor; }
        }

        // Deterministic per-frame monochrome film grain.
        if grain > 0.0 {
            let noise = hash_noise(x as u32, y as u32, frame_number);
            let amount = noise * grain * 0.035;
            for channel in 0..3 { rgb[channel] = (rgb[channel] + amount).max(0.0); }
        }

        for channel in 0..3 { pixel[channel] = rgb[channel] * alpha; }
        pixel[3] = alpha;
    }

    0
}
