#!/usr/bin/env python3
"""Preserve unmapped After Effects plug-ins as editable, non-rendering project entries."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_AEP_UNPORTED_PLUGIN_PRESERVATION_V1"


EFFECTS_PATCH = r'''
// EFFECTCRAFT_ANDROID_AEP_UNPORTED_PLUGIN_PRESERVATION_V1
// The AEP parser knows the parameter records even when EffectCraft has no renderer for the
// original plug-in. Keep those controls and the entire effect chunk in an explicitly disabled
// placeholder; never substitute a similarly named built-in effect.
fn plugin_id_part(value: &str) -> String {
    let mut out = String::new();
    for c in value.chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_lowercase());
        } else if !out.ends_with('_') {
            out.push('_');
        }
    }
    let out = out.trim_matches('_').to_string();
    if out.is_empty() { "unknown".into() } else { out }
}

fn chunk_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len().saturating_mul(2));
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

fn write_original_chunk(chunk: &crate::Chunk<'_>, out: &mut Vec<u8>, depth: usize, limit: usize) -> bool {
    if depth > 64 || out.len() > limit {
        return false;
    }
    let start = out.len();
    out.extend_from_slice(&chunk.id);
    out.extend_from_slice(&[0; 4]);
    let body_start = out.len();
    match &chunk.body {
        crate::Body::Data(bytes) => out.extend_from_slice(bytes),
        crate::Body::OpaqueList { list_type, data } => {
            out.extend_from_slice(list_type);
            out.extend_from_slice(data);
        }
        crate::Body::Chunks(children) => {
            for child in children {
                if !write_original_chunk(child, out, depth + 1, limit) {
                    return false;
                }
            }
        }
        crate::Body::List { list_type, children } => {
            out.extend_from_slice(list_type);
            for child in children {
                if !write_original_chunk(child, out, depth + 1, limit) {
                    return false;
                }
            }
        }
    }
    let body_len = out.len().saturating_sub(body_start);
    let Ok(body_len_u32) = u32::try_from(body_len) else { return false };
    out[start + 4..start + 8].copy_from_slice(&body_len_u32.to_be_bytes());
    if body_len % 2 == 1 {
        out.push(chunk.pad.unwrap_or(0));
    }
    out.len() <= limit
}

fn append_plugin_node(root: &mut PropGroup, nested: &mut Vec<PropGroup>, node: Node) {
    if let Some(parent) = nested.last_mut() {
        parent.children.push(node);
    } else {
        root.children.push(node);
    }
}

fn close_plugin_group(root: &mut PropGroup, nested: &mut Vec<PropGroup>) {
    if let Some(group) = nested.pop() {
        append_plugin_node(root, nested, Node::Group(group));
    }
}

fn plugin_parameter_ui(param: &EffectParam<'_, '_>, width: f64, height: f64) -> Option<(Value, ParamUi, Option<Kind>)> {
    match param.kind {
        ParamKind::FloatSlider | ParamKind::FixedSlider | ParamKind::IntSlider => {
            let value = match param.value()? {
                ParamValue::Number(number) if number.is_finite() => Value::Scalar(number),
                _ => return None,
            };
            let ui = match (param.valid_min(), param.valid_max()) {
                (Some(min), Some(max)) if min.is_finite() && max.is_finite() && min < max => {
                    let (slider_min, slider_max) = param.slider_range().filter(|(a, b)| a.is_finite() && b.is_finite() && a < b).unwrap_or((min, max));
                    ParamUi::Slider {
                        min,
                        max,
                        slider_min: slider_min.clamp(min, max),
                        slider_max: slider_max.clamp(min, max),
                        decimals: 3,
                    }
                }
                _ => ParamUi::Number,
            };
            Some((value, ui, Some(Kind::EffectNumber(1.0))))
        }
        ParamKind::Angle => {
            let ParamValue::Number(number) = param.value()? else { return None };
            number.is_finite().then_some((Value::Scalar(number), ParamUi::Angle, Some(Kind::EffectNumber(1.0))))
        }
        ParamKind::Checkbox => {
            let ParamValue::Bool(value) = param.value()? else { return None };
            Some((Value::Bool(value), ParamUi::Checkbox, Some(Kind::EffectBool)))
        }
        ParamKind::Color => {
            let ParamValue::Argb([_alpha, red, green, blue]) = param.value()? else { return None };
            let value = Value::Color([red, green, blue, 1.0]);
            value.components().iter().all(|v| v.is_finite()).then_some((value, ParamUi::Color, Some(Kind::EffectColor)))
        }
        ParamKind::Point => {
            let ParamValue::Point([x, y]) = param.value()? else { return None };
            let value = Value::Vec2([x * width, y * height]);
            value.components().iter().all(|v| v.is_finite()).then_some((value, ParamUi::Point, Some(Kind::EffectPoint(width, height))))
        }
        ParamKind::Popup => {
            let ParamValue::Index(index) = param.value()? else { return None };
            let count = param.popup_item_count().map(usize::from).or_else(|| param.items.as_ref().map(Vec::len)).unwrap_or(0);
            if index == 0 || (count > 0 && index as usize > count) { return None; }
            let options = param.items.clone().unwrap_or_else(|| (1..=count.max(index as usize)).map(|n| format!("Item {n}")).collect());
            Some((Value::Enum(index - 1), ParamUi::Popup { options }, Some(Kind::EffectPopup(count.max(index as usize) as u32))))
        }
        _ => None,
    }
}

fn import_unmapped_plugin_effect(
    fx: &AepEffect<'_, '_>,
    defs: &EffectDefinitions<'_, '_>,
    cx: &LayerCtx<'_>,
    ids: &mut Ids<'_>,
    target: &mut PropGroup,
    refs: &mut Vec<PendingLayerRef>,
    col: &mut Collector,
) {
    let shown = fx.display_name().unwrap_or_else(|| fx.match_name().to_string());
    let mut group = ids.group(&format!("aep_plugin_{}", plugin_id_part(fx.match_name())), &shown);
    group.kind = effectcraft_project::GroupKind::Effect { effect: "aep.plugin.unported".into() };
    // This is a preservation record, not a working effect. It must not render a substitute.
    group.enabled = false;
    let width = f64::from(cx.size.0);
    let height = f64::from(cx.size.1);
    let mut nested: Vec<PropGroup> = Vec::new();
    let mut unhandled: Vec<String> = Vec::new();
    for param in defs.params(fx) {
        match param.kind {
            ParamKind::GroupStart => {
                nested.push(ids.group(&format!("aep_group_{}", param.index), &param.name));
                continue;
            }
            ParamKind::GroupEnd => {
                close_plugin_group(&mut group, &mut nested);
                continue;
            }
            ParamKind::Button | ParamKind::NoData => {
                // Their label/definition remains in the raw AEP chunk; there is no safe action
                // to execute until the original native plug-in is actually hosted.
                unhandled.push(format!("{}: button or no-data control '{}' is preserved but inactive", param.index, param.name));
                continue;
            }
            _ => {}
        }
        let safe = plugin_id_part(&param.match_name);
        let prop_id = format!("aep_param_{}_{}", param.index, safe);
        let label = if param.name.is_empty() { param.match_name.clone() } else { param.name.clone() };
        let mut property_value = None;
        let mut ui = ParamUi::Hidden;
        let mut key_kind: Option<Kind> = None;
        if param.kind == ParamKind::Layer {
            property_value = Some(Value::Layer(None));
            ui = ParamUi::Layer;
        } else if let Some((value, hint, kind)) = plugin_parameter_ui(&param, width, height) {
            property_value = Some(value);
            ui = hint;
            key_kind = kind;
        } else {
            unhandled.push(format!("{}: '{}' ({:?}) has no safe editable value decoder; original bytes are preserved", param.index, label, param.kind));
        }
        let value = property_value.unwrap_or_else(|| Value::Str(format!("Original AE parameter; type {:?}", param.kind)));
        let mut property = effectcraft_project::Property::new(ids.alloc(), &prop_id, &label, value).with_ui(ui.clone());
        property.static_only = matches!(param.kind, ParamKind::Button | ParamKind::NoData | ParamKind::GroupStart | ParamKind::GroupEnd | ParamKind::ArbitraryData | ParamKind::Path | ParamKind::Other(_));
        if matches!(param.kind, ParamKind::Checkbox | ParamKind::Popup | ParamKind::Layer) {
            property.hold_only = true;
        }
        if matches!(param.kind, ParamKind::Point) {
            property.spatial = true;
        }
        if param.kind == ParamKind::Layer {
            match param.layer_ref(cx.aep_id).unwrap_or(LayerRef::This) {
                LayerRef::Nothing => property.value = Value::Layer(None),
                LayerRef::This => property.value = Value::Layer(Some(cx.ec_id.0)),
                LayerRef::Layer(target_id) => {
                    property.value = Value::Layer(None);
                    refs.push(PendingLayerRef {
                        layer: cx.ec_id,
                        prop: property.uid,
                        target: target_id,
                        what: format!("{}: '{}' original plug-in parameter '{}'", cx.comp, cx.layer, label),
                    });
                }
            }
        }
        if let Some(stored) = param.stored() {
            if let Some(kind) = key_kind {
                if param.is_animated() {
                    import_keys(&stored, kind, cx.layer, &param.match_name, cx.tm, &mut property, col);
                    if property.keys.is_empty() {
                        unhandled.push(format!("{}: '{}' keyframes could not be decoded", param.index, label));
                    }
                }
            }
            if let Some(expression) = stored.expression() {
                if matches!(param.kind, ParamKind::Popup | ParamKind::Layer) {
                    unhandled.push(format!("{}: '{}' expression is preserved in the original chunk but not executable here", param.index, label));
                } else {
                    import_expression(&stored, &mut property, col);
                }
            }
        }
        append_plugin_node(&mut group, &mut nested, Node::Prop(property));
        if param.kind == ParamKind::Layer {
            // The original Layer Control's Source / Masks / Effects & Masks mode is retained
            // in the raw chunk. Until it is decoded it is safer to use the source-only default.
            let source_id = effectcraft_effects::layer_source_id(&prop_id);
            let mut source = effectcraft_project::Property::new(
                ids.alloc(), &source_id, &format!("{} Source", label), Value::Enum(0)
            ).with_ui(ParamUi::Hidden);
            source.hold_only = true;
            append_plugin_node(&mut group, &mut nested, Node::Prop(source));
        }
    }
    while !nested.is_empty() {
        close_plugin_group(&mut group, &mut nested);
    }

    // Store the entire original sspc chunk, including parameter definitions, defaults, keyed
    // values, UI metadata and opaque/arbitrary data. The compact chunk stream is hex encoded so
    // it can travel inside an EffectCraft project without a sidecar file.
    let mut raw = Vec::new();
    const RAW_LIMIT: usize = 16 * 1024 * 1024;
    let raw_saved = write_original_chunk(fx.chunk(), &mut raw, 0, RAW_LIMIT);
    if raw_saved {
        let raw_text = format!("AE-SSPC-CHUNK-HEX-V1:{}", chunk_hex(&raw));
        let mut original = effectcraft_project::Property::new(
            ids.alloc(), "raw_aep_effect_chunk", "Original AE Plug-in Data", Value::Str(raw_text)
        ).with_ui(ParamUi::Hidden);
        original.static_only = true;
        append_plugin_node(&mut group, &mut nested, Node::Prop(original));
    } else {
        col.lose(LossCategory::DamagedData, format!("{}: '{}' original plug-in data exceeded the 16 MiB preservation limit or could not be encoded", cx.comp, cx.layer));
    }
    let mut match_name = effectcraft_project::Property::new(
        ids.alloc(), "aep_plugin_match_name", "Original AE Match Name", Value::Str(fx.match_name().to_string())
    ).with_ui(ParamUi::Hidden);
    match_name.static_only = true;
    append_plugin_node(&mut group, &mut nested, Node::Prop(match_name));

    col.imported.effects = col.imported.effects.saturating_add(1);
    col.lose(
        LossCategory::Effects,
        format!("{}: '{}' original effect '{}' is preserved as an editable placeholder ({} recognised parameters, {} undecoded controls); its original plug-in code is not executed in this Android build",
            cx.comp, cx.layer, shown, defs.params(fx).iter().filter(|p| plugin_parameter_ui(p, width, height).is_some() || p.kind == ParamKind::Layer).count(), unhandled.len())
    );
    for detail in unhandled.into_iter().take(8) {
        col.lose(LossCategory::Effects, format!("{}: '{}' {detail}", cx.comp, cx.layer));
    }
    target.children.push(Node::Group(group));
}
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    effects_path = root / "crates/aep/src/import/effects.rs"
    source = effects_path.read_text(encoding="utf-8")
    if MARKER not in source:
        source = source.replace(
            "use effectcraft_project::{Node, ParamUi, PropGroup};",
            "use effectcraft_project::{Node, ParamUi, PropGroup};\nuse serde_json::json;",
            1,
        )
        anchor = "/// The match names of the effects the importer converts (the others are reported)."
        source = replace_once(source, anchor, EFFECTS_PATCH + "\n" + anchor, "generic AEP plug-in preservation helpers")
        old = '''        let Some(map) = EFFECTS.iter().find(|m| m.match_name == fx.match_name()) else {
            col.lose(LossCategory::Effects, format!("{}: '{}' has the effect '{shown}' ({})", cx.comp, cx.layer, fx.match_name()));
            continue;
        };'''
        new = '''        let Some(map) = EFFECTS.iter().find(|m| m.match_name == fx.match_name()) else {
            import_unmapped_plugin_effect(&fx, defs, cx, ids, target, refs, col);
            continue;
        };'''
        source = replace_once(source, old, new, "route unmapped original AE effects to parameter-preserving placeholders")
        effects_path.write_text(source, encoding="utf-8")

    panel_path = root / "crates/ui-egui/src/panels/effect_controls/panel.rs"
    panel = panel_path.read_text(encoding="utf-8")
    panel_marker = "EFFECTCRAFT_ANDROID_AEP_UNPORTED_PLUGIN_WARNING_V1"
    if panel_marker not in panel:
        old = '''        about_button(app, ui, &bp, &t, effect, g, r);
        let hresp = ui.interact('''
        new = '''        about_button(app, ui, &bp, &t, effect, g, r);
        // EFFECTCRAFT_ANDROID_AEP_UNPORTED_PLUGIN_WARNING_V1
        if effect == "aep.plugin.unported" {
            let warning = "已保留原版 AE 插件参数和原始数据；当前 Android 版本尚未运行该插件。";
            let wr = Rect::from_min_size(pos2(body.min.x + 12.0, y + 1.0), vec2((body.width() - 24.0).max(40.0), ROW));
            bp.text(wr.left_center(), Align2::LEFT_CENTER, warning, Tokens::ui(10.5), t.warning);
            app.auto.add(&format!("effectControls.effect.{}.nativePluginStatus", g.uid), wr, warning);
            y += ROW;
        }
        let hresp = ui.interact('''
        panel = replace_once(panel, old, new, "visible original AE plug-in placeholder status")
        panel_path.write_text(panel, encoding="utf-8")

    print("Unmapped AEP plug-ins now retain editable common controls and their complete original sspc chunk.")
    print("Original plug-in placeholders remain disabled and visibly report that native code is not executing.")


if __name__ == "__main__":
    main()
