#![allow(unexpected_cfgs)]
use std::cell::RefCell;
use std::vec::Vec;

const MANIFEST: &str = {
    #[cfg(sapphire_glow)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.glow","name":"Sapphire-style Glow","category":"Glow","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"Android-native-compatible soft highlight glow; not the proprietary desktop Sapphire plug-in.","params":[{"id":"radius","name":"Glow Radius","type":"slider","default":12,"min":1,"max":48,"decimals":0},{"id":"threshold","name":"Threshold","type":"slider","default":0.72,"min":0.05,"max":0.98,"decimals":2},{"id":"intensity","name":"Intensity","type":"slider","default":0.8,"min":0,"max":2,"decimals":2}]}"# } 
    #[cfg(sapphire_aura)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.glow-aura","name":"Sapphire-style Glow Aura","category":"Glow","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"Tinted highlight aura for Android; a compatible recreation, not the proprietary desktop plug-in.","params":[{"id":"radius","name":"Aura Radius","type":"slider","default":18,"min":1,"max":64,"decimals":0},{"id":"intensity","name":"Intensity","type":"slider","default":0.85,"min":0,"max":2,"decimals":2},{"id":"threshold","name":"Threshold","type":"slider","default":0.55,"min":0.05,"max":0.98,"decimals":2},{"id":"tint","name":"Aura Color","type":"color","default":[0.45,0.68,1,1]}]}"# }
    #[cfg(sapphire_lensflare)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.lensflare","name":"Sapphire-style LensFlare","category":"Light","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"Procedural lens flare with a movable center and star rays; not the proprietary desktop plug-in.","params":[{"id":"center","name":"Flare Center","type":"point","default":[0.5,0.5]},{"id":"intensity","name":"Intensity","type":"slider","default":0.8,"min":0,"max":2,"decimals":2},{"id":"size","name":"Flare Size","type":"slider","default":0.38,"min":0.08,"max":1.5,"decimals":2},{"id":"color","name":"Flare Color","type":"color","default":[1,0.78,0.48,1]}]}"# }
    #[cfg(sapphire_blur)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.blur","name":"Sapphire-style Blur","category":"Blur","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"Fast separable box blur with adjustable radius and mix; compatible recreation.","params":[{"id":"radius","name":"Radius","type":"slider","default":6,"min":1,"max":32,"decimals":0},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_distort)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.distort","name":"Sapphire-style Distort","category":"Distort","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"Radial swirl and ripple distortion with a movable center; compatible recreation.","params":[{"id":"center","name":"Distortion Center","type":"point","default":[0.5,0.5]},{"id":"strength","name":"Swirl Strength","type":"slider","default":0.65,"min":-1.5,"max":1.5,"decimals":2},{"id":"radius","name":"Radius","type":"slider","default":0.75,"min":0.1,"max":1.5,"decimals":2},{"id":"ripple","name":"Ripple","type":"slider","default":2,"min":0,"max":12,"decimals":1}]}"# }
    #[cfg(sapphire_stylize)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.stylize","name":"Sapphire-style Stylize","category":"Stylize","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"Color posterization, contrast and saturation controls; compatible recreation.","params":[{"id":"levels","name":"Color Levels","type":"slider","default":8,"min":2,"max":32,"decimals":0},{"id":"contrast","name":"Contrast","type":"slider","default":1.15,"min":0.5,"max":2,"decimals":2},{"id":"saturation","name":"Saturation","type":"slider","default":1.1,"min":0,"max":2,"decimals":2}]}"# }
    #[cfg(sapphire_motion)]
    { r#"{"api":1,"id":"org.effectcraft.compat.rsmb-motion-blur","name":"RSMB 风格方向模糊（非原版）","category":"Blur","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"安卓兼容方向模糊效果；不执行电脑版 RSMB，也不进行原版运动矢量估算。","params":[{"id":"angle","name":"方向角度","type":"slider","default":0,"min":0,"max":360,"sliderMin":0,"sliderMax":360,"decimals":0},{"id":"distance","name":"模糊距离","type":"slider","default":18,"min":0,"max":96,"decimals":0},{"id":"mix","name":"效果强度","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_glint)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.glint","name":"Sapphire-style Glint","category":"Light","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Threshold-extracted star-ray glint recreation for Android; not the proprietary desktop plug-in.","params":[{"id":"threshold","name":"Threshold","type":"slider","default":0.82,"min":0.05,"max":1.5,"decimals":2},{"id":"intensity","name":"Intensity","type":"slider","default":1.1,"min":0,"max":3,"decimals":2},{"id":"size","name":"Ray Length","type":"slider","default":18,"min":1,"max":96,"decimals":1},{"id":"spikes","name":"Star Spikes","type":"slider","default":4,"min":2,"max":8,"decimals":0},{"id":"rotation","name":"Rotation","type":"angle","default":0},{"id":"color","name":"Glint Color","type":"color","default":[1,0.9,0.72,1]},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_rays)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.rays","name":"Sapphire-style Rays","category":"Light","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Radial light-beam recreation from thresholded highlights; not the proprietary desktop plug-in.","params":[{"id":"center","name":"Ray Origin","type":"point","default":[0.5,0.5]},{"id":"threshold","name":"Threshold","type":"slider","default":0.72,"min":0.05,"max":1.5,"decimals":2},{"id":"intensity","name":"Intensity","type":"slider","default":0.8,"min":0,"max":3,"decimals":2},{"id":"length","name":"Ray Length","type":"slider","default":0.7,"min":0,"max":1,"decimals":2},{"id":"color","name":"Ray Color","type":"color","default":[1,0.9,0.72,1]},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_halftone)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.halftone","name":"Sapphire-style Halftone","category":"Stylize","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Antialiased mobile halftone screen with monochrome or CMY dot modes; compatible recreation.","params":[{"id":"cell_size","name":"Cell Size","type":"slider","default":8,"min":2,"max":48,"decimals":1},{"id":"angle","name":"Screen Angle","type":"angle","default":45},{"id":"contrast","name":"Dot Contrast","type":"slider","default":1,"min":0.25,"max":2.5,"decimals":2},{"id":"softness","name":"Dot Softness","type":"slider","default":0.12,"min":0,"max":0.5,"decimals":2},{"id":"mode","name":"Dot Mode","type":"popup","default":0,"options":["Monochrome","CMY Color"]},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_pixelsort)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.pixelsort","name":"Sapphire-style PixelSort","category":"Stylize","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Deterministic threshold-segment sorting on horizontal or vertical scanlines; compatible recreation.","params":[{"id":"threshold","name":"Sort Threshold","type":"slider","default":0.55,"min":0,"max":1.5,"decimals":2},{"id":"min_length","name":"Minimum Segment","type":"slider","default":4,"min":2,"max":256,"decimals":0},{"id":"max_length","name":"Maximum Segment","type":"slider","default":48,"min":2,"max":512,"decimals":0},{"id":"direction","name":"Direction","type":"popup","default":0,"options":["Horizontal","Vertical"]},{"id":"sort_channel","name":"Sort By","type":"popup","default":0,"options":["Luminance","Red","Green","Blue"]},{"id":"reverse","name":"Reverse","type":"checkbox","default":false},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
};

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

fn box_blur(source: &[[f32; 4]], width: usize, height: usize, radius: usize) -> Vec<[f32; 4]> {
    if width == 0 || height == 0 || source.len() != width.saturating_mul(height) { return Vec::new(); }
    let radius = radius.min(48);
    let denominator = (radius.saturating_mul(2).saturating_add(1)) as f32;
    let mut horizontal = vec![[0.0_f32; 4]; source.len()];
    let mut output = vec![[0.0_f32; 4]; source.len()];
    for y in 0..height {
        let mut sum = [0.0_f32; 4];
        for offset in -(radius as isize)..=(radius as isize) {
            let x = offset.clamp(0, width as isize - 1) as usize;
            for channel in 0..4 { sum[channel] += source[y * width + x][channel]; }
        }
        for x in 0..width {
            let index = y * width + x;
            for channel in 0..4 { horizontal[index][channel] = sum[channel] / denominator; }
            let remove_x = (x as isize - radius as isize).clamp(0, width as isize - 1) as usize;
            let add_x = (x as isize + radius as isize + 1).clamp(0, width as isize - 1) as usize;
            for channel in 0..4 {
                sum[channel] += source[y * width + add_x][channel] - source[y * width + remove_x][channel];
            }
        }
    }
    for x in 0..width {
        let mut sum = [0.0_f32; 4];
        for offset in -(radius as isize)..=(radius as isize) {
            let y = offset.clamp(0, height as isize - 1) as usize;
            for channel in 0..4 { sum[channel] += horizontal[y * width + x][channel]; }
        }
        for y in 0..height {
            let index = y * width + x;
            for channel in 0..4 { output[index][channel] = sum[channel] / denominator; }
            let remove_y = (y as isize - radius as isize).clamp(0, height as isize - 1) as usize;
            let add_y = (y as isize + radius as isize + 1).clamp(0, height as isize - 1) as usize;
            for channel in 0..4 {
                sum[channel] += horizontal[add_y * width + x][channel] - horizontal[remove_y * width + x][channel];
            }
        }
    }
    output
}

fn gaussian_blur(source: &[[f32; 4]], width: usize, height: usize, radius: usize) -> Vec<[f32; 4]> {
    if radius < 3 {
        return box_blur(source, width, height, radius);
    }
    // Three lower-radius box passes approximate a Gaussian kernel while keeping
    // the renderer dependency-free and predictable on Android CPUs.
    let pass_radius = ((radius as f32 / 3.0_f32.sqrt()).round() as usize).max(1).min(48);
    let first = box_blur(source, width, height, pass_radius);
    let second = box_blur(&first, width, height, pass_radius);
    box_blur(&second, width, height, pass_radius)
}

fn frame_pixel(value: f64, extent: usize) -> f32 {
    let max = extent.saturating_sub(1) as f32;
    let value = if value.is_finite() { value as f32 } else { 0.0 };
    value.clamp(0.0, max)
}

fn sample_bilinear(source: &[[f32; 4]], width: usize, height: usize, x: f32, y: f32) -> [f32; 4] {
    let max_x = width.saturating_sub(1) as f32;
    let max_y = height.saturating_sub(1) as f32;
    let x = if x.is_finite() { x.clamp(0.0, max_x) } else { 0.0 };
    let y = if y.is_finite() { y.clamp(0.0, max_y) } else { 0.0 };
    let x0 = x.floor() as usize;
    let y0 = y.floor() as usize;
    let x1 = (x0 + 1).min(width - 1);
    let y1 = (y0 + 1).min(height - 1);
    let tx = x - x0 as f32;
    let ty = y - y0 as f32;
    let p00 = source[y0 * width + x0];
    let p10 = source[y0 * width + x1];
    let p01 = source[y1 * width + x0];
    let p11 = source[y1 * width + x1];
    let mut result = [0.0_f32; 4];
    for channel in 0..4 {
        let top = p00[channel] + (p10[channel] - p00[channel]) * tx;
        let bottom = p01[channel] + (p11[channel] - p01[channel]) * tx;
        result[channel] = top + (bottom - top) * ty;
    }
    result
}

#[cfg(any(sapphire_glow, sapphire_aura))]
fn render_glow(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], aura: bool) -> i32 {
    let radius = (params[0].max(0.0) * _scale.max(0.0)).round().clamp(1.0, 64.0) as usize;
    let (intensity, threshold) = if aura {
        (params[1].clamp(0.0, 2.0), params[2].clamp(0.05, 0.98))
    } else {
        (params[2].clamp(0.0, 2.0), params[1].clamp(0.05, 0.98))
    };
    let intensity = intensity as f32;
    let threshold = threshold as f32;
    let source = pixels.to_vec();
    let mut highlights = Vec::with_capacity(source.len());
    for pixel in &source {
        let alpha = pixel[3].max(0.0);
        if alpha <= 1e-6 { highlights.push([0.0; 4]); continue; }
        let red = (pixel[0] / alpha).max(0.0);
        let green = (pixel[1] / alpha).max(0.0);
        let blue = (pixel[2] / alpha).max(0.0);
        let luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
        let mask = ((luminance - threshold) / (1.0 - threshold).max(1e-4)).clamp(0.0, 1.0);
        let factor = mask * mask;
        highlights.push([pixel[0] * factor, pixel[1] * factor, pixel[2] * factor, alpha * factor]);
    }
    let glow = gaussian_blur(&highlights, width, height, radius);
    for index in 0..pixels.len() {
        if aura {
            let tint = [params[3] as f32, params[4] as f32, params[5] as f32];
            for channel in 0..3 {
                pixels[index][channel] = source[index][channel] + glow[index][channel] * intensity * tint[channel];
            }
        } else {
            for channel in 0..3 { pixels[index][channel] = source[index][channel] + glow[index][channel] * intensity; }
        }
        pixels[index][3] = source[index][3];
    }
    0
}

