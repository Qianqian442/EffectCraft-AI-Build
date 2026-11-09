#!/usr/bin/env python3
"""Add a draggable, horizontally scrollable curve-preset picker to the Android Timeline."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_CURVE_QUICK_ACCESS_V1"


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
    open: bool,
}

fn android_curve_segment_id() -> egui::Id {
    egui::Id::new("effectcraft-android-curve-segment")
}

/// Resolve the adjacent keyframe pair surrounding the current Timeline playhead
/// on the one selected property. The user only needs to position the playhead between keys.
fn android_playhead_curve_segment(app: &EffectcraftApp) -> Option<AndroidCurveSegment> {
    let mut selected = app.session.state.selected_props.iter();
    let (layer_id, prop_uid) = *selected.next()?;
    if selected.next().is_some() {
        return None;
    }
    let comp_id = app.session.active_comp_id()?;
    let comp = app.session.project.comp(comp_id)?;
    let layer = comp.layer(layer_id)?;
    let prop = layer.props.find(prop_uid)?;
    let playhead = app.session.time_of(comp_id);

    for pair in prop.keys.windows(2) {
        let first_comp = layer.comp_time(pair[0].time);
        let second_comp = layer.comp_time(pair[1].time);
        let lower = first_comp.min(second_comp);
        let upper = first_comp.max(second_comp);
        if playhead > lower && playhead < upper {
            return Some(AndroidCurveSegment {
                comp: comp_id.0,
                layer: layer_id.0,
                prop: prop_uid,
                first: pair[0].time.0,
                second: pair[1].time.0,
                open: true,
            });
        }
    }
    None
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
        let y = android_curve_sample(kind, x).clamp(0.0, 1.0);
        let current = pos2(plot.min.x + x * plot.width(), plot.max.y - y * plot.height());
        p.line_segment([previous, current], Stroke::new(2.2, color));
        previous = current;
    }
}

fn android_apply_curve(app: &mut EffectcraftApp, segment: AndroidCurveSegment, curve: &str) {
    let result = match curve {
        "loop_cycle" => app.session.execute("prop.setExpression", serde_json::json!({
            "comp": segment.comp,
            "layer": segment.layer,
            "prop": segment.prop,
            "expression": "loopOut(\\"cycle\\")",
            "enabled": true
        })),
        "loop_pingpong" => app.session.execute("prop.setExpression", serde_json::json!({
            "comp": segment.comp,
            "layer": segment.layer,
            "prop": segment.prop,
            "expression": "loopOut(\\"pingpong\\")",
            "enabled": true
        })),
        "loop_offset" => app.session.execute("prop.setExpression", serde_json::json!({
            "comp": segment.comp,
            "layer": segment.layer,
            "prop": segment.prop,
            "expression": "loopOut(\\"offset\\")",
            "enabled": true
        })),
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
    } else if curve.starts_with("loop_") {
        app.ui.status = match curve {
            "loop_cycle" => "已应用循环表达式：loopOut(cycle)".into(),
            "loop_pingpong" => "已应用往返循环表达式：loopOut(pingpong)".into(),
            "loop_offset" => "已应用偏移循环表达式：loopOut(offset)".into(),
            _ => String::new(),
        };
    }
}

/// Left-bottom shortcut and centered draggable curve picker.
fn android_curve_quick_access(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let ctx = ui.ctx().clone();
    let id = android_curve_segment_id();
    let mut state: Option<AndroidCurveSegment> = ctx.data(|data| data.get_temp(id));
    let button_rect = Rect::from_min_size(pos2(rect.min.x + 10.0, rect.max.y - 56.0), vec2(64.0, 24.0));
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
            app.ui.status = "请先选中一个属性，并把蓝色播放指针移到两个相邻关键帧之间，再点左下角“曲线”。".into();
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
                .resizable(false)
                .collapsible(false)
                .open(&mut open)
                .show(&ctx, |ui| {
                    ui.label(egui::RichText::new("选择当前属性的曲线；循环模式会在末尾关键帧之后继续重复").size(11.5).color(app.tokens.text_dim));
                    ui.add_space(5.0);
                    egui::ScrollArea::horizontal()
                        .id_salt("effectcraft-android-curve-presets")
                        .auto_shrink([false, false])
                        .scroll_bar_visibility(egui::scroll_area::ScrollBarVisibility::AlwaysVisible)
                        .show(ui, |ui| {
                            ui.horizontal(|ui| {
                                let presets: [(&str, &str, &str); 11] = [
                                    ("线性", "linear", "linear"),
                                    ("缓入", "ease_in", "ease_in"),
                                    ("缓出", "ease_out", "ease_out"),
                                    ("缓入缓出", "ease", "ease"),
                                    ("贝塞尔", "bezier", "bezier"),
                                    ("连续贝塞尔", "continuous", "continuous"),
                                    ("自动贝塞尔", "ease", "auto"),
                                    ("保持", "hold", "hold"),
                                    ("循环", "loop_cycle", "loop_cycle"),
                                    ("往返循环", "loop_pingpong", "loop_pingpong"),
                                    ("偏移循环", "loop_offset", "loop_offset"),
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
                android_apply_curve(app, current, curve);
                current.open = false;
            }
            if !open {
                current.open = false;
            }
        }
        ctx.data_mut(|data| data.insert_temp(id, current));
    }
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
