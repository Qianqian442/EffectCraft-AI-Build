use aexlo::{Depth8, Host, Layer, ParamKind, ParamValue, PluginInstance, Time};
use image::{ColorType, ImageFormat};
use serde_json::{json, Value};
use std::error::Error;
use std::io::{self, BufRead, Write};
use std::path::Path;

type AnyError = Box<dyn Error + Send + Sync>;

fn parameter_value_json(value: &ParamValue) -> Value {
    match value {
        ParamValue::Float(v) => json!({"type":"float","value":v}),
        ParamValue::Fixed(v) => json!({"type":"fixed","value":v}),
        ParamValue::Slider(v) => json!({"type":"slider","value":v}),
        ParamValue::Checkbox(v) => json!({"type":"checkbox","value":v}),
        ParamValue::Popup(v) => json!({"type":"popup","value":v}),
        ParamValue::Angle(v) => json!({"type":"angle","value":v}),
        ParamValue::Point{x,y} => json!({"type":"point","x":x,"y":y}),
        ParamValue::Color{red,green,blue,alpha} => json!({"type":"color","red":red,"green":green,"blue":blue,"alpha":alpha}),
        ParamValue::Path(v) => json!({"type":"path","value":v}),
        ParamValue::Point3D{x,y,z} => json!({"type":"point3d","x":x,"y":y,"z":z}),
    }
}

fn parse_parameter_value(value: &Value) -> Result<ParamValue, AnyError> {
    let kind = value.get("type").and_then(Value::as_str).ok_or("parameter type is missing")?;
    let number = |key: &str| value.get(key).and_then(Value::as_f64).ok_or_else(|| format!("parameter field {key} must be a number").into());
    let integer = |key: &str| value.get(key).and_then(Value::as_i64).and_then(|v| i32::try_from(v).ok()).ok_or_else(|| format!("parameter field {key} must be a 32-bit integer").into());
    let channel = |key: &str| value.get(key).and_then(Value::as_u64).and_then(|v| u8::try_from(v).ok()).ok_or_else(|| format!("colour channel {key} must be 0..255").into());
    Ok(match kind {
        "float" => ParamValue::Float(number("value")?),
        "fixed" => ParamValue::Fixed(number("value")? as f32),
        "slider" => ParamValue::Slider(integer("value")?),
        "checkbox" => ParamValue::Checkbox(value.get("value").and_then(Value::as_bool).ok_or("checkbox value must be boolean")?),
        "popup" => ParamValue::Popup(integer("value")?),
        "angle" => ParamValue::Angle(number("value")? as f32),
        "point" => ParamValue::Point{x:number("x")? as f32,y:number("y")? as f32},
        "color" => ParamValue::Color{red:channel("red")?,green:channel("green")?,blue:channel("blue")?,alpha:channel("alpha")?},
        "path" => ParamValue::Path(value.get("value").and_then(Value::as_u64).and_then(|v| u32::try_from(v).ok()).ok_or("path value must be a u32")?),
        "point3d" => ParamValue::Point3D{x:number("x")?,y:number("y")?,z:number("z")?},
        _ => return Err(format!("unsupported parameter type: {kind}").into()),
    })
}

fn instance_info(instance: &PluginInstance, about: &str) -> Value {
    let params = (1..instance.param_count()).map(|index| {
        let kind = instance.param_kind(index).unwrap_or(ParamKind::Other(-1));
        let value = instance.get_param(index).as_ref().map(parameter_value_json).unwrap_or(Value::Null);
        let range = instance.param_slider_range(index).map(|(min,max)| json!({"min":min,"max":max}));
        let choices = instance.param_choices(index);
        json!({
            "index": index,
            "name": instance.param_name(index).unwrap_or_default(),
            "kind": format!("{kind:?}"),
            "value": value,
            "slider_range": range,
            "choices": choices,
            "hidden": instance.param_hidden(index),
            "disabled": instance.param_disabled(index),
            "custom_ui": instance.param_has_custom_ui(index)
        })
    }).collect::<Vec<_>>();
    json!({
        "ok": true,
        "about": about,
        "param_count": instance.param_count(),
        "parameters": params,
        "gpu_supported": instance.supports_gpu(),
        "custom_ui_supported": instance.has_custom_ui()
    })
}