#[cfg(sapphire_lensflare)]
fn render_lensflare(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64]) -> i32 {
    // The EffectCraft host has already mapped the layer-relative point to frame pixels.
    let cx = frame_pixel(params[0], width);
    let cy = frame_pixel(params[1], height);
    let intensity = params[2].clamp(0.0, 2.0) as f32;
    let size = (params[3].clamp(0.08, 1.5) as f32 * width.min(height) as f32 * _scale.max(0.0) as f32).max(2.0);
    let color = [params[4] as f32, params[5] as f32, params[6] as f32];
    let image_cx = (width.saturating_sub(1) as f32) * 0.5;
    let image_cy = (height.saturating_sub(1) as f32) * 0.5;
    let axis_x = image_cx - cx;
    let axis_y = image_cy - cy;
    let axis_len = (axis_x * axis_x + axis_y * axis_y).sqrt();
    let (axis_x, axis_y) = if axis_len > 1e-4 {
        (axis_x / axis_len, axis_y / axis_len)
    } else {
        (1.0, 0.0)
    };
    let ghost_specs = [(1.25_f32, 0.22_f32), (1.72, 0.15), (-0.42, 0.12), (-0.86, 0.08)];
    let ghosts: Vec<(f32, f32, f32)> = ghost_specs.iter().map(|(position, scale)| {
        (cx + (image_cx - cx) * position, cy + (image_cy - cy) * position, size * scale)
    }).collect();

    for y in 0..height {
        for x in 0..width {
            let dx = x as f32 - cx;
            let dy = y as f32 - cy;
            let distance = (dx * dx + dy * dy).sqrt();
            let angle = dy.atan2(dx);
            let core = (-distance * distance / (size * size * 0.055).max(1.0)).exp();
            let halo = (-distance * distance / (size * size * 0.72).max(1.0)).exp();
            let ring_distance = (distance - size * 0.78).abs();
            let ring = (-(ring_distance * ring_distance) / (size * size * 0.012).max(1.0)).exp();
            let star = (angle * 4.0).cos().abs().powf(22.0);
            let along = dx * axis_x + dy * axis_y;
            let across = -dx * axis_y + dy * axis_x;
            let streak = (-(across * across) / (size * size * 0.0018).max(1.0)).exp()
                * (-along.abs() / (size * 2.2).max(1.0)).exp();
            let mut ghost_energy = 0.0_f32;
            for (gx, gy, ghost_size) in &ghosts {
                let gdx = x as f32 - *gx;
                let gdy = y as f32 - *gy;
                let r2 = gdx * gdx + gdy * gdy;
                ghost_energy += (-r2 / (ghost_size * ghost_size * 0.42).max(1.0)).exp();
            }
            let amount = (core * 0.62 + halo * 0.12 + ring * 0.2
                + halo * star * 0.18 + streak * 0.16 + ghost_energy * 0.11) * intensity;
            let index = y * width + x;
            for channel in 0..3 {
                pixels[index][channel] += amount * color[channel] * pixels[index][3].max(0.0);
            }
        }
    }
    0
}

