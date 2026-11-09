#![allow(unexpected_cfgs)]
use std::cell::RefCell;
use std::vec::Vec;

const MANIFEST: &str = {
    #[cfg(sapphire_glow)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.glow","name":"Sapphire-style Glow","category":"Glow","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Android-native-compatible soft highlight glow; not the proprietary desktop Sapphire plug-in.","params":[{"id":"radius","name":"Glow Radius","type":"slider","default":12,"min":1,"max":48,"decimals":0},{"id":"threshold","name":"Threshold","type":"slider","default":0.72,"min":0.05,"max":0.98,"decimals":2},{"id":"intensity","name":"Intensity","type":"slider","default":0.8,"min":0,"max":2,"decimals":2}]}"# } 
    #[cfg(sapphire_aura)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.glow-aura","name":"Sapphire-style Glow Aura","category":"Glow","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Tinted highlight aura for Android; a compatible recreation, not the proprietary desktop plug-in.","params":[{"id":"radius","name":"Aura Radius","type":"slider","default":18,"min":1,"max":64,"decimals":0},{"id":"intensity","name":"Intensity","type":"slider","default":0.85,"min":0,"max":2,"decimals":2},{"id":"threshold","name":"Threshold","type":"slider","default":0.55,"min":0.05,"max":0.98,"decimals":2},{"id":"tint","name":"Aura Color","type":"color","default":[0.45,0.68,1,1]}]}"# }
    #[cfg(sapphire_lensflare)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.lensflare","name":"Sapphire-style LensFlare","category":"Light","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Procedural lens flare with a movable center and star rays; not the proprietary desktop plug-in.","params":[{"id":"center","name":"Flare Center","type":"point","default":[0.5,0.5]},{"id":"intensity","name":"Intensity","type":"slider","default":0.8,"min":0,"max":2,"decimals":2},{"id":"size","name":"Flare Size","type":"slider","default":0.38,"min":0.08,"max":1.5,"decimals":2},{"id":"color","name":"Flare Color","type":"color","default":[1,0.78,0.48,1]}]}"# }
    #[cfg(sapphire_blur)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.blur","name":"Sapphire-style Blur","category":"Blur","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Fast separable box blur with adjustable radius and mix; compatible recreation.","params":[{"id":"radius","name":"Radius","type":"slider","default":6,"min":1,"max":32,"decimals":0},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_distort)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.distort","name":"Sapphire-style Distort","category":"Distort","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Radial swirl and ripple distortion with a movable center; compatible recreation.","params":[{"id":"center","name":"Distortion Center","type":"point","default":[0.5,0.5]},{"id":"strength","name":"Swirl Strength","type":"slider","default":0.65,"min":-1.5,"max":1.5,"decimals":2},{"id":"radius","name":"Radius","type":"slider","default":0.75,"min":0.1,"max":1.5,"decimals":2},{"id":"ripple","name":"Ripple","type":"slider","default":2,"min":0,"max":12,"decimals":1}]}"# }
    #[cfg(sapphire_stylize)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.stylize","name":"Sapphire-style Stylize","category":"Stylize","version":"1.0.0","author":"EffectCraft Compatibility Layer","description":"Color posterization, contrast and saturation controls; compatible recreation.","params":[{"id":"levels","name":"Color Levels","type":"slider","default":8,"min":2,"max":32,"decimals":0},{"id":"contrast","name":"Contrast","type":"slider","default":1.15,"min":0.5,"max":2,"decimals":2},{"id":"saturation","name":"Saturation","type":"slider","default":1.1,"min":0,"max":2,"decimals":2}]}"# }
    #[cfg(sapphire_motion)]
    { r#"{"api":1,"id":"org.effectcraft.compat.rsmb-motion-blur","name":"RSMB 风格方向模糊（非原版）","category":"Blur","version":"1.1.0","author":"EffectCraft Compatibility Layer","description":"安卓兼容方向模糊效果；不执行电脑版 RSMB，也不进行原版运动矢量估算。","params":[{"id":"angle","name":"方向角度","type":"slider","default":0,"min":0,"max":360,"sliderMin":0,"sliderMax":360,"decimals":0},{"id":"distance","name":"模糊距离","type":"slider","default":18,"min":0,"max":96,"decimals":0},{"id":"mix","name":"效果强度","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
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
    if width == 0 || height == 0 { return Vec::new(); }
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

fn sample_nearest(source: &[[f32; 4]], width: usize, height: usize, x: f32, y: f32) -> [f32; 4] {
    let sx = x.round().clamp(0.0, (width.saturating_sub(1)) as f32) as usize;
    let sy = y.round().clamp(0.0, (height.saturating_sub(1)) as f32) as usize;
    source[sy * width + sx]
}

#[cfg(any(sapphire_glow, sapphire_aura))]
fn render_glow(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], aura: bool) -> i32 {
    let radius = params[0].round().clamp(1.0, 64.0) as usize;
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
    let glow = box_blur(&highlights, width, height, radius);
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
    let cx = params[0] as f32;
    let cy = params[1] as f32;
    let intensity = params[2].clamp(0.0, 2.0) as f32;
    let size = (params[3].clamp(0.08, 1.5) as f32 * width.min(height) as f32).max(2.0);
    let color = [params[4] as f32, params[5] as f32, params[6] as f32];
    let max_dim = width.max(height) as f32;
    for y in 0..height {
        for x in 0..width {
            let dx = x as f32 - cx;
            let dy = y as f32 - cy;
            let distance = (dx * dx + dy * dy).sqrt();
            let radial = (-distance * distance / (size * size)).exp();
            let ring_distance = (distance - size * 0.72).abs();
            let ring = (-(ring_distance * ring_distance) / (size * size * 0.018).max(1.0)).exp();
            let angle = dy.atan2(dx);
            let rays = 0.35 + 0.65 * (angle * 6.0).cos().abs().powf(14.0);
            let ghost = (-((distance - max_dim * 0.22).powi(2)) / (size * size * 0.12).max(1.0)).exp();
            let amount = (radial * 0.75 + ring * 0.22 + ghost * rays * 0.28) * intensity;
            let index = y * width + x;
            for channel in 0..3 { pixels[index][channel] += amount * color[channel] * pixels[index][3].max(0.0); }
        }
    }
    0
}

#[cfg(sapphire_blur)]
fn render_blur(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64]) -> i32 {
    let radius = params[0].round().clamp(1.0, 32.0) as usize;
    let mix = (params[1] / 100.0).clamp(0.0, 1.0) as f32;
    let source = pixels.to_vec();
    let blurred = box_blur(&source, width, height, radius);
    for index in 0..pixels.len() {
        for channel in 0..4 { pixels[index][channel] = source[index][channel] * (1.0 - mix) + blurred[index][channel] * mix; }
    }
    0
}

#[cfg(sapphire_distort)]
fn render_distort(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64]) -> i32 {
    let source = pixels.to_vec();
    let cx = params[0] as f32;
    let cy = params[1] as f32;
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
            pixels[y * width + x] = sample_nearest(&source, width, height, sx, sy);
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
                let pixel = sample_nearest(&source, width, height, x as f32 + dx * t * 2.0, y as f32 + dy * t * 2.0);
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