fn render(instance: &mut PluginInstance, request: &Value) -> Result<Value, AnyError> {
    let input_path = request.get("input_png").and_then(Value::as_str).ok_or("input_png is required")?;
    let output_path = request.get("output_png").and_then(Value::as_str).ok_or("output_png is required")?;
    let frame = request.get("frame").and_then(Value::as_i64).and_then(|v| i32::try_from(v).ok()).unwrap_or(0);
    let fps = request.get("fps").and_then(Value::as_u64).and_then(|v| u32::try_from(v).ok()).filter(|v| *v>0).unwrap_or(30);

    if let Some(values) = request.get("params").and_then(Value::as_array) {
        for item in values {
            let index = item.get("index").and_then(Value::as_u64).and_then(|v| usize::try_from(v).ok()).ok_or("parameter index is missing")?;
            let raw = item.get("value").ok_or("parameter value is missing")?;
            instance.set_param(index, parse_parameter_value(raw)?)?;
            instance.user_changed_param(index)?;
        }
    }

    let image = image::open(input_path)?.to_rgba8();
    let (width, height) = image.dimensions();
    if width == 0 || height == 0 { return Err("input image has zero dimensions".into()); }
    instance.set_render_size(width, height);
    instance.set_input_layer(Layer::<Depth8>::from_rgba8(image.into_raw(), width, height)?);
    instance.set_time(Time::frame(frame, fps));
    instance.render_frame()?;

    let (out_width, out_height) = instance.output_size();
    let pixels_len = usize::try_from(out_width).ok()
        .and_then(|w| usize::try_from(out_height).ok().and_then(|h| w.checked_mul(h)))
        .and_then(|n| n.checked_mul(4))
        .ok_or("output pixel buffer size overflow")?;
    let mut pixels = vec![0u8; pixels_len];
    instance.write_output_rgba8(&mut pixels)?;
    let output = Path::new(output_path);
    if let Some(parent) = output.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    image::save_buffer_with_format(output, &pixels, out_width, out_height, ColorType::Rgba8, ImageFormat::Png)?;
    Ok(json!({"ok":true,"frame":frame,"fps":fps,"width":out_width,"height":out_height,"output_png":output_path}))
}

fn main() -> Result<(), AnyError> {
    // One worker process owns one plug-in instance. A plug-in fault therefore
    // terminates this worker, not the EffectCraft Android process.
    let plugin = std::env::args_os().nth(1).ok_or("usage: effectcraft-aex-host.exe <plugin.aex>")?;
    let host = Host::get();
    let mut instance = host.load(plugin)?;
    let about = instance.about()?;

    let stdout = io::stdout();
    let mut writer = io::BufWriter::new(stdout.lock());
    serde_json::to_writer(&mut writer, &instance_info(&instance, &about))?;
    writer.write_all(b"\n")?;
    writer.flush()?;

    for line in io::stdin().lock().lines() {
        let line = line?;
        if line.trim().is_empty() { continue; }
        let request: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(error) => {
                serde_json::to_writer(&mut writer, &json!({"ok":false,"error":format!("invalid JSON: {error}")}))?;
                writer.write_all(b"\n")?;
                writer.flush()?;
                continue;
            }
        };
        match request.get("cmd").and_then(Value::as_str).unwrap_or_default() {
            "render" => match render(&mut instance, &request) {
                Ok(response) => serde_json::to_writer(&mut writer, &response)?,
                Err(error) => serde_json::to_writer(&mut writer, &json!({"ok":false,"error":error.to_string()}))?,
            },
            "info" => serde_json::to_writer(&mut writer, &instance_info(&instance, &about))?,
            "quit" => break,
            _ => serde_json::to_writer(&mut writer, &json!({"ok":false,"error":"unknown command"}))?,
        }
        writer.write_all(b"\n")?;
        writer.flush()?;
    }
    Ok(())
}