#[cfg(sapphire_blur)]
fn render_blur(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64]) -> i32 {
    let radius = (params[0].max(0.0) * _scale.max(0.0)).round().clamp(1.0, 32.0) as usize;
    let mix = (params[1] / 100.0).clamp(0.0, 1.0) as f32;
    let source = pixels.to_vec();
    let blurred = gaussian_blur(&source, width, height, radius);
    for index in 0..pixels.len() {
        for channel in 0..4 { pixels[index][channel] = source[index][channel] * (1.0 - mix) + blurred[index][channel] * mix; }
    }
    0
}

#[cfg(sapphire_distort)]
fn render_distort(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64]) -> i32 {
    let source = pixels.to_vec();
    let cx = frame_pixel(params[0], width);
    let cy = frame_pixel(params[1], height);
    let strength = params[2].clamp(-1.5, 1.5) as f32;
    let radius = (params[3].clamp(0.1, 1.5) as f32 * width.min(height) as f32).max(1.0);
    let ripple = params[4].clamp(0.0, 12.0) as f32;
    for y in 0..height {
        for x in 0..width {
            let dx = x as f32 - cx;
            let dy = y as f32 - cy;
            let distance = (dx * dx + dy * dy).sqrt();
            let normalized = (distance / radius).clamp(0.0, 1.0);
            if normalized >= 1.0 { continue; }
            let angle = strength * 1.7 * (1.0 - normalized).powi(2)
                + (normalized * std::f32::consts::PI * 8.0).sin() * ripple * 0.035;
            let (sin_angle, cos_angle) = angle.sin_cos();
            let sx = cx + dx * cos_angle - dy * sin_angle;
            let sy = cy + dx * sin_angle + dy * cos_angle;
            pixels[y * width + x] = sample_bilinear(&source, width, height, sx, sy);
        }
    }
    0
}

