use std::cell::RefCell;
use std::vec::Vec;

const MANIFEST: &str = r#"${manifestJson}"#;

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
        1 => Palette { shadows: [-0.025, -0.003, 0.045], midtones: [0.018, 0.005, -0.006], highlights: [0.075, 0.025, -0.032], saturation: 1.04, contrast: 1.04, fade: 0.0 },
        2 => Palette { shadows: [-0.070, 0.018, 0.082], midtones: [0.002, 0.010, 0.012], highlights: [0.082, 0.022, -0.052], saturation: 1.08, contrast: 1.10, fade: 0.0 },
        3 => Palette { shadows: [-0.025, 0.012, 0.085], midtones: [-0.010, 0.002, 0.023], highlights: [0.012, 0.022, 0.060], saturation: 0.96, contrast: 1.05, fade: 0.0 },
        4 => Palette { shadows: [0.034, 0.014, -0.008], midtones: [0.026, 0.006, -0.010], highlights: [0.045, 0.022, 0.002], saturation: 0.84, contrast: 0.94, fade: 0.16 },
        5 => Palette { shadows: [0.006, 0.006, 0.006], midtones: [0.0, 0.0, 0.0], highlights: [0.008, 0.008, 0.008], saturation: 0.0, contrast: 1.22, fade: 0.0 },
        6 => Palette { shadows: [-0.018, -0.010, 0.008], midtones: [0.0, 0.0, 0.0], highlights: [0.020, 0.018, 0.014], saturation: 0.62, contrast: 1.30, fade: 0.035 },
        7 => Palette { shadows: [-0.040, -0.002, 0.105], midtones: [0.020, -0.016, 0.048], highlights: [0.075, -0.025, 0.086], saturation: 1.22, contrast: 1.14, fade: 0.0 },
        8 => Palette { shadows: [0.018, 0.006, 0.012], midtones: [0.018, 0.006, 0.004], highlights: [0.035, 0.014, 0.006], saturation: 0.90, contrast: 0.96, fade: 0.04 },
        9 => Palette { shadows: [-0.018, 0.004, 0.045], midtones: [0.006, -0.006, 0.022], highlights: [0.012, -0.010, 0.065], saturation: 0.92, contrast: 1.12, fade: 0.0 },
        10 => Palette { shadows: [0.012, 0.006, -0.005], midtones: [0.025, 0.010, -0.004], highlights: [0.040, 0.018, 0.002], saturation: 0.96, contrast: 1.02, fade: 0.025 },
        _ => Palette { shadows: [0.0; 3], midtones: [0.0; 3], highlights: [0.0; 3], saturation: 1.0, contrast: 1.0, fade: 0.0 },
    }
}

fn luminance(rgb: [f32; 3]) -> f32 {
    0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
}

