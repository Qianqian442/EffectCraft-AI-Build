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
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.glint","name":"Sapphire-style Glint","category":"Light","version":"1.2.0","author":"EffectCraft Compatibility Layer","description":"Android recreation mapped to documented S_Glint threshold, independent ray families, RGB ray lengths and compositing controls; not the proprietary desktop plug-in.","params":[{"id":"threshold","name":"Threshold","type":"slider","default":0.7,"min":0,"max":1.5,"decimals":2},{"id":"brightness_x","name":"Brightness X","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"brightness_y","name":"Brightness Y","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"brightness_diag1","name":"Brightness Diag1","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"brightness_diag2","name":"Brightness Diag2","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"color","name":"Scale Colors","type":"color","default":[1,1,1,1]},{"id":"threshold_add_color","name":"Threshold Add Color","type":"color","default":[0,0,0,1]},{"id":"threshold_blur","name":"Threshold Blur","type":"slider","default":0.0896,"min":0,"max":64,"decimals":2},{"id":"size","name":"Size","type":"slider","default":2,"min":0,"max":128,"decimals":2},{"id":"size_x","name":"Size X","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"size_y","name":"Size Y","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"size_diag1","name":"Size Diag1","type":"slider","default":0.75,"min":0,"max":4,"decimals":2},{"id":"size_diag2","name":"Size Diag2","type":"slider","default":0.75,"min":0,"max":4,"decimals":2},{"id":"size_red","name":"Size Red","type":"slider","default":0.5,"min":0,"max":4,"decimals":2},{"id":"size_green","name":"Size Green","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"size_blue","name":"Size Blue","type":"slider","default":1.5,"min":0,"max":4,"decimals":2},{"id":"blur_glint","name":"Blur Glint","type":"slider","default":0,"min":0,"max":64,"decimals":2},{"id":"hue_shift","name":"Hue Shift","type":"slider","default":0,"min":-1,"max":1,"decimals":2},{"id":"affect_alpha","name":"Affect Alpha","type":"slider","default":0,"min":0,"max":2,"decimals":2},{"id":"glint_from_alpha","name":"Glint From Alpha","type":"slider","default":0,"min":0,"max":1,"decimals":2},{"id":"glint_under_source","name":"Glint Under Source","type":"checkbox","default":false},{"id":"source_opacity","name":"Source Opacity","type":"slider","default":1,"min":0,"max":1,"decimals":2},{"id":"swap_diagonals","name":"Swap Diagonals","type":"checkbox","default":false},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_rays)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.rays","name":"Sapphire-style Rays","category":"Light","version":"1.2.0","author":"EffectCraft Compatibility Layer","description":"Android recreation mapped to S_Rays light/dark mode, center, signed ray length, channel lengths, reverse rays, brightness bias, blur and resolution controls.","params":[{"id":"effect","name":"Effect","type":"popup","default":0,"options":["Light Rays","Dark Rays"]},{"id":"center","name":"Center","type":"point","default":[0.5,0.5]},{"id":"rays_length","name":"Rays Length","type":"slider","default":0.25,"min":-5,"max":3,"decimals":2},{"id":"length_red","name":"Length Red","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"length_green","name":"Length Green","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"length_blue","name":"Length Blue","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"reverse_rays","name":"Reverse Rays","type":"slider","default":0,"min":0,"max":1,"decimals":2},{"id":"rays_brightness","name":"Rays Brightness","type":"slider","default":3,"min":0,"max":8,"decimals":2},{"id":"rays_darkness","name":"Rays Darkness","type":"slider","default":3,"min":0,"max":8,"decimals":2},{"id":"blur_rays","name":"Blur Rays","type":"slider","default":0,"min":0,"max":64,"decimals":2},{"id":"blur_rays_rel_x","name":"Blur Rays Rel X","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"blur_rays_rel_y","name":"Blur Rays Rel Y","type":"slider","default":1,"min":0,"max":4,"decimals":2},{"id":"rays_color","name":"Rays Color","type":"color","default":[1,1,1,1]},{"id":"rays_color_dark","name":"Rays Color Dark","type":"color","default":[0,0,0,1]},{"id":"bias_outer_bright","name":"Bias Outer Bright","type":"slider","default":0,"min":0,"max":1,"decimals":2},{"id":"rays_res","name":"Rays Res","type":"popup","default":0,"options":["Full","Half","Quarter"]},{"id":"threshold","name":"Threshold","type":"slider","default":0.5,"min":0,"max":1.5,"decimals":2},{"id":"threshold_add_color","name":"Threshold Add Color","type":"color","default":[0,0,0,1]},{"id":"rays_from_alpha","name":"Rays From Alpha","type":"slider","default":0,"min":0,"max":1,"decimals":2},{"id":"use_source_chroma","name":"Use Source Chroma","type":"slider","default":1,"min":0,"max":1,"decimals":2},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_halftone)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.halftone","name":"Sapphire-style HalfTone","category":"Stylize","version":"1.2.0","author":"EffectCraft Compatibility Layer","description":"Antialiased mobile halftone mapped to documented S_HalfTone black/white dots, frequency, angle, width, sharpness, lighten, source smoothing, colors and pattern shift.","params":[{"id":"dots","name":"Dots","type":"popup","default":0,"options":["Black","White"]},{"id":"dots_frequency","name":"Dots Frequency","type":"slider","default":50,"min":1,"max":200,"decimals":2},{"id":"dots_angle","name":"Dots Angle","type":"angle","default":30},{"id":"dots_rel_width","name":"Dots Rel Width","type":"slider","default":1,"min":0.01,"max":4,"decimals":2},{"id":"dots_sharpness","name":"Dots Sharpness","type":"slider","default":4,"min":0,"max":32,"decimals":2},{"id":"dots_lighten","name":"Dots Lighten","type":"slider","default":0,"min":-1,"max":1,"decimals":2},{"id":"smooth_source","name":"Smooth Source","type":"slider","default":0,"min":0,"max":64,"decimals":2},{"id":"color1","name":"Color1","type":"color","default":[1,1,1,1]},{"id":"color0","name":"Color0","type":"color","default":[0,0,0,1]},{"id":"dots_shift","name":"Dots Shift","type":"point","default":[0,0]},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
    #[cfg(sapphire_pixelsort)]
    { r#"{"api":1,"id":"org.effectcraft.sapphire.compat.pixelsort","name":"Sapphire-style PixelSort","category":"Stylize","version":"1.2.0","author":"EffectCraft Compatibility Layer","description":"Android recreation of S_PixelSort linear, radial and circular scan paths with keyframeable centers, angles, ranges, chunk size and variation.","params":[{"id":"effect","name":"Effect","type":"popup","default":0,"options":["Linear","Radial","Circular"]},{"id":"threshold","name":"Threshold","type":"slider","default":0.5,"min":0,"max":1.5,"decimals":2},{"id":"sort_angle","name":"Sort Angle","type":"angle","default":0},{"id":"center","name":"Center","type":"point","default":[0.5,0.5]},{"id":"radial_start_angle","name":"Radial Start Angle","type":"angle","default":0},{"id":"degrees_sorted","name":"Degrees Sorted","type":"slider","default":360,"min":0,"max":360,"decimals":0},{"id":"inner_radius","name":"Inner Radius","type":"slider","default":0.1,"min":0,"max":1,"decimals":2},{"id":"ray_length","name":"Ray Length","type":"slider","default":0.8,"min":0,"max":3,"decimals":2},{"id":"vary_radius","name":"Vary Radius","type":"slider","default":0.1,"min":0,"max":1,"decimals":2},{"id":"circular_start_angle","name":"Circular Start Angle","type":"angle","default":0},{"id":"circular_degrees_sorted","name":"Circular Degrees Sorted","type":"slider","default":270,"min":0,"max":360,"decimals":0},{"id":"circle_center","name":"Circle Center","type":"point","default":[0.5,0.5]},{"id":"vary_start","name":"Vary Start","type":"slider","default":0.15,"min":0,"max":1,"decimals":2},{"id":"min_length","name":"Minimum Segment","type":"slider","default":4,"min":2,"max":256,"decimals":0},{"id":"max_length","name":"Maximum Segment","type":"slider","default":48,"min":2,"max":1024,"decimals":0},{"id":"sort_by","name":"Sort By","type":"popup","default":0,"options":["Luminance","Red","Green","Blue"]},{"id":"reverse","name":"Reverse","type":"checkbox","default":false},{"id":"mix","name":"Mix","type":"slider","default":100,"min":0,"max":100,"decimals":0}]}"# }
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
fn render_glow(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], aura: bool, scale: f64) -> i32 {
    let radius = (params[0].max(0.0) * scale.max(0.0)).round().clamp(1.0, 64.0) as usize;
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
fn render_lensflare(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], scale: f64) -> i32 {
    // The EffectCraft host has already mapped the layer-relative point to frame pixels.
    let cx = frame_pixel(params[0], width);
    let cy = frame_pixel(params[1], height);
    let intensity = params[2].clamp(0.0, 2.0) as f32;
    let size = (params[3].clamp(0.08, 1.5) as f32 * width.min(height) as f32 * scale.max(0.0) as f32).max(2.0);
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
fn render_blur(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], scale: f64) -> i32 {
    let radius = (params[0].max(0.0) * scale.max(0.0)).round().clamp(1.0, 32.0) as usize;
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


fn smoothstep(edge0: f32, edge1: f32, value: f32) -> f32 {
    if (edge1 - edge0).abs() < 1e-6 { return if value >= edge1 { 1.0 } else { 0.0 }; }
    let t = ((value - edge0) / (edge1 - edge0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

fn straight_luminance(pixel: [f32; 4]) -> f32 {
    let alpha = pixel[3].max(1e-6);
    let red = (pixel[0] / alpha).max(0.0);
    let green = (pixel[1] / alpha).max(0.0);
    let blue = (pixel[2] / alpha).max(0.0);
    0.2126 * red + 0.7152 * green + 0.0722 * blue
}

fn hue_rotate_rgb(rgb: [f32; 3], shift: f32) -> [f32; 3] {
    if shift.abs() < 1e-6 { return rgb; }
    let y = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
    let i = 0.596 * rgb[0] - 0.275 * rgb[1] - 0.321 * rgb[2];
    let q = 0.212 * rgb[0] - 0.523 * rgb[1] + 0.311 * rgb[2];
    let angle = shift * std::f32::consts::TAU;
    let (sn, cs) = angle.sin_cos();
    let ri = i * cs - q * sn;
    let rq = i * sn + q * cs;
    [
        y + 0.956 * ri + 0.621 * rq,
        y - 0.272 * ri - 0.647 * rq,
        y - 1.106 * ri + 1.703 * rq,
    ]
}

#[cfg(sapphire_glint)]
fn render_glint(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], scale: f64) -> i32 {
    let threshold = params[0].clamp(0.0, 1.5) as f32;
    let brightness = [params[1] as f32, params[2] as f32, params[3] as f32, params[4] as f32];
    let tint = [params[5] as f32, params[6] as f32, params[7] as f32];
    let threshold_add = [params[9] as f32, params[10] as f32, params[11] as f32];
    let threshold_blur = (params[13].max(0.0) * scale.max(0.0)).clamp(0.0, 48.0) as usize;
    let base_size = (params[14].max(0.0) * scale.max(0.0)).clamp(0.0, 128.0) as f32;
    let axis_size = [
        params[15].max(0.0) as f32,
        params[16].max(0.0) as f32,
        params[17].max(0.0) as f32,
        params[18].max(0.0) as f32,
    ];
    let channel_size = [params[19].max(0.0) as f32, params[20].max(0.0) as f32, params[21].max(0.0) as f32];
    let blur_glint = (params[22].max(0.0) * scale.max(0.0)).clamp(0.0, 64.0) as usize;
    let hue_shift = params[23] as f32;
    let affect_alpha = params[24].clamp(0.0, 2.0) as f32;
    let glint_from_alpha = params[25].clamp(0.0, 1.0) as f32;
    let glint_under_source = params[26] >= 0.5;
    let source_opacity = params[27].clamp(0.0, 1.0) as f32;
    let swap_diagonals = params[28] >= 0.5;
    let mix = (params[29] / 100.0).clamp(0.0, 1.0) as f32;
    if base_size <= 0.0 || mix <= 0.0 || brightness.iter().all(|value| *value <= 0.0) { return 0; }

    let source = pixels.to_vec();
    let threshold_input = if threshold_blur > 0 {
        gaussian_blur(&source, width, height, threshold_blur)
    } else {
        source.clone()
    };
    let mut highlights = Vec::with_capacity(source.len());
    for px in &threshold_input {
        let luma = straight_luminance(*px);
        let signal = luma * (1.0 - glint_from_alpha) + px[3].clamp(0.0, 1.0) * glint_from_alpha;
        let threshold_shift = threshold_add[0] * (px[0] / px[3].max(1e-6))
            + threshold_add[1] * (px[1] / px[3].max(1e-6))
            + threshold_add[2] * (px[2] / px[3].max(1e-6));
        let weight = smoothstep(threshold + threshold_shift, threshold + threshold_shift + 0.16, signal);
        highlights.push([px[0] * weight, px[1] * weight, px[2] * weight, px[3] * weight]);
    }

    let mut glint_layer = vec![[0.0_f32; 4]; source.len()];
    let mut angles = [0.0_f32, std::f32::consts::FRAC_PI_2, std::f32::consts::FRAC_PI_4, -std::f32::consts::FRAC_PI_4];
    let mut axis_brightness = brightness;
    let mut sizes = axis_size;
    if swap_diagonals {
        angles.swap(2, 3);
        axis_brightness.swap(2, 3);
        sizes.swap(2, 3);
    }
    const STEPS: usize = 8;
    for y in 0..height {
        for x in 0..width {
            let mut star = [0.0_f32; 3];
            for axis in 0..4 {
                if axis_brightness[axis] <= 0.0 || sizes[axis] <= 0.0 { continue; }
                let (sn, cs) = angles[axis].sin_cos();
                let ray_length = base_size * sizes[axis];
                for step in 1..=STEPS {
                    let distance = ray_length * step as f32 / STEPS as f32;
                    let attenuation = (-(distance / ray_length.max(1.0)) * 2.2).exp()
                        * axis_brightness[axis] / (STEPS as f32 * 2.0);
                    for sign in [-1.0_f32, 1.0_f32] {
                        for channel in 0..3 {
                            let channel_distance = distance * channel_size[channel].max(0.0);
                            let sample = sample_bilinear(
                                &highlights, width, height,
                                x as f32 + cs * channel_distance * sign,
                                y as f32 + sn * channel_distance * sign,
                            );
                            star[channel] += sample[channel] * attenuation;
                        }
                    }
                }
            }
            let rotated = hue_rotate_rgb([
                star[0] * tint[0],
                star[1] * tint[1],
                star[2] * tint[2],
            ], hue_shift);
            let idx = y * width + x;
            glint_layer[idx] = [rotated[0], rotated[1], rotated[2], rotated.iter().copied().fold(0.0_f32, f32::max)];
        }
    }
    let glint_layer = if blur_glint > 0 {
        gaussian_blur(&glint_layer, width, height, blur_glint)
    } else {
        glint_layer
    };
    for idx in 0..pixels.len() {
        let src = source[idx];
        let glint = glint_layer[idx];
        let glint_alpha = (glint[3] * affect_alpha).clamp(0.0, 1.0);
        let behind = if glint_under_source { (1.0 - src[3].clamp(0.0, 1.0)) } else { 1.0 };
        let src_rgb = [
            src[0] * source_opacity,
            src[1] * source_opacity,
            src[2] * source_opacity,
        ];
        let result = [
            src_rgb[0] + glint[0] * behind,
            src_rgb[1] + glint[1] * behind,
            src_rgb[2] + glint[2] * behind,
        ];
        for c in 0..3 { pixels[idx][c] = src[c] * (1.0 - mix) + result[c] * mix; }
        pixels[idx][3] = (src[3] * (1.0 - mix) + (src[3] * source_opacity + glint_alpha) * mix).clamp(0.0, 1.0);
    }
    0
}

#[cfg(sapphire_rays)]
fn render_rays(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], scale: f64) -> i32 {
    let dark_mode = params[0].round() >= 1.0;
    let cx = frame_pixel(params[1], width);
    let cy = frame_pixel(params[2], height);
    let rays_length = params[3] as f32;
    let channel_length = [params[4] as f32, params[5] as f32, params[6] as f32];
    let reverse = params[7].clamp(0.0, 1.0) as f32;
    let brightness = params[8].clamp(0.0, 8.0) as f32;
    let darkness = params[9].clamp(0.0, 8.0) as f32;
    let blur_radius = (params[10].max(0.0) * scale.max(0.0)
        * ((params[11].max(0.0) + params[12].max(0.0)) * 0.5).clamp(0.0, 4.0))
        .clamp(0.0, 64.0) as usize;
    let ray_color = [params[13] as f32, params[14] as f32, params[15] as f32];
    let dark_color = [params[17] as f32, params[18] as f32, params[19] as f32];
    let bias = params[21].clamp(0.0, 1.0) as f32;
    let resolution = params[22].round().clamp(0.0, 2.0) as usize;
    let threshold = params[23].clamp(0.0, 1.5) as f32;
    let threshold_add = [params[24] as f32, params[25] as f32, params[26] as f32];
    let from_alpha = params[28].clamp(0.0, 1.0) as f32;
    let use_chroma = params[29].clamp(0.0, 1.0) as f32;
    let mix = (params[30] / 100.0).clamp(0.0, 1.0) as f32;
    if rays_length.abs() < 1e-4 || mix <= 0.0 || (if dark_mode { darkness } else { brightness }) <= 0.0 { return 0; }

    let source = pixels.to_vec();
    let mut light_map = Vec::with_capacity(source.len());
    let mut dark_map = Vec::with_capacity(source.len());
    for px in &source {
        let alpha = px[3].clamp(0.0, 1.0);
        let luma = straight_luminance(*px);
        let signal = luma * (1.0 - from_alpha) + alpha * from_alpha;
        let threshold_shift = threshold_add[0] * (px[0] / alpha.max(1e-6))
            + threshold_add[1] * (px[1] / alpha.max(1e-6))
            + threshold_add[2] * (px[2] / alpha.max(1e-6));
        let local_threshold = (threshold + threshold_shift).clamp(0.0, 1.5);
        let light = smoothstep(local_threshold, local_threshold + 0.18, signal);
        let dark = smoothstep(local_threshold, local_threshold + 0.18, 1.0 - signal);
        let rgb = [
            px[0] * use_chroma + luma * alpha * (1.0 - use_chroma),
            px[1] * use_chroma + luma * alpha * (1.0 - use_chroma),
            px[2] * use_chroma + luma * alpha * (1.0 - use_chroma),
        ];
        light_map.push([rgb[0] * light, rgb[1] * light, rgb[2] * light, alpha * light]);
        dark_map.push([dark * alpha, dark * alpha, dark * alpha, alpha * dark]);
    }
    let max_dim = width.max(height) as f32;
    let ray_distance = rays_length.abs() * max_dim;
    let steps_base = match resolution { 1 => 16, 2 => 8, _ => 32 };
    let signed = rays_length.signum();
    let mut ray_layer = vec![[0.0_f32; 4]; source.len()];
    for y in 0..height {
        for x in 0..width {
            let dx = cx - x as f32;
            let dy = cy - y as f32;
            let mut accum = [0.0_f32; 3];
            let mut accum_dark = 0.0_f32;
            for direction in 0..=1 {
                let direction_weight = if direction == 0 { 1.0 } else { reverse };
                if direction_weight <= 0.0 { continue; }
                for channel in 0..3 {
                    let distance = ray_distance * channel_length[channel].max(0.0);
                    for step in 0..steps_base {
                        let t = step as f32 / (steps_base - 1).max(1) as f32;
                        let ray_t = signed * t * distance;
                        let sign = if direction == 0 { 1.0 } else { -1.0 };
                        let sample = sample_bilinear(
                            if dark_mode { &dark_map } else { &light_map },
                            width, height,
                            x as f32 + dx * ray_t / ray_distance.max(1.0) * sign,
                            y as f32 + dy * ray_t / ray_distance.max(1.0) * sign,
                        );
                        let fade = if bias < 0.5 {
                            (1.0 - t).powf((0.5 - bias) * 4.0 + 0.01)
                        } else {
                            t.powf((bias - 0.5) * 4.0 + 0.01)
                        };
                        let weight = fade * direction_weight / steps_base as f32;
                        if dark_mode {
                            accum_dark += sample[0] * weight;
                        } else {
                            accum[channel] += sample[channel] * weight;
                        }
                    }
                }
            }
            let idx = y * width + x;
            if dark_mode {
                ray_layer[idx] = [
                    -accum_dark * darkness * dark_color[0],
                    -accum_dark * darkness * dark_color[1],
                    -accum_dark * darkness * dark_color[2],
                    accum_dark * darkness,
                ];
            } else {
                ray_layer[idx] = [
                    accum[0] * brightness * ray_color[0],
                    accum[1] * brightness * ray_color[1],
                    accum[2] * brightness * ray_color[2],
                    accum.iter().copied().fold(0.0_f32, f32::max) * brightness,
                ];
            }
        }
    }
    let ray_layer = if blur_radius > 0 {
        gaussian_blur(&ray_layer, width, height, blur_radius)
    } else { ray_layer };
    for idx in 0..pixels.len() {
        for channel in 0..3 {
            let result = if dark_mode {
                (source[idx][channel] + ray_layer[idx][channel]).max(0.0)
            } else {
                source[idx][channel] + ray_layer[idx][channel]
            };
            pixels[idx][channel] = source[idx][channel] * (1.0 - mix) + result * mix;
        }
        pixels[idx][3] = source[idx][3];
    }
    0
}

#[cfg(sapphire_halftone)]
fn render_halftone(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64], scale: f64) -> i32 {
    let white_dots = params[0].round() >= 1.0;
    let frequency = params[1].max(1.0) as f32;
    let angle = (params[2] as f32).to_radians();
    let relative_width = params[3].clamp(0.01, 4.0) as f32;
    let sharpness = params[4].max(0.0) as f32;
    let lighten = params[5] as f32;
    let smooth_source = (params[6].max(0.0) * scale.max(0.0)).clamp(0.0, 48.0) as usize;
    let color1 = [params[7] as f32, params[8] as f32, params[9] as f32];
    let color0 = [params[11] as f32, params[12] as f32, params[13] as f32];
    let shift_x = params[15] as f32;
    let shift_y = params[16] as f32;
    let mix = (params[17] / 100.0).clamp(0.0, 1.0) as f32;
    if mix <= 0.0 { return 0; }
    let source = pixels.to_vec();
    let filtered = if smooth_source > 0 {
        gaussian_blur(&source, width, height, smooth_source)
    } else {
        source.clone()
    };
    let cell = (width.max(height) as f32 / frequency.max(1.0)).clamp(1.0, 128.0);
    let (sn, cs) = angle.sin_cos();
    let half = cell * 0.5;
    let cx = width as f32 * 0.5;
    let cy = height as f32 * 0.5;
    let edge_width = (cell / (sharpness * 4.0 + 1.0)).clamp(0.25, cell * 0.5);
    for y in 0..height {
        for x in 0..width {
            let px = x as f32 - cx - shift_x;
            let py = y as f32 - cy - shift_y;
            let fx = px * cs + py * sn;
            let fy = -px * sn + py * cs;
            let gx = (fx / cell).floor();
            let gy = (fy / cell).floor();
            let local_x = fx - (gx + 0.5) * cell;
            let local_y = fy - (gy + 0.5) * cell;
            let sx = ((gx + 0.5) * cell * cs - (gy + 0.5) * cell * sn + cx + shift_x)
                .clamp(0.0, width.saturating_sub(1) as f32);
            let sy = ((gx + 0.5) * cell * sn + (gy + 0.5) * cell * cs + cy + shift_y)
                .clamp(0.0, height.saturating_sub(1) as f32);
            let sample = sample_bilinear(&filtered, width, height, sx, sy);
            let alpha = sample[3].max(1e-6);
            let luma = (straight_luminance(sample) + lighten).clamp(0.0, 1.0);
            let ink = if white_dots { luma } else { 1.0 - luma };
            let radius = ink.sqrt() * half * 0.96;
            let screen_radius = (((local_x / relative_width).powi(2) + local_y.powi(2)).sqrt());
            let dot = 1.0 - smoothstep(radius - edge_width, radius + edge_width, screen_radius);
            let (dot_color, bg_color) = if white_dots { (color1, color0) } else { (color0, color1) };
            let idx = y * width + x;
            for channel in 0..3 {
                let out = (bg_color[channel] * (1.0 - dot) + dot_color[channel] * dot) * source[idx][3];
                pixels[idx][channel] = source[idx][channel] * (1.0 - mix) + out * mix;
            }
            pixels[idx][3] = source[idx][3];
        }
    }
    0
}

#[cfg(sapphire_pixelsort)]
fn sort_pixel_path(
    path: &[usize],
    source: &[[f32; 4]],
    sorted: &mut [[f32; 4]],
    threshold: f32,
    min_length: usize,
    max_length: usize,
    sort_channel: usize,
    reverse: bool,
) {
    let key = |px: &[f32; 4]| -> f32 {
        let alpha = px[3].max(1e-6);
        match sort_channel {
            1 => px[0] / alpha,
            2 => px[1] / alpha,
            3 => px[2] / alpha,
            _ => straight_luminance(*px),
        }
    };
    let mut cursor = 0usize;
    while cursor < path.len() {
        while cursor < path.len() && straight_luminance(source[path[cursor]]) < threshold {
            cursor += 1;
        }
        let start = cursor;
        while cursor < path.len() && straight_luminance(source[path[cursor]]) >= threshold {
            cursor += 1;
        }
        let end = cursor;
        if end.saturating_sub(start) < min_length { continue; }
        let mut chunk_start = start;
        while chunk_start < end {
            let chunk_end = (chunk_start + max_length).min(end);
            if chunk_end - chunk_start >= min_length {
                let mut segment: Vec<[f32; 4]> = path[chunk_start..chunk_end].iter().map(|index| source[*index]).collect();
                segment.sort_by(|a,b| {
                    let order = key(a).total_cmp(&key(b));
                    if reverse { order.reverse() } else { order }
                });
                for (offset, pixel) in segment.into_iter().enumerate() {
                    sorted[path[chunk_start + offset]] = pixel;
                }
            }
            chunk_start = chunk_end;
        }
    }
}

#[cfg(sapphire_pixelsort)]
fn render_pixelsort(pixels: &mut [[f32; 4]], width: usize, height: usize, params: &[f64]) -> i32 {
    let pattern = params[0].round().clamp(0.0, 2.0) as usize;
    let threshold = params[1].clamp(0.0, 1.5) as f32;
    let sort_angle = (params[2] as f32).to_radians();
    let center = (frame_pixel(params[3], width), frame_pixel(params[4], height));
    let radial_start = (params[5] as f32).to_radians();
    let radial_degrees = params[6].clamp(0.0, 360.0) as f32;
    let inner_radius = params[7].clamp(0.0, 1.0) as f32;
    let ray_length = params[8].clamp(0.0, 3.0) as f32;
    let vary_radius = params[9].clamp(0.0, 1.0) as f32;
    let circular_start = (params[10] as f32).to_radians();
    let circular_degrees = params[11].clamp(0.0, 360.0) as f32;
    let circle_center = (frame_pixel(params[12], width), frame_pixel(params[13], height));
    let vary_start = params[14].clamp(0.0, 1.0) as f32;
    let min_length = params[15].round().clamp(2.0, 256.0) as usize;
    let max_length = params[16].round().clamp(min_length as f64, 1024.0) as usize;
    let sort_channel = params[17].round().clamp(0.0, 3.0) as usize;
    let reverse = params[18] >= 0.5;
    let mix = (params[19] / 100.0).clamp(0.0, 1.0) as f32;
    if mix <= 0.0 { return 0; }

    let source = pixels.to_vec();
    let mut sorted = source.clone();
    let max_radius = (((width as f32).powi(2) + (height as f32).powi(2)).sqrt() * 0.5).max(1.0);
    let chunk_limit = ((ray_length * width.max(height) as f32).round() as usize).clamp(min_length, max_length);

    if pattern == 0 {
        let (sn, cs) = sort_angle.sin_cos();
        let normal_min = (-sn).min(0.0) * width.saturating_sub(1) as f32
            + cs.min(0.0) * height.saturating_sub(1) as f32;
        let normal_max = (-sn).max(0.0) * width.saturating_sub(1) as f32
            + cs.max(0.0) * height.saturating_sub(1) as f32;
        let line_count = ((normal_max - normal_min).ceil() as usize + 2).max(1);
        let mut lines: Vec<Vec<(f32, usize)>> = (0..line_count).map(|_| Vec::new()).collect();
        for y in 0..height {
            for x in 0..width {
                let normal = -(x as f32) * sn + y as f32 * cs;
                let line = ((normal - normal_min).round() as usize).min(line_count - 1);
                let along = x as f32 * cs + y as f32 * sn;
                lines[line].push((along, y * width + x));
            }
        }
        for line in &mut lines {
            line.sort_by(|a,b| a.0.total_cmp(&b.0));
            let path: Vec<usize> = line.iter().map(|entry| entry.1).collect();
            sort_pixel_path(&path, &source, &mut sorted, threshold, min_length, chunk_limit, sort_channel, reverse);
        }
    } else if pattern == 1 {
        let ray_count = ((max_radius * 2.0).ceil() as usize).clamp(64, 2048);
        let span = radial_degrees / 360.0;
        for ray in 0..ray_count {
            let u = ray as f32 / ray_count as f32;
            if u > span { continue; }
            let angle = radial_start + u * std::f32::consts::TAU;
            let (sn, cs) = angle.sin_cos();
            let edge_x = if cs > 1e-6 { (width as f32 - 1.0 - center.0) / cs } else if cs < -1e-6 { -center.0 / cs } else { f32::INFINITY };
            let edge_y = if sn > 1e-6 { (height as f32 - 1.0 - center.1) / sn } else if sn < -1e-6 { -center.1 / sn } else { f32::INFINITY };
            let edge = edge_x.min(edge_y).max(0.0);
            let variation = (u * 97.31).sin() * vary_radius * max_radius * 0.25;
            let start_radius = (inner_radius * max_radius + variation).clamp(0.0, edge);
            let mut path = Vec::new();
            let mut distance = start_radius;
            while distance <= edge {
                let x = center.0 + cs * distance;
                let y = center.1 + sn * distance;
                let ix = x.round().clamp(0.0, width.saturating_sub(1) as f32) as usize;
                let iy = y.round().clamp(0.0, height.saturating_sub(1) as f32) as usize;
                path.push(iy * width + ix);
                distance += 1.0;
            }
            sort_pixel_path(&path, &source, &mut sorted, threshold, min_length, chunk_limit, sort_channel, reverse);
        }
    } else {
        let start_radius = inner_radius * max_radius;
        let mut radius = start_radius.max(1.0);
        while radius <= max_radius {
            let sample_count = (std::f32::consts::TAU * radius).ceil().clamp(16.0, 16384.0) as usize;
            let span = circular_degrees / 360.0;
            let phase = (radius * 12.9898).sin() * vary_start * 0.25;
            let mut path = Vec::new();
            for i in 0..sample_count {
                let u = i as f32 / sample_count as f32;
                if u > span { continue; }
                let angle = circular_start + phase + u * std::f32::consts::TAU;
                let x = circle_center.0 + angle.cos() * radius;
                let y = circle_center.1 + angle.sin() * radius;
                if x >= 0.0 && x < width as f32 && y >= 0.0 && y < height as f32 {
                    let ix = x.round().clamp(0.0, width.saturating_sub(1) as f32) as usize;
                    let iy = y.round().clamp(0.0, height.saturating_sub(1) as f32) as usize;
                    path.push(iy * width + ix);
                }
            }
            sort_pixel_path(&path, &source, &mut sorted, threshold, min_length, chunk_limit, sort_channel, reverse);
            radius += 1.0;
        }
    }

    for i in 0..pixels.len() {
        for channel in 0..4 {
            pixels[i][channel] = source[i][channel] * (1.0 - mix) + sorted[i][channel] * mix;
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
        #[cfg(sapphire_glint)] { 30 }
        #[cfg(sapphire_rays)] { 31 }
        #[cfg(sapphire_halftone)] { 18 }
        #[cfg(sapphire_pixelsort)] { 20 }
    };
    if nparams < needed { return 1; }
    let values = unsafe { std::slice::from_raw_parts(params as *const f64, nparams as usize) };
    let frame = unsafe { std::slice::from_raw_parts_mut(pixels as *mut [f32; 4], count) };
    let w = width as usize;
    let h = height as usize;
    #[cfg(sapphire_glow)] { render_glow(frame, w, h, values, false, _scale) }
    #[cfg(sapphire_aura)] { render_glow(frame, w, h, values, true, _scale) }
    #[cfg(sapphire_lensflare)] { render_lensflare(frame, w, h, values, _scale) }
    #[cfg(sapphire_blur)] { render_blur(frame, w, h, values, _scale) }
    #[cfg(sapphire_distort)] { render_distort(frame, w, h, values) }
    #[cfg(sapphire_stylize)] { render_stylize(frame, values) }
    #[cfg(sapphire_motion)] { render_motion(frame, w, h, values) }
    #[cfg(sapphire_glint)] { render_glint(frame, w, h, values, _scale) }
    #[cfg(sapphire_rays)] { render_rays(frame, w, h, values, _scale) }
    #[cfg(sapphire_halftone)] { render_halftone(frame, w, h, values, _scale) }
    #[cfg(sapphire_pixelsort)] { render_pixelsort(frame, w, h, values) }
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