#[cfg(sapphire_stylize)]
fn render_stylize(pixels: &mut [[f32; 4]], params: &[f64]) -> i32 {
    let levels = params[0].round().clamp(2.0, 32.0) as f32;
    let contrast = params[1].clamp(0.5, 2.0) as f32;
    let saturation = params[2].clamp(0.0, 2.0) as f32;
    let steps = (levels - 1.0).max(1.0);
    for pixel in pixels.iter_mut() {
        let alpha = pixel[3].max(0.0);
        if alpha <= 1e-6 { continue; }
        let mut rgb = [pixel[0] / alpha, pixel[1] / alpha, pixel[2] / alpha];
        let luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
        for channel in 0..3 {
            let saturated = luminance + (rgb[channel] - luminance) * saturation;
            let contrasted = ((saturated - 0.5) * contrast + 0.5).clamp(0.0, 1.0);
            rgb[channel] = (contrasted * steps).round() / steps;
            pixel[channel] = rgb[channel] * alpha;
        }
    }
    0
}

#[cfg(sapphire_motion)]
fn render_motion(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64]) -> i32 {
    let angle = (params[0] as f32).to_radians();
    let distance = params[1].clamp(0.0, 96.0) as f32;
    let mix = (params[2] / 100.0).clamp(0.0, 1.0) as f32;
    if distance <= 0.01 || mix <= 0.0 { return 0; }
    let source = pixels.to_vec();
    let dx = angle.cos() * distance * 0.5;
    let dy = angle.sin() * distance * 0.5;
    const SAMPLES: i32 = 13;
    for y in 0..height {
        for x in 0..width {
            let mut sum = [0.0_f32; 4];
            for sample in 0..SAMPLES {
                let t = sample as f32 / (SAMPLES - 1) as f32 - 0.5;
                let pixel = sample_bilinear(&source, width, height, x as f32 + dx * t * 2.0, y as f32 + dy * t * 2.0);
                for channel in 0..4 { sum[channel] += pixel[channel] / SAMPLES as f32; }
            }
            let index = y * width + x;
            for channel in 0..4 { pixels[index][channel] = source[index][channel] * (1.0 - mix) + sum[channel] * mix; }
        }
    }
    0
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn ec_render(pixels: i32, width: i32, height: i32, params: i32, nparams: i32, _time: f64, _scale: f64) -> i32 {
    if width <= 0 || height <= 0 || nparams < 1 { return 1; }
    let Some(count) = (width as usize).checked_mul(height as usize) else { return 1; };
    if count == 0 || count > 32_000_000 { return 1; }
    let needed = {
        #[cfg(any(sapphire_glow, sapphire_aura, sapphire_blur))] { if cfg!(sapphire_glow) { 3 } else if cfg!(sapphire_aura) { 7 } else { 2 } }
        #[cfg(sapphire_lensflare)] { 8 }
        #[cfg(sapphire_distort)] { 5 }
        #[cfg(sapphire_stylize)] { 3 }
        #[cfg(sapphire_motion)] { 3 }
    };
    if nparams < needed { return 1; }
    let values = unsafe { std::slice::from_raw_parts(params as *const f64, nparams as usize) };
    let frame = unsafe { std::slice::from_raw_parts_mut(pixels as *mut [f32; 4], count) };
    let w = width as usize;
    let h = height as usize;
    #[cfg(sapphire_glow)] { render_glow(frame, w, h, values, false) }
    #[cfg(sapphire_aura)] { render_glow(frame, w, h, values, true) }
    #[cfg(sapphire_lensflare)] { render_lensflare(frame, w, h, values) }
    #[cfg(sapphire_blur)] { render_blur(frame, w, h, values) }
    #[cfg(sapphire_distort)] { render_distort(frame, w, h, values) }
    #[cfg(sapphire_stylize)] { render_stylize(frame, values) }
    #[cfg(sapphire_motion)] { render_motion(frame, w, h, values) }
}


#[cfg(test)]
mod tests {
    use super::{frame_pixel, sample_bilinear};

    #[test]
    fn host_mapped_frame_pixel_is_not_scaled_twice() {
        assert!((frame_pixel(7.0, 20) - 7.0).abs() < 1e-6);
        assert!((frame_pixel(0.5, 20) - 0.5).abs() < 1e-6);
    }

    #[test]
    fn frame_pixel_is_clamped_and_non_finite_is_safe() {
        assert!((frame_pixel(100.0, 20) - 19.0).abs() < 1e-6);
        assert!((frame_pixel(f64::NAN, 20)).abs() < 1e-6);
    }

    #[test]
    fn bilinear_sampling_interpolates_between_pixels() {
        let pixels = [
            [0.0, 0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0, 1.0],
            [1.0, 1.0, 1.0, 1.0],
        ];
        let sample = sample_bilinear(&pixels, 2, 2, 0.5, 0.5);
        assert!((sample[0] - 0.5).abs() < 1e-6);
        assert!((sample[1] - 0.5).abs() < 1e-6);
        assert!((sample[2] - 0.25).abs() < 1e-6);
        assert!((sample[3] - 1.0).abs() < 1e-6);
    }

    #[test]
    fn bilinear_sampling_clamps_to_frame_edges() {
        let pixels = [[0.2, 0.3, 0.4, 1.0], [0.8, 0.7, 0.6, 1.0]];
        let left = sample_bilinear(&pixels, 2, 1, -10.0, 0.0);
        let right = sample_bilinear(&pixels, 2, 1, 10.0, 0.0);
        assert!((left[0] - 0.2).abs() < 1e-6);
        assert!((right[0] - 0.8).abs() < 1e-6);
    }
}
