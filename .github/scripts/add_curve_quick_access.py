#!/usr/bin/env python3
"""Add a draggable, horizontally scrollable curve-preset picker to the Android Timeline."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_CURVE_QUICK_ACCESS_V2"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)



def patch_engine(root: Path) -> None:
    path = root / "crates/engine/src/cmd/anim.rs"
    source = path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_SEGMENT_CURVE_COMMAND_V1" in source:
        return

    source = replace_once(
        source,
        "use super::{CommandSpec, bad, comp_id, f_p, has_comp, has_keys, layers_p, merge_p, str_p, time_p};",
        "use super::{CommandSpec, bad, comp_id, f_p, has_comp, has_keys, layer_mut, layers_p, merge_p, str_p, time_p};",
        "Segment curve command imports",
    )
    anchor = "pub fn specs() -> Vec<CommandSpec> {"
    code = r'''
// EFFECTCRAFT_ANDROID_SEGMENT_CURVE_COMMAND_V1
/// Apply a curve preset to exactly one adjacent pair of keyframes on one property.
fn set_segment_curve(s: &mut Session, p: &Value) -> Result<Value> {
    const C: &str = "keys.setSegmentCurve";
    let cid = comp_id(s, p)?;
    let lid = LayerId(p.get("layer").and_then(Value::as_u64).ok_or_else(|| bad(C, "missing layer"))?);
    let uid = p.get("prop").and_then(Value::as_u64).ok_or_else(|| bad(C, "missing prop"))?;
    let first = Tick::from_seconds_f64(f_p(p, "first").ok_or_else(|| bad(C, "missing first key time"))?);
    let second = Tick::from_seconds_f64(f_p(p, "second").ok_or_else(|| bad(C, "missing second key time"))?);
    let curve = str_p(p, "curve").ok_or_else(|| bad(C, "missing curve"))?;

    s.edit("Set Keyframe Segment Curve", merge_p(p), |proj, st| {
        let layer = layer_mut(proj, cid, lid)?;
        if layer.switches.locked {
            return Err(bad(C, "the layer is locked"));
        }
        let prop = layer.props.find_mut(uid).ok_or_else(|| bad(C, "no animated property"))?;
        let i = prop.keys.iter().position(|key| key.time == first).ok_or_else(|| bad(C, "first keyframe no longer exists"))?;
        let j = prop.keys.iter().position(|key| key.time == second).ok_or_else(|| bad(C, "second keyframe no longer exists"))?;
        if j != i + 1 {
            return Err(bad(C, "the selected keyframes are no longer adjacent"));
        }
        let (before, after) = prop.keys.split_at_mut(j);
        let a = &mut before[i];
        let b = &mut after[0];
        match curve {
            "linear" => {
                a.out_interp = Interp::Linear;
                b.in_interp = Interp::Linear;
                a.auto_bezier = false;
                b.auto_bezier = false;
                a.continuous = false;
                b.continuous = false;
            }
            "bezier" | "ease" => {
                a.continuous = false;
                b.continuous = false;
                effectcraft_keyframe::easy_ease(a, false, true);
                effectcraft_keyframe::easy_ease(b, true, false);
            }
            "ease_in" => {
                a.out_interp = Interp::Bezier;
                a.out_ease = vec![Ease::EASY; a.value.dims().max(1)];
                a.auto_bezier = false;
                b.in_interp = Interp::Linear;
                b.auto_bezier = false;
            }
            "ease_out" => {
                a.out_interp = Interp::Linear;
                a.auto_bezier = false;
                b.in_interp = Interp::Bezier;
                b.in_ease = vec![Ease::EASY; b.value.dims().max(1)];
                b.auto_bezier = false;
            }
            "continuous" => {
                effectcraft_keyframe::easy_ease(a, false, true);
                effectcraft_keyframe::easy_ease(b, true, false);
                a.continuous = true;
                b.continuous = true;
                a.auto_bezier = false;
                b.auto_bezier = false;
            }
            "auto" => {
                a.out_interp = Interp::Bezier;
                b.in_interp = Interp::Bezier;
                a.auto_bezier = true;
                b.auto_bezier = true;
                a.continuous = false;
                b.continuous = false;
            }
            "hold" => {
                a.out_interp = Interp::Hold;
                b.in_interp = Interp::Hold;
                a.auto_bezier = false;
                b.auto_bezier = false;
            }
            _ => return Err(bad(C, format!("unknown curve preset: {curve}"))),
        }
        st.selected_keys = vec![
            KeyRef { layer: lid, prop: uid, time: first },
            KeyRef { layer: lid, prop: uid, time: second },
        ];
        Ok(json!({"layer": lid.0, "prop": uid, "first": first.seconds(), "second": second.seconds(), "curve": curve}))
    })
}

'''
    source = replace_once(source, anchor, code + anchor, "Segment curve command")
    spec_anchor = '        cmd!("keys.nudge", "Nudge Keyframes", [], None, "{frames, merge?}", has_keys, nudge),'
    source = replace_once(
        source,
        spec_anchor,
        '        cmd!("keys.setSegmentCurve", "Set Keyframe Segment Curve", [], None, "{layer, prop, first, second, curve}", has_comp, set_segment_curve),\n' + spec_anchor,
        "Segment curve command registration",
    )
    path.write_text(source, encoding="utf-8")


def patch_timeline(root: Path) -> None:
    patch_engine(root)
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    type_and_helpers = r'''
// EFFECTCRAFT_ANDROID_CURVE_QUICK_ACCESS_V1
/// The exact two-key segment selected for the floating curve preset picker.
#[derive(Clone, Copy)]
struct AndroidCurveSegment {
    comp: u64,
    layer: u64,
    prop: u64,
    first: i64,
    second: i64,
    first_index: usize,
    second_index: usize,
    numeric: bool,
    open: bool,
}

fn android_curve_segment_id() -> egui::Id {
    egui::Id::new("effectcraft-android-curve-segment")
}

/// Resolve the adjacent keyframe pair surrounding the current Timeline playhead
/// on the one selected property. The user only needs to position the playhead between keys.
// EFFECTCRAFT_ANDROID_CURVE_PLAYHEAD_RESOLVE_V2
fn android_collect_curve_property(
    prop: &Property,
    layer: &Layer,
    comp: u64,
    playhead: Tick,
    out: &mut Vec<AndroidCurveSegment>,
) {
    for (pair_index, pair) in prop.keys.windows(2).enumerate() {
        let first_comp = layer.comp_time(pair[0].time);
        let second_comp = layer.comp_time(pair[1].time);
        if playhead > first_comp.min(second_comp) && playhead < first_comp.max(second_comp) {
            out.push(AndroidCurveSegment {
                comp,
                layer: layer.id.0,
                prop: prop.uid,
                first: pair[0].time.0,
                second: pair[1].time.0,
                first_index: pair_index + 1,
                second_index: pair_index + 2,
                numeric: !prop.value.components().is_empty(),
                open: true,
            });
        }
    }
}

/// Walk all nested property groups when the user selected a layer but not a property row.
fn android_collect_curve_segments(
    group: &PropGroup,
    layer: &Layer,
    comp: u64,
    playhead: Tick,
    out: &mut Vec<AndroidCurveSegment>,
) {
    for node in &group.children {
        match node {
            Node::Prop(prop) => android_collect_curve_property(prop, layer, comp, playhead, out),
            Node::Group(child) => android_collect_curve_segments(child, layer, comp, playhead, out),
        }
    }
}

/// The playhead alone can resolve the curve when one adjacent keyframe segment is unique.
/// A selected property is preferred; otherwise one selected layer and one matching segment suffice.
fn android_playhead_curve_segment(app: &EffectcraftApp) -> Option<AndroidCurveSegment> {
    let comp_id = app.session.active_comp_id()?;
    let comp = app.session.project.comp(comp_id)?;
    let playhead = app.session.time_of(comp_id);

    let mut layer_ids: Vec<LayerId> = app.session.state.selected_layers.iter().copied().collect();
    for (layer_id, _) in &app.session.state.selected_props {
        if !layer_ids.contains(layer_id) {
            layer_ids.push(*layer_id);
        }
    }
    if layer_ids.is_empty() {
        if let [item] = app.session.state.project_selection.as_slice() {
            for layer in &comp.layers {
                if layer.source.item() == Some(*item) && !layer_ids.contains(&layer.id) {
                    layer_ids.push(layer.id);
                }
            }
        }
    }
    if layer_ids.is_empty() {
        return None;
    }

    let mut selected_segments = Vec::new();
    for (layer_id, prop_uid) in &app.session.state.selected_props {
        let Some(layer) = comp.layer(*layer_id) else { continue };
        let Some(prop) = layer.props.find(*prop_uid) else { continue };
        android_collect_curve_property(prop, layer, comp_id.0, playhead, &mut selected_segments);
    }
    if selected_segments.len() == 1 {
        return selected_segments.pop();
    }
    if selected_segments.len() > 1 {
        return None;
    }

    let mut candidates = Vec::new();
    for layer_id in layer_ids {
        let Some(layer) = comp.layer(layer_id) else { continue };
        android_collect_curve_segments(&layer.props, layer, comp_id.0, playhead, &mut candidates);
    }
    if candidates.len() == 1 { candidates.pop() } else { None }
}

fn android_curve_sample(kind: &str, x: f32) -> f32 {
    match kind {
        "hold" => if x >= 0.96 { 1.0 } else { 0.0 },
        "ease_in" => x * x * x,
        "ease_out" => 1.0 - (1.0 - x).powi(3),
        "ease" => x * x * (3.0 - 2.0 * x),
        "continuous" => x * x * (3.0 - 2.0 * x),
        "bezier" => x * x,
        "loop_cycle" => (x * 3.0).fract(),
        "loop_pingpong" => {
            let phase = (x * 3.0) % 2.0;
            if phase <= 1.0 { phase } else { 2.0 - phase }
        }
        // Offset looping continues the same motion while carrying each cycle's value offset.
        "loop_offset" => x,
        // AM-style Bounce easing: several progressively smaller rebounds before settling.
        "bounce" => {
            let n = 7.5625;
            let d = 2.75;
            if x < 1.0 / d {
                n * x * x
            } else if x < 2.0 / d {
                let t = x - 1.5 / d;
                n * t * t + 0.75
            } else if x < 2.5 / d {
                let t = x - 2.25 / d;
                n * t * t + 0.9375
            } else {
                let t = x - 2.625 / d;
                n * t * t + 0.984375
            }
        }
        _ => x,
    }
}

fn android_curve_preview(ui: &mut egui::Ui, rect: Rect, kind: &str, color: Color32) {
    let plot = Rect::from_min_max(pos2(rect.min.x + 10.0, rect.min.y + 8.0), pos2(rect.max.x - 10.0, rect.max.y - 30.0));
    let p = ui.painter();
    p.line_segment([plot.left_bottom(), plot.right_bottom()], Stroke::new(1.0, Color32::from_gray(105)));
    p.line_segment([plot.left_bottom(), plot.left_top()], Stroke::new(1.0, Color32::from_gray(105)));
    p.line_segment([plot.left_bottom(), plot.right_top()], Stroke::new(1.0, Color32::from_gray(65)));
    let mut previous = plot.left_bottom();
    for i in 1..=24 {
        let x = i as f32 / 24.0;
        let sample = android_curve_sample(kind, x);
        let y = sample.clamp(0.0, 1.0);
        let current = pos2(plot.min.x + x * plot.width(), plot.max.y - y * plot.height());
        p.line_segment([previous, current], Stroke::new(2.2, color));
        previous = current;
    }
}

fn android_apply_curve(app: &mut EffectcraftApp, segment: AndroidCurveSegment, curve: &str) {
    let result = match curve {
        "loop_cycle" | "loop_pingpong" | "loop_offset" => {
            // Keep the cycle expression tied to editable Bezier handles on the selected segment.
            // The native Graph Editor evaluates the expression curve and edits these source handles.
            let bezier = app.session.execute("keys.setSegmentCurve", serde_json::json!({
                "comp": segment.comp,
                "layer": segment.layer,
                "prop": segment.prop,
                "first": Tick(segment.first).seconds(),
                "second": Tick(segment.second).seconds(),
                "curve": "bezier"
            }));
            match bezier {
                Err(error) => Err(error),
                Ok(_) => {
                    let expression = match curve {
                        "loop_cycle" => "loopOut("cycle")",
                        "loop_pingpong" => "loopOut("pingpong")",
                        "loop_offset" => "loopOut("offset")",
                        _ => unreachable!(),
                    };
                    app.session.execute("prop.setExpression", serde_json::json!({
                        "comp": segment.comp,
                        "layer": segment.layer,
                        "prop": segment.prop,
                        "expression": expression,
                        "enabled": true
                    }))
                }
            }
        }
        "bounce" => {
            if !segment.numeric {
                app.ui.status = "弹跳曲线仅适用于数值、位置、缩放等数值属性".into();
                return;
            }
            let expression = format!(
                "var a = key({}); var b = key({}); var u = (time-a.time)/(b.time-a.time); var r = value; if (time >= a.time && time <= b.time) {{ var t = clamp(u,0,1); var n = 7.5625; var d = 2.75; var p; if (t < 1/d) p = n*t*t; else if (t < 2/d) {{ t -= 1.5/d; p = n*t*t + 0.75; }} else if (t < 2.5/d) {{ t -= 2.25/d; p = n*t*t + 0.9375; }} else {{ t -= 2.625/d; p = n*t*t + 0.984375; }} r = a.value + (b.value-a.value)*p; }} r;",
                segment.first_index,
                segment.second_index
            );
            app.session.execute("prop.setExpression", serde_json::json!({
                "comp": segment.comp,
                "layer": segment.layer,
                "prop": segment.prop,
                "expression": expression,
                "enabled": true
            }))
        }
        _ => app.session.execute("keys.setSegmentCurve", serde_json::json!({
            "comp": segment.comp,
            "layer": segment.layer,
            "prop": segment.prop,
            "first": Tick(segment.first).seconds(),
            "second": Tick(segment.second).seconds(),
            "curve": curve
        })),
    };
    if let Err(error) = result {
        app.ui.status = error.to_string();
    } else if curve == "bounce" {
        app.ui.status = "已应用 AM 风格弹跳周期：多次回弹并逐渐收敛到终点".into();
    } else if curve.starts_with("loop_") {
        // Open the native, editable Value Graph after applying the cycle expression.
        // The selected segment's Bezier handles remain the source curve repeated by loopOut.
        app.ui.timeline.graph_mode = "value".into();
        app.ui.timeline.graph_show_selected = true;
        app.ui.timeline.graph_editor = true;
        app.ui.status = match curve {
            "loop_cycle" => "已打开周期运动曲线编辑器：拖动黄色贝塞尔手柄即可调整循环曲线".into(),
            "loop_pingpong" => "已打开往返周期曲线编辑器：拖动黄色贝塞尔手柄即可调整曲线".into(),
            "loop_offset" => "已打开偏移周期曲线编辑器：拖动黄色贝塞尔手柄即可调整曲线".into(),
            _ => String::new(),
        };
    }
}

// EFFECTCRAFT_ANDROID_PERIODIC_CURVE_EDITOR_V1
#[derive(Clone, Copy)]
struct AndroidCycleParams {
    cycles: f32,
    amplitude: f32,
    phase: f32,
}
impl Default for AndroidCycleParams {
    fn default() -> Self {
        Self { cycles: 3.0, amplitude: 0.55, phase: 0.0 }
    }
}
#[derive(Clone, Copy)]
struct AndroidCycleEditor {
    segment: AndroidCurveSegment,
    kind: u8,
    params: AndroidCycleParams,
    open: bool,
}
fn android_cycle_editor_id() -> egui::Id {
    egui::Id::new("effectcraft-android-periodic-curve-editor")
}
fn android_cycle_params_id(segment: AndroidCurveSegment) -> egui::Id {
    egui::Id::new(("effectcraft-android-periodic-curve-params", segment.layer, segment.prop, segment.first, segment.second))
}
fn android_cycle_wave(kind: u8, x: f32, params: AndroidCycleParams) -> f32 {
    let phase = x * params.cycles + params.phase / std::f32::consts::TAU;
    match kind {
        1 => {
            let q = phase.rem_euclid(1.0);
            1.0 - 4.0 * (q - 0.5).abs()
        }
        2 => 2.0 * phase.rem_euclid(1.0) - 1.0,
        3 => 2.0 * (std::f32::consts::PI * phase).sin().abs() - 1.0,
        _ => (std::f32::consts::TAU * phase).sin(),
    }
}
fn android_periodic_expression(segment: AndroidCurveSegment, editor: AndroidCycleEditor) -> String {
    let cycles = editor.params.cycles.clamp(1.0, 12.0);
    let amplitude = editor.params.amplitude.clamp(0.0, 1.5);
    let phase = editor.params.phase;
    let wave = match editor.kind {
        1 => format!("var q = (u*{cycles:.4} + {phase:.5}/(2*Math.PI)) % 1; var wave = 1 - 4*Math.abs(q-0.5);"),
        2 => format!("var wave = 2*((u*{cycles:.4} + {phase:.5}/(2*Math.PI)) % 1)-1;"),
        3 => format!("var wave = 2*Math.abs(Math.sin(Math.PI*(u*{cycles:.4} + {phase:.5}/(2*Math.PI))))-1;"),
        _ => format!("var wave = Math.sin(2*Math.PI*{cycles:.4}*u + {phase:.5});"),
    };
    format!(
        "var a = key({}); var b = key({}); var r = value; if (time >= a.time && time <= b.time) {{ var u = clamp((time-a.time)/(b.time-a.time),0,1); var envelope = Math.sin(Math.PI*u); {} r = a.value + (b.value-a.value)*u + (b.value-a.value)*{amplitude:.5}*wave*envelope; }} r;",
        segment.first_index, segment.second_index, wave
    )
}

/// AM-style editor: drag yellow handles or use the controls to adjust the periodic curve.
fn android_periodic_curve_editor(app: &mut EffectcraftApp, ctx: &egui::Context) {
    let id = android_cycle_editor_id();
    let Some(mut editor) = ctx.data(|data| data.get_temp::<AndroidCycleEditor>(id)) else { return; };
    if !editor.open { return; }
    let mut open = true;
    let mut apply = false;
    egui::Window::new("周期曲线编辑器")
        .id(id.with("window"))
        .default_pos(ctx.content_rect().center() - vec2(170.0, 165.0))
        .default_size(vec2(ctx.content_rect().width().min(350.0).max(260.0), 330.0))
        .min_size(vec2(250.0, 290.0))
        .max_size(ctx.content_rect().size())
        .constrain_to(ctx.content_rect())
        .movable(true)
        .resizable(false)
        .collapsible(false)
        .open(&mut open)
        .show(ctx, |ui| {
            let mode_name = match editor.kind {
                1 => "往返周期",
                2 => "偏移周期",
                3 => "弹跳周期",
                _ => "周期运动",
            };
            ui.label(format!("{mode_name} · 拖动黄色控制点调整曲线"));
            ui.add_space(4.0);

            let graph_width = ui.available_width().max(220.0);
            let (graph, _) = ui.allocate_exact_size(vec2(graph_width, 126.0), Sense::hover());
            let plot = graph.shrink2(vec2(14.0, 9.0));
            let painter = ui.painter();
            painter.rect_filled(graph, 5.0, Color32::from_rgb(31, 37, 65));
            for i in 0..=4 {
                let x = plot.left() + plot.width() * i as f32 / 4.0;
                let y = plot.top() + plot.height() * i as f32 / 4.0;
                painter.line_segment([pos2(x, plot.top()), pos2(x, plot.bottom())], Stroke::new(0.6, Color32::from_gray(72)));
                painter.line_segment([pos2(plot.left(), y), pos2(plot.right(), y)], Stroke::new(0.6, Color32::from_gray(72)));
            }
            painter.line_segment([plot.left_bottom(), plot.right_bottom()], Stroke::new(1.0, Color32::from_gray(150)));
            painter.line_segment([plot.left_center(), plot.right_center()], Stroke::new(0.8, Color32::from_gray(100)));

            let mut previous = plot.left_center();
            for i in 1..=128 {
                let x = i as f32 / 128.0;
                let envelope = (std::f32::consts::PI * x).sin();
                let y = 0.5 - android_cycle_wave(editor.kind, x, editor.params) * editor.params.amplitude * 0.43 * envelope;
                let point = pos2(plot.left() + x * plot.width(), plot.bottom() - y.clamp(0.0, 1.0) * plot.height());
                painter.line_segment([previous, point], Stroke::new(2.5, Color32::from_rgb(245, 139, 176)));
                previous = point;
            }

            let cycle_x = plot.left() + ((editor.params.cycles - 1.0) / 11.0).clamp(0.0, 1.0) * plot.width();
            let cycle_handle = pos2(cycle_x, plot.bottom() - 3.0);
            painter.circle_filled(cycle_handle, 7.0, Color32::from_rgb(255, 218, 74));
            let cycle_response = ui.interact(Rect::from_center_size(cycle_handle, vec2(24.0, 24.0)), id.with("cycle-handle"), Sense::drag());
            if cycle_response.dragged() {
                if let Some(pointer) = cycle_response.interact_pointer_pos() {
                    editor.params.cycles = (1.0 + 11.0 * ((pointer.x - plot.left()) / plot.width()).clamp(0.0, 1.0)).round();
                }
            }

            let amp_x = plot.left() + plot.width() * 0.22;
            let amp_y = plot.center().y - editor.params.amplitude.clamp(0.0, 1.5) * plot.height() * 0.27;
            let amp_handle = pos2(amp_x, amp_y);
            painter.line_segment([pos2(amp_x, plot.center().y), amp_handle], Stroke::new(1.5, Color32::from_rgb(255, 218, 74)));
            painter.circle_filled(amp_handle, 7.0, Color32::from_rgb(255, 218, 74));
            let amp_response = ui.interact(Rect::from_center_size(amp_handle, vec2(24.0, 24.0)), id.with("amplitude-handle"), Sense::drag());
            if amp_response.dragged() {
                if let Some(pointer) = amp_response.interact_pointer_pos() {
                    editor.params.amplitude = ((plot.center().y - pointer.y) / (plot.height() * 0.27)).clamp(0.0, 1.5);
                }
            }

            ui.label("下方黄色点：左右调整周期数；左侧黄色点：上下调整振幅");
            ui.add(egui::Slider::new(&mut editor.params.cycles, 1.0..=12.0).step_by(1.0).text("周期数"));
            ui.add(egui::Slider::new(&mut editor.params.amplitude, 0.0..=1.5).text("振幅"));
            ui.add(egui::Slider::new(&mut editor.params.phase, 0.0..=std::f32::consts::TAU).text("相位"));
            ui.horizontal(|ui| {
                if ui.button("应用曲线").clicked() { apply = true; }
                if ui.button("取消").clicked() { open = false; }
            });
        });

    if apply {
        let expression = android_periodic_expression(editor.segment, editor);
        match app.session.execute("prop.setExpression", serde_json::json!({
            "comp": editor.segment.comp,
            "layer": editor.segment.layer,
            "prop": editor.segment.prop,
            "expression": expression,
            "enabled": true
        })) {
            Ok(_) => {
                ctx.data_mut(|data| data.insert_temp(android_cycle_params_id(editor.segment), editor.params));
                app.ui.status = "周期曲线已应用；重新打开曲线编辑器可继续调整周期数、振幅和相位。".into();
                editor.open = false;
            }
            Err(error) => app.ui.status = error.to_string(),
        }
    }
    if !open { editor.open = false; }
    ctx.data_mut(|data| data.insert_temp(id, editor));
}

/// Left-bottom shortcut and centered draggable curve picker.
fn android_curve_quick_access(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let ctx = ui.ctx().clone();
    let id = android_curve_segment_id();
    let mut state: Option<AndroidCurveSegment> = ctx.data(|data| data.get_temp(id));
    // Keep the Curve shortcut separate from the global bottom-left Import Media button.
    // On normal-width timelines it sits beside Import Media; on narrow screens it moves
    // to a second row above it. The keyframe button remains in its own footer slot.
    let (curve_x, curve_y) = if rect.width() >= 240.0 {
        (rect.min.x + 160.0, rect.max.y - 56.0)
    } else {
        (rect.min.x + 10.0, rect.max.y - 88.0)
    };
    let button_rect = Rect::from_min_size(pos2(curve_x, curve_y), vec2(64.0, 24.0));
    let button = ui.interact(button_rect, egui::Id::new("effectcraft-curve-quick-button"), Sense::click());
    let p = ui.painter();
    p.rect_filled(button_rect, 5.0, if button.hovered() { app.tokens.accent.gamma_multiply(0.25) } else { app.tokens.panel_bg });
    p.rect_stroke(button_rect, 5.0, Stroke::new(1.0, app.tokens.separator), StrokeKind::Inside);
    p.text(button_rect.center(), Align2::CENTER_CENTER, "曲线", Tokens::semibold(11.5), app.tokens.text);
    app.auto.add("timeline.curveQuickButton", button_rect, "Curve presets");
    if button.clicked() {
        if let Some(mut current) = android_playhead_curve_segment(app) {
            current.open = true;
            state = Some(current);
            ctx.data_mut(|data| data.insert_temp(id, current));
        } else {
            app.ui.status = "请先选中一个图层，并把蓝色播放指针移到两个相邻关键帧之间；若该时间段有多个属性，请先点选要调整的属性行。".into();
        }
    }

    if let Some(mut current) = state {
        if current.open {
            let mut open = true;
            let mut picked: Option<&'static str> = None;
            egui::Window::new("曲线选项")
                .id(egui::Id::new("effectcraft-android-curve-picker-window"))
                .default_pos(ctx.content_rect().center() - vec2(210.0, 88.0))
                .default_size(vec2(430.0, 174.0))
                .title_bar(true)
                .movable(true)
                .resizable(false)
                .collapsible(false)
                .open(&mut open)
                .show(&ctx, |ui| {
                    ui.label(egui::RichText::new("选择当前属性的曲线；弹跳会连续回弹并逐渐停稳，周期模式会重复运动").size(11.5).color(app.tokens.text_dim));
                    ui.add_space(5.0);
                    egui::ScrollArea::horizontal()
                        .id_salt("effectcraft-android-curve-presets")
                        .auto_shrink([false, false])
                        .scroll_bar_visibility(egui::scroll_area::ScrollBarVisibility::AlwaysVisible)
                        .show(ui, |ui| {
                            ui.horizontal(|ui| {
                                let presets: [(&str, &str, &str); 12] = [
                                    ("线性", "linear", "linear"),
                                    ("缓入", "ease_in", "ease_in"),
                                    ("缓出", "ease_out", "ease_out"),
                                    ("缓入缓出", "ease", "ease"),
                                    ("贝塞尔", "bezier", "bezier"),
                                    ("连续贝塞尔", "continuous", "continuous"),
                                    ("自动贝塞尔", "ease", "auto"),
                                    ("保持", "hold", "hold"),
                                    ("周期运动", "loop_cycle", "loop_cycle"),
                                    ("往返周期", "loop_pingpong", "loop_pingpong"),
                                    ("偏移周期", "loop_offset", "loop_offset"),
                                    ("弹跳周期", "bounce", "bounce"),
                                ];
                                for (label, preview, curve) in presets {
                                    let (card, response) = ui.allocate_exact_size(vec2(88.0, 94.0), Sense::click());
                                    ui.painter().rect_filled(card, 6.0, if response.hovered() { app.tokens.accent.gamma_multiply(0.22) } else { app.tokens.panel_bg });
                                    ui.painter().rect_stroke(card, 6.0, Stroke::new(1.0, if response.hovered() { app.tokens.accent } else { app.tokens.separator }), StrokeKind::Inside);
                                    android_curve_preview(ui, card, preview, app.tokens.accent);
                                    ui.painter().text(pos2(card.center().x, card.max.y - 13.0), Align2::CENTER_CENTER, label, Tokens::ui(10.5), app.tokens.text);
                                    if response.clicked() {
                                        picked = Some(curve);
                                    }
                                }
                            });
                        });
                });
            if let Some(curve) = picked {
                let cycle_kind = match curve {
                    "loop_pingpong" => Some(1),
                    "loop_offset" => Some(2),
                    "bounce" => Some(3),
                    "loop_cycle" => Some(0),
                    _ => None,
                };
                if let Some(kind) = cycle_kind {
                    if !current.numeric {
                        app.ui.status = "周期曲线仅支持数值、位置、缩放等数值属性".into();
                    } else {
                        let params_id = android_cycle_params_id(current);
                        let params = ctx.data(|data| data.get_temp::<AndroidCycleParams>(params_id))
                            .unwrap_or_default();
                        ctx.data_mut(|data| data.insert_temp(android_cycle_editor_id(), AndroidCycleEditor {
                            segment: current,
                            kind,
                            params,
                            open: true,
                        }));
                    }
                } else {
                    android_apply_curve(app, current, curve);
                }
                current.open = false;
            }
            if !open {
                current.open = false;
            }
        }
        ctx.data_mut(|data| data.insert_temp(id, current));
    }
    android_periodic_curve_editor(app, &ctx);
}
'''
    anchor = "const EXPR_MAX_LINES: usize = 100;\n"
    source = replace_once(source, anchor, anchor + type_and_helpers + "\n", "curve quick access helpers")

    prop_anchor = '''    prop_expression_hint(app, ui, g, rc, prop);
    if !g.graph_on {
        for k in &prop.keys {
'''
    prop_replacement = '''    prop_expression_hint(app, ui, g, rc, prop);
    if !g.graph_on {
        for k in &prop.keys {
'''
    source = replace_once(source, prop_anchor, prop_replacement, "curve segment hit targets")

    show_anchor = '''    footer_zoom(app, ui, g, footer);
    comp_markers_ui(app, ui, g);
    hand_tool_pan(app, ui, g);
    drop_targets(app, ui, g);
    let Rw { tl, ui_actions, .. } = rw;
'''
    show_replacement = '''    footer_zoom(app, ui, g, footer);
    comp_markers_ui(app, ui, g);
    hand_tool_pan(app, ui, g);
    drop_targets(app, ui, g);
    android_curve_quick_access(app, ui, rect);
    let Rw { tl, ui_actions, .. } = rw;
'''
    source = replace_once(source, show_anchor, show_replacement, "curve quick access UI insertion")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "vendor/effectcraft"))
    patch_timeline(root)


if __name__ == "__main__":
    main()
