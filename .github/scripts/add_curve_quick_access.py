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


def patch_timeline(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    type_and_helpers = r'''
// EFFECTCRAFT_ANDROID_CURVE_QUICK_ACCESS_V1
/// The exact two-key segment selected for the floating curve preset picker.
#[derive(Clone, Copy)]
struct AndroidCurveSegment {
    layer: u64,
    prop: u64,
    first: i64,
    second: i64,
    open: bool,
}

fn android_curve_segment_id() -> egui::Id {
    egui::Id::new("effectcraft-android-curve-segment")
}

/// Make the gap between adjacent keyframes clickable without covering either key's hit target.
fn android_curve_segment_hit(app: &mut EffectcraftApp, ui: &mut egui::Ui, g: &mut Rw, rc: &RowCtx<'_>, prop: &Property) {
    if g.graph_on || prop.keys.len() < 2 {
        return;
    }
    let uid = prop.uid;
    for pair in prop.keys.windows(2) {
        let (a, b) = (&pair[0], &pair[1]);
        let x0 = g.tl.tm.x(rc.layer.comp_time(a.time).seconds());
        let x1 = g.tl.tm.x(rc.layer.comp_time(b.time).seconds());
        let segment = Rect::from_min_max(pos2(x0 + 7.0, rc.cy - 7.0), pos2(x1 - 7.0, rc.cy + 7.0)).intersect(g.right_clip);
        if segment.width() < 5.0 || !segment.is_positive() {
            continue;
        }
        let response = ui.interact(
            segment,
            egui::Id::new(("effectcraft-curve-between-keys", rc.layer.id.0, uid, a.time.0, b.time.0)),
            Sense::click(),
        );
        if response.hovered() {
            ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
            ui.painter().line_segment(
                [pos2(x0 + 8.0, rc.cy), pos2(x1 - 8.0, rc.cy)],
                Stroke::new(2.0, app.tokens.accent.gamma_multiply(0.8)),
            );
        }
        app.auto.add(
            &format!("timeline.curveSegment.{}.{}.{}", rc.layer.id.0, uid, a.time.0),
            segment,
            "Open curve presets for the two keyframes",
        );
        if response.clicked() {
            ui.ctx().data_mut(|data| {
                data.insert_temp(android_curve_segment_id(), AndroidCurveSegment {
                    layer: rc.layer.id.0,
                    prop: uid,
                    first: a.time.0,
                    second: b.time.0,
                    open: true,
                });
            });
        }
    }
}

fn android_curve_sample(kind: &str, x: f32) -> f32 {
    match kind {
        "hold" => if x >= 0.96 { 1.0 } else { 0.0 },
        "ease_in" => x * x * x,
        "ease_out" => 1.0 - (1.0 - x).powi(3),
        "ease" => x * x * (3.0 - 2.0 * x),
        "continuous" => x * x * (3.0 - 2.0 * x),
        "bezier" => x * x,
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

fn android_apply_curve(
    app: &mut EffectcraftApp,
    ctx: &egui::Context,
    segment: AndroidCurveSegment,
    command: &str,
    params: serde_json::Value,
) {
    let Some(comp) = app.session.active_comp() else {
        app.ui.status = "请先打开一个合成".into();
        return;
    };
    let layer = LayerId(segment.layer);
    let valid = comp.layer(layer).and_then(|l| l.props.find(segment.prop)).is_some_and(|prop| {
        prop.keys.iter().any(|k| k.time.0 == segment.first)
            && prop.keys.iter().any(|k| k.time.0 == segment.second)
    });
    if !valid {
        app.ui.status = "这两个关键帧已发生变化，请重新选择区段".into();
        return;
    }
    app.session.state.selected_keys = vec![
        effectcraft_engine::KeyRef { layer, prop: segment.prop, time: Tick(segment.first) },
        effectcraft_engine::KeyRef { layer, prop: segment.prop, time: Tick(segment.second) },
    ];
    if let Err(error) = crate::menus::invoke(app, ctx, command, params) {
        app.ui.status = error;
    }
}

/// Left-bottom shortcut and centered draggable curve picker.
fn android_curve_quick_access(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let ctx = ui.ctx().clone();
    let id = android_curve_segment_id();
    let mut state: Option<AndroidCurveSegment> = ctx.data(|data| data.get_temp(id));
    let button_rect = Rect::from_min_size(pos2(rect.min.x + 10.0, rect.max.y - 32.0), vec2(64.0, 24.0));
    let button = ui.interact(button_rect, egui::Id::new("effectcraft-curve-quick-button"), Sense::click());
    let p = ui.painter();
    p.rect_filled(button_rect, 5.0, if button.hovered() { app.tokens.accent.gamma_multiply(0.25) } else { app.tokens.panel });
    p.rect_stroke(button_rect, 5.0, Stroke::new(1.0, app.tokens.separator), StrokeKind::Inside);
    p.text(button_rect.center(), Align2::CENTER_CENTER, "曲线", Tokens::semibold(11.5), app.tokens.text);
    app.auto.add("timeline.curveQuickButton", button_rect, "Curve presets");
    if button.clicked() {
        if let Some(mut current) = state {
            current.open = !current.open;
            state = Some(current);
        } else {
            app.ui.status = "请先点击时间轴上两个关键帧之间的区段".into();
        }
    }

    if let Some(mut current) = state {
        if current.open {
            let mut open = true;
            let mut picked: Option<(&'static str, serde_json::Value)> = None;
            egui::Window::new("曲线选项")
                .id(egui::Id::new("effectcraft-android-curve-picker-window"))
                .default_pos(ctx.screen_rect().center() - vec2(210.0, 88.0))
                .default_size(vec2(430.0, 174.0))
                .resizable(false)
                .collapsible(false)
                .open(&mut open)
                .show(&ctx, |ui| {
                    ui.label(egui::RichText::new("选择这两个关键帧之间的动画曲线").size(11.5).color(app.tokens.text_dim));
                    ui.add_space(5.0);
                    egui::ScrollArea::horizontal()
                        .id_salt("effectcraft-android-curve-presets")
                        .auto_shrink([false, false])
                        .scroll_bar_visibility(egui::scroll_area::ScrollBarVisibility::AlwaysVisible)
                        .show(ui, |ui| {
                            ui.horizontal(|ui| {
                                let presets: [(&str, &str, &str, serde_json::Value); 8] = [
                                    ("线性", "linear", "keys.interpolation", serde_json::json!({"interpolation": "linear"})),
                                    ("缓入", "ease_in", "keys.easyEaseIn", serde_json::json!({})),
                                    ("缓出", "ease_out", "keys.easyEaseOut", serde_json::json!({})),
                                    ("缓入缓出", "ease", "keys.easyEase", serde_json::json!({})),
                                    ("贝塞尔", "bezier", "keys.interpolation", serde_json::json!({"interpolation": "bezier"})),
                                    ("连续贝塞尔", "continuous", "keys.interpolation", serde_json::json!({"interpolation": "continuousBezier"})),
                                    ("自动贝塞尔", "ease", "keys.interpolation", serde_json::json!({"interpolation": "autoBezier"})),
                                    ("保持", "hold", "keys.interpolation", serde_json::json!({"interpolation": "hold"})),
                                ];
                                for (label, preview, command, params) in presets {
                                    let (card, response) = ui.allocate_exact_size(vec2(88.0, 94.0), Sense::click());
                                    ui.painter().rect_filled(card, 6.0, if response.hovered() { app.tokens.accent.gamma_multiply(0.22) } else { app.tokens.panel });
                                    ui.painter().rect_stroke(card, 6.0, Stroke::new(1.0, if response.hovered() { app.tokens.accent } else { app.tokens.separator }), StrokeKind::Inside);
                                    android_curve_preview(ui, card, preview, app.tokens.accent);
                                    ui.painter().text(pos2(card.center().x, card.max.y - 13.0), Align2::CENTER_CENTER, label, Tokens::ui(10.5), app.tokens.text);
                                    if response.clicked() {
                                        picked = Some((command, params));
                                    }
                                }
                            });
                        });
                });
            if let Some((command, params)) = picked {
                android_apply_curve(app, &ctx, current, command, params);
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
    anchor = "/// Synthetic group uid for the Geometry Options row of a 3D text or shape layer in a Classic 3D comp, which only offers \\\"Change Renderer…\\\" (never a real property uid).\\n"
    source = replace_once(source, anchor, type_and_helpers + "\\n" + anchor, "curve quick access helpers")

    prop_anchor = '''    prop_expression_hint(app, ui, g, rc, prop);
    if !g.graph_on {
        for k in &prop.keys {
'''
    prop_replacement = '''    prop_expression_hint(app, ui, g, rc, prop);
    if !g.graph_on {
        android_curve_segment_hit(app, ui, g, rc, prop);
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