fn smoothstep(edge0: f32, edge1: f32, value: f32) -> f32 {
    let t = ((value - edge0) / (edge1 - edge0).max(1e-5)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

fn hue_weight(hue: f32, center: f32) -> f32 {
    let distance = (hue - center + 180.0).rem_euclid(360.0) - 180.0;
    1.0 - smoothstep(18.0, 72.0, distance.abs())
}

fn rgb_to_hsl(rgb: [f32; 3]) -> [f32; 3] {
    let r = rgb[0].clamp(0.0, 1.0);
    let g = rgb[1].clamp(0.0, 1.0);
    let b = rgb[2].clamp(0.0, 1.0);
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let delta = max - min;
    let light = (max + min) * 0.5;
    if delta <= 1e-6 { return [0.0, 0.0, light]; }
    let saturation = delta / (1.0 - (2.0 * light - 1.0).abs()).max(1e-6);
    let hue = if max == r {
        60.0 * (((g - b) / delta).rem_euclid(6.0))
    } else if max == g {
        60.0 * (((b - r) / delta) + 2.0)
    } else {
        60.0 * (((r - g) / delta) + 4.0)
    };
    [hue.rem_euclid(360.0), saturation.clamp(0.0, 1.0), light.clamp(0.0, 1.0)]
}

fn hsl_to_rgb(hsl: [f32; 3]) -> [f32; 3] {
    let h = hsl[0].rem_euclid(360.0);
    let s = hsl[1].clamp(0.0, 1.0);
    let l = hsl[2].clamp(0.0, 1.0);
    let c = (1.0 - (2.0 * l - 1.0).abs()) * s;
    let x = c * (1.0 - ((h / 60.0).rem_euclid(2.0) - 1.0).abs());
    let m = l - c * 0.5;
    let base = match h as i32 {
        0..=59 => [c, x, 0.0],
        60..=119 => [x, c, 0.0],
        120..=179 => [0.0, c, x],
        180..=239 => [0.0, x, c],
        240..=299 => [x, 0.0, c],
        _ => [c, 0.0, x],
    };
    [base[0] + m, base[1] + m, base[2] + m]
}

fn curve(value: f32, points: [f32; 5]) -> f32 {
    let scaled = value.clamp(0.0, 1.0) * 4.0;
    let segment = (scaled.floor() as usize).min(3);
    let t = scaled - segment as f32;
    points[segment] + (points[segment + 1] - points[segment]) * t
}

fn wheel_offset(rgb: &mut [f32; 3], color: &[f64], weight: f32, strength: f32) {
    for channel in 0..3 {
        rgb[channel] += (color[channel] as f32 - 0.5) * 0.34 * weight * strength;
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
    const PARAMS_NEEDED: usize = 74;
    if width <= 0 || height <= 0 || nparams < PARAMS_NEEDED as i32 { return 1; }
    let Some(count) = (width as usize).checked_mul(height as usize) else { return 1; };
    if count == 0 || count > 32_000_000 { return 1; }

    let values = unsafe { std::slice::from_raw_parts(params as *const f64, nparams as usize) };
    let frame = unsafe { std::slice::from_raw_parts_mut(pixels as *mut [f32; 4], count) };
    let preset = values[0].round().clamp(0.0, 10.0) as usize;
    let strength = values[1].clamp(0, 1) as f32;
    let exposure = values[2].clamp(-3, 3) as f32;
    let contrast = values[3].clamp(0.5, 2) as f32;
    let pivot = values[4].clamp(0.1, 0.9) as f32;
    let black_point = values[5].clamp(0, 0.25) as f32;
    let white_point = values[6].clamp(0.75, 1) as f32;
    let gamma = values[7].clamp(0.5, 2) as f32;
    let shadows = values[8].clamp(-1, 1) as f32;
    let midtones = values[9].clamp(-1, 1) as f32;
    let highlights = values[10].clamp(-1, 1) as f32;
    let whites = values[11].clamp(-1, 1) as f32;
    let blacks = values[12].clamp(-1, 1) as f32;
    let temperature = values[13].clamp(-1, 1) as f32;
    let tint = values[14].clamp(-1, 1) as f32;
    let saturation = values[15].clamp(0, 2) as f32;
    let vibrance = values[16].clamp(-1, 1) as f32;
    let hue_shift = values[17].clamp(-180, 180) as f32;
    let shadow_color = &values[18..22];
    let midtone_color = &values[22..26];
    let highlight_color = &values[26..30];
    let shadow_wheel_strength = values[30].clamp(0, 2) as f32;
    let midtone_wheel_strength = values[31].clamp(0, 2) as f32;
    let highlight_wheel_strength = values[32].clamp(0, 2) as f32;
    let fade = values[33].clamp(0, 0.6) as f32;
    let grain = values[34].clamp(0, 1) as f32;
    let grain_size = values[35].clamp(1, 6) as f32;
    let vignette = values[36].clamp(0, 1) as f32;
    let vignette_midpoint = values[37].clamp(0.05, 0.9) as f32;
    let vignette_feather = values[38].clamp(0.05, 1) as f32;
    let halation = values[39].clamp(0, 1) as f32;
    let bloom = values[40].clamp(0, 1) as f32;
    let bloom_threshold = values[41].clamp(0.1, 1) as f32;
    let dehaze = values[42].clamp(0, 1) as f32;
    let clarity = values[43].clamp(-1, 1) as f32;
    let sharpen = values[44].clamp(0, 1) as f32;
    let curve_black = values[45].clamp(0, 1) as f32;
    let curve_shadows = values[46].clamp(0, 1) as f32;
    let curve_midtones = values[47].clamp(0, 1) as f32;
    let curve_highlights = values[48].clamp(0, 1) as f32;
    let curve_white = values[49].clamp(0, 1) as f32;
    let hsl_red_hue = values[50].clamp(-180, 180) as f32;
    let hsl_red_sat = values[51].clamp(-1, 1) as f32;
    let hsl_red_lum = values[52].clamp(-1, 1) as f32;
    let hsl_orange_hue = values[53].clamp(-180, 180) as f32;
    let hsl_orange_sat = values[54].clamp(-1, 1) as f32;
    let hsl_orange_lum = values[55].clamp(-1, 1) as f32;
    let hsl_yellow_hue = values[56].clamp(-180, 180) as f32;
    let hsl_yellow_sat = values[57].clamp(-1, 1) as f32;
    let hsl_yellow_lum = values[58].clamp(-1, 1) as f32;
    let hsl_green_hue = values[59].clamp(-180, 180) as f32;
    let hsl_green_sat = values[60].clamp(-1, 1) as f32;
    let hsl_green_lum = values[61].clamp(-1, 1) as f32;
    let hsl_aqua_hue = values[62].clamp(-180, 180) as f32;
    let hsl_aqua_sat = values[63].clamp(-1, 1) as f32;
    let hsl_aqua_lum = values[64].clamp(-1, 1) as f32;
    let hsl_blue_hue = values[65].clamp(-180, 180) as f32;
    let hsl_blue_sat = values[66].clamp(-1, 1) as f32;
    let hsl_blue_lum = values[67].clamp(-1, 1) as f32;
    let hsl_purple_hue = values[68].clamp(-180, 180) as f32;
    let hsl_purple_sat = values[69].clamp(-1, 1) as f32;
    let hsl_purple_lum = values[70].clamp(-1, 1) as f32;
    let hsl_magenta_hue = values[71].clamp(-180, 180) as f32;
    let hsl_magenta_sat = values[72].clamp(-1, 1) as f32;
    let hsl_magenta_lum = values[73].clamp(-1, 1) as f32;

    let style = palette(preset);
    let exposure_gain = 2.0_f32.powf(exposure);
    let effective_contrast = contrast * (1.0 + (style.contrast - 1.0) * strength);
    let effective_saturation = saturation * (1.0 + (style.saturation - 1.0) * strength);
    let effective_fade = (fade + style.fade * strength).clamp(0.0, 0.8);
    let black = black_point.min(white_point - 0.01);
    let white = white_point.max(black + 0.01);
    let curve_points = [curve_black, curve_shadows, curve_midtones, curve_highlights, curve_white];
    let frame_number = (time.max(0.0) * 24.0).floor() as u32;
    let w = width as usize;
    let h = height as usize;
    let inv_w = 1.0 / w.max(1) as f32;
    let inv_h = 1.0 / h.max(1) as f32;
    let aspect = w as f32 / h.max(1) as f32;
    let radius = (0.53_f32 * (1.0 + aspect.abs().ln().abs() * 0.18)).max(0.35);
    let inner = radius * (0.15 + vignette_midpoint * 0.72);
    let outer = (inner + (radius - inner) * vignette_feather.max(0.05)).max(inner + 1e-4);

    // Preserve the input luminance for the local-contrast and sharpening controls.
    let source_luma: Vec<f32> = frame.iter().map(|p| {
        if p[3] <= 1e-6 { 0.0 } else {
            luminance([p[0] / p[3], p[1] / p[3], p[2] / p[3]])
        }
    }).collect();

    for (index, pixel) in frame.iter_mut().enumerate() {
        let alpha = pixel[3].max(0.0);
        if alpha <= 1e-6 { continue; }
        let x = (index % w) as f32;
        let y = (index / w) as f32;
        let mut rgb = [pixel[0] / alpha, pixel[1] / alpha, pixel[2] / alpha];

        for channel in 0..3 { rgb[channel] *= exposure_gain; }

        // White balance.
        rgb[0] *= 1.0 + temperature * 0.13 + tint * 0.035;
        rgb[1] *= 1.0 - tint * 0.075;
        rgb[2] *= 1.0 - temperature * 0.13 + tint * 0.035;

        // Black / white points and gamma.
        for channel in 0..3 {
            let normalized = ((rgb[channel] - black) / (white - black)).max(0.0);
            rgb[channel] = normalized.powf(1.0 / gamma.max(0.05));
        }

        let luma0 = luminance(rgb).clamp(0.0, 1.0);
        let shadow_weight = (1.0 - luma0).powi(2);
        let midtone_weight = (4.0 * luma0 * (1.0 - luma0)).clamp(0.0, 1.0);
        let highlight_weight = luma0.powi(2);
        let white_weight = smoothstep(0.65, 1.0, luma0);
        let black_weight = 1.0 - smoothstep(0.0, 0.38, luma0);

        for channel in 0..3 {
            rgb[channel] += style.shadows[channel] * shadow_weight * strength;
            rgb[channel] += style.midtones[channel] * midtone_weight * strength;
            rgb[channel] += style.highlights[channel] * highlight_weight * strength;
            rgb[channel] += shadows * shadow_weight * 0.18;
            rgb[channel] += midtones * midtone_weight * 0.12;
            rgb[channel] += highlights * highlight_weight * 0.18;
            rgb[channel] += whites * white_weight * 0.12;
            rgb[channel] += blacks * black_weight * 0.12;
        }

        wheel_offset(&mut rgb, shadow_color, shadow_weight, shadow_wheel_strength);
        wheel_offset(&mut rgb, midtone_color, midtone_weight, midtone_wheel_strength);
        wheel_offset(&mut rgb, highlight_color, highlight_weight, highlight_wheel_strength);

        // Pivoted contrast and dehaze.
        for channel in 0..3 {
            rgb[channel] = (rgb[channel] - pivot) * effective_contrast + pivot;
            if dehaze > 0.0 {
                rgb[channel] = (rgb[channel] - 0.08 * dehaze) / (1.0 - 0.72 * dehaze).max(0.1);
            }
        }

        let mut hsl = rgb_to_hsl(rgb);
        hsl[0] = (hsl[0] + hue_shift).rem_euclid(360.0);
        hsl[1] = (hsl[1] + vibrance * (1.0 - hsl[1]) * 0.65).clamp(0.0, 1.0);

        let w_red = hue_weight(hsl[0], 0.0);
        hsl[0] += hsl_red_hue * w_red;
        hsl[1] += hsl_red_sat * w_red;
        hsl[2] += hsl_red_lum * w_red * 0.25;

        let w_orange = hue_weight(hsl[0], 30.0);
        hsl[0] += hsl_orange_hue * w_orange;
        hsl[1] += hsl_orange_sat * w_orange;
        hsl[2] += hsl_orange_lum * w_orange * 0.25;

        let w_yellow = hue_weight(hsl[0], 60.0);
        hsl[0] += hsl_yellow_hue * w_yellow;
        hsl[1] += hsl_yellow_sat * w_yellow;
        hsl[2] += hsl_yellow_lum * w_yellow * 0.25;

        let w_green = hue_weight(hsl[0], 120.0);
        hsl[0] += hsl_green_hue * w_green;
        hsl[1] += hsl_green_sat * w_green;
        hsl[2] += hsl_green_lum * w_green * 0.25;

        let w_aqua = hue_weight(hsl[0], 180.0);
        hsl[0] += hsl_aqua_hue * w_aqua;
        hsl[1] += hsl_aqua_sat * w_aqua;
        hsl[2] += hsl_aqua_lum * w_aqua * 0.25;

        let w_blue = hue_weight(hsl[0], 220.0);
        hsl[0] += hsl_blue_hue * w_blue;
        hsl[1] += hsl_blue_sat * w_blue;
        hsl[2] += hsl_blue_lum * w_blue * 0.25;

        let w_purple = hue_weight(hsl[0], 270.0);
        hsl[0] += hsl_purple_hue * w_purple;
        hsl[1] += hsl_purple_sat * w_purple;
        hsl[2] += hsl_purple_lum * w_purple * 0.25;

        let w_magenta = hue_weight(hsl[0], 320.0);
        hsl[0] += hsl_magenta_hue * w_magenta;
        hsl[1] += hsl_magenta_sat * w_magenta;
        hsl[2] += hsl_magenta_lum * w_magenta * 0.25;
        hsl[1] = (hsl[1] * effective_saturation).clamp(0.0, 1.0);
        rgb = hsl_to_rgb(hsl);

        // Five-point RGB curve. The five draggable values are exposed as animatable effect controls.
        for channel in 0..3 { rgb[channel] = curve(rgb[channel], curve_points); }

        // Local contrast and sharpening use a small 3x3 luminance neighborhood.
        if clarity.abs() > 0.0001 || sharpen > 0.0001 {
            let mut sum = 0.0;
            let mut neighbors = 0.0;
            let xi = x as isize;
            let yi = y as isize;
            for dy in -1..=1 {
                for dx in -1..=1 {
                    if dx == 0 && dy == 0 { continue; }
                    let nx = (xi + dx).clamp(0, w as isize - 1) as usize;
                    let ny = (yi + dy).clamp(0, h as isize - 1) as usize;
                    sum += source_luma[ny * w + nx];
                    neighbors += 1.0;
                }
            }
            let high_pass = source_luma[index] - sum / neighbors.max(1.0);
            let detail = high_pass * (clarity * 0.55 + sharpen * 1.35);
            for channel in 0..3 { rgb[channel] += detail; }
        }

        // Aspect-correct vignette.
        if vignette > 0.0 {
            let dx = (x + 0.5) * inv_w - 0.5;
            let dy = (y + 0.5) * inv_h - 0.5;
            let radial = ((dx * aspect).powi(2) + dy.powi(2)).sqrt();
            let mask = smoothstep(inner, outer, radial);
            let factor = (1.0 - mask * vignette * 0.82).clamp(0.0, 1.0);
            for channel in 0..3 { rgb[channel] *= factor; }
        }

        // Film grain uses a controllable spatial scale.
        if grain > 0.0 {
            let size = grain_size.round().clamp(1.0, 6.0) as u32;
            let noise = hash_noise(x as u32 / size, y as u32 / size, frame_number);
            let amount = noise * grain * 0.035;
            for channel in 0..3 { rgb[channel] = (rgb[channel] + amount).max(0.0); }
        }

        for channel in 0..3 { pixel[channel] = rgb[channel].max(0.0) * alpha; }
        pixel[3] = alpha;
    }

    // Bloom and film halation use a highlight-only 3x3 soft spread pass.
    if bloom > 0.0001 || halation > 0.0001 {
        let graded: Vec<[f32; 3]> = frame.iter().map(|p| {
            if p[3] <= 1e-6 { [0.0; 3] } else { [p[0] / p[3], p[1] / p[3], p[2] / p[3]] }
        }).collect();
        let mut output = graded.clone();
        for y in 0..h {
            for x in 0..w {
                let index = y * w + x;
                if frame[index][3] <= 1e-6 { continue; }
                let mut glow = [0.0_f32; 3];
                let mut samples = 0.0_f32;
                for dy in -1..=1 {
                    for dx in -1..=1 {
                        let nx = (x as isize + dx).clamp(0, w as isize - 1) as usize;
                        let ny = (y as isize + dy).clamp(0, h as isize - 1) as usize;
                        let n = ny * w + nx;
                        let l = luminance(graded[n]).max(0.0);
                        let mask = smoothstep(bloom_threshold, 1.0, l);
                        for channel in 0..3 { glow[channel] += graded[n][channel] * mask; }
                        samples += 1.0;
                    }
                }
                for channel in 0..3 {
                    let soft = glow[channel] / samples.max(1.0);
                    output[index][channel] += soft * bloom * 0.48;
                    let warm = if channel == 0 { 1.0 } else if channel == 1 { 0.30 } else { 0.08 };
                    output[index][channel] += soft * halation * warm * 0.36;
                }
            }
        }
        for (index, pixel) in frame.iter_mut().enumerate() {
            let alpha = pixel[3].max(0.0);
            for channel in 0..3 { pixel[channel] = output[index][channel].max(0.0) * alpha; }
        }
    }

    0
}
