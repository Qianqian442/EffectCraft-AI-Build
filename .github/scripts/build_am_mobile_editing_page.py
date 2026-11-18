#!/usr/bin/env python3
"""Install a genuinely separate AM mobile editor surface, not a rotated Ae dock layout."""
from __future__ import annotations

import os
import re
from pathlib import Path


MARKER = "EFFECTCRAFT_AM_INDEPENDENT_EDITOR_SURFACE_V1"
MODULE = r'''//! Independent Alight Motion-inspired phone editing page.
//! This module intentionally does not call the Ae dock tree or the Ae Timeline renderer.
//! It reuses the shared composition renderer and engine commands, while owning the mobile
//! editing layout, multi-layer clip tracks, transport, quick actions and bottom tool drawer.

use egui::{Align2, Color32, Id, Rect, Sense, Stroke, StrokeKind, pos2, vec2};
use serde_json::json;

use crate::EffectcraftApp;
use crate::dock::PanelKind;
use crate::icons::{self, Icon};
use crate::theme::Tokens;
use crate::state::Tool;

const WORKSPACE: &str = "AM 竖屏";
const TOP_H: f32 = 44.0;
const TRANSPORT_H: f32 = 42.0;
const BOTTOM_H: f32 = 54.0;
const ROW_H: f32 = 36.0;
const NAME_W: f32 = 88.0;

#[derive(Clone, Copy)]
struct TimelineView {
    start: f64,
    zoom: f64,
    scroll_y: f32,
}
impl Default for TimelineView {
    fn default() -> Self {
        Self { start: 0.0, zoom: 1.0, scroll_y: 0.0 }
    }
}

fn invoke(app: &mut EffectcraftApp, ctx: &egui::Context, command: &str, params: serde_json::Value) {
    if let Err(error) = crate::menus::invoke(app, ctx, command, params) {
        app.ui.status = error;
    }
}

fn button(ui: &mut egui::Ui, rect: Rect, label: &str, _id: impl std::hash::Hash) -> egui::Response {
    ui.put(rect, egui::Button::new(label).min_size(rect.size()))
        .on_hover_text(label)
}

fn top_bar(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let p = ui.painter().with_clip_rect(rect);
    p.rect_filled(rect, 0.0, t.header_bg);
    p.line_segment([rect.left_bottom(), rect.right_bottom()], Stroke::new(1.0, t.separator));

    let back_rect = Rect::from_min_size(pos2(rect.min.x + 5.0, rect.min.y + 5.0), vec2(34.0, 34.0));
    let back = button(ui, back_rect, "‹", "am-back");
    app.auto.add_response("am.header.back", &back, "返回项目");
    if back.clicked() {
        app.ui.start_screen = true;
    }

    let layout_rect = Rect::from_min_size(pos2(rect.min.x + 43.0, rect.min.y + 7.0), vec2(62.0, 30.0));
    let layout_id = Id::new("am-independent-layout-menu");
    let layout_response = button(ui, layout_rect, "AM ▾", "am-layout");
    app.auto.add_response("am.header.layout", &layout_response, "切换 Ae / AM 布局");
    if layout_response.clicked() {
        crate::widgets::open_popup(ui, layout_id);
    }
    let choices = vec!["Ae 原布局".to_string(), "AM 竖屏布局".to_string()];
    if let Some(choice) = crate::widgets::popup_menu(ui, layout_id, layout_rect.left_bottom(), &choices, Some(1)) {
        app.set_workspace(if choice == 0 { "Default" } else { WORKSPACE });
    }

    let export_rect = Rect::from_min_size(pos2(rect.max.x - 68.0, rect.min.y + 7.0), vec2(62.0, 30.0));
    let export = button(ui, export_rect, "导出", "am-export");
    app.auto.add_response("am.header.export", &export, "导出视频或工程");
    if export.clicked() {
        ui.ctx().data_mut(|d| d.insert_temp(Id::new("effectcraft-export-dialog-open"), true));
    }

    let undo_rect = Rect::from_min_size(pos2(rect.max.x - 150.0, rect.min.y + 7.0), vec2(34.0, 30.0));
    let can_undo = !app.session.history.undo.is_empty();
    let undo = ui.add_enabled_ui(can_undo, |ui| {
        ui.put(undo_rect, egui::Button::new("↶").min_size(undo_rect.size()))
    }).inner;
    app.auto.add_response("am.header.undo", &undo, "撤销");
    if undo.clicked() {
        invoke(app, ui.ctx(), "edit.undo", json!({}));
    }

    let redo_rect = Rect::from_min_size(pos2(rect.max.x - 112.0, rect.min.y + 7.0), vec2(34.0, 30.0));
    let can_redo = !app.session.history.redo.is_empty();
    let redo = ui.add_enabled_ui(can_redo, |ui| {
        ui.put(redo_rect, egui::Button::new("↷").min_size(redo_rect.size()))
    }).inner;
    app.auto.add_response("am.header.redo", &redo, "重做");

    let title_left = layout_rect.max.x + 7.0;
    let title_right = (undo_rect.min.x - 6.0).max(title_left);
    let title_rect = Rect::from_min_max(pos2(title_left, rect.min.y), pos2(title_right, rect.max.y));
    let title = app.session.active_comp_id()
        .and_then(|id| app.session.project.item(id))
        .map(|item| item.name.clone())
        .unwrap_or_else(|| "未命名工程".to_string());
    p.with_clip_rect(title_rect).text(title_rect.left_center(), Align2::LEFT_CENTER, title, Tokens::semibold(12.0), t.text);
}

fn transport(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let p = ui.painter().with_clip_rect(rect);
    p.rect_filled(rect, 0.0, t.panel_bg);
    p.line_segment([rect.left_top(), rect.right_top()], Stroke::new(1.0, t.separator));
    p.line_segment([rect.left_bottom(), rect.right_bottom()], Stroke::new(1.0, t.separator));

    let buttons = [
        (Icon::First, "time.start", "到开头"),
        (Icon::StepBack, "time.previousFrame", "上一帧"),
        (Icon::Play, "playback.toggle", "播放/暂停"),
        (Icon::StepFwd, "time.nextFrame", "下一帧"),
        (Icon::Last, "time.end", "到结尾"),
    ];
    let bw = 34.0;
    let gap = 8.0;
    let total = bw * 5.0 + gap * 4.0;
    let mut x = rect.center().x - total / 2.0;
    for (icon, command, tip) in buttons {
        let r = Rect::from_min_size(pos2(x, rect.min.y + 5.0), vec2(bw, rect.height() - 10.0));
        let active = command == "playback.toggle" && app.playback.playing;
        let response = ui.interact(r, Id::new(("am-transport", command)), Sense::click());
        p.rect_filled(r, 6.0, if active || response.hovered() { t.hover } else { t.field_bg });
        let icon = if active { Icon::Pause } else { icon };
        icons::paint(&p, r.shrink(8.0), icon, if response.hovered() { t.text } else { t.text_dim });
        app.auto.add_response(&format!("am.transport.{command}"), &response, tip);
        if response.clicked() {
            invoke(app, ui.ctx(), command, json!({}));
        }
        x += bw + gap;
    }
    let current = app.session.time().seconds();
    let comp_duration = app.session.active_comp().map(|c| c.duration.seconds()).unwrap_or(0.0);
    let tc = format!("{:02}:{:02}.{:02}", (current / 60.0) as u64, current as u64 % 60, ((current.fract()) * 100.0) as u64);
    p.text(pos2(rect.min.x + 10.0, rect.center().y), Align2::LEFT_CENTER, tc, Tokens::semibold(11.0), t.text);
    p.text(pos2(rect.max.x - 10.0, rect.center().y), Align2::RIGHT_CENTER, format!("{:.1}s", comp_duration), Tokens::ui(10.0), t.text_dim);
}

fn seek_to(app: &mut EffectcraftApp, time: f64) {
    let target = time.max(0.0);
    if let Err(error) = app.session.execute("time.set", json!({"time": target})) {
        app.ui.status = error.to_string();
    }
}

fn layer_ids_for_drag(app: &EffectcraftApp, current: u64) -> Vec<u64> {
    let selected = &app.session.state.selected_layers;
    if selected.iter().any(|id| id.0 == current) && !selected.is_empty() {
        selected.iter().map(|id| id.0).collect()
    } else {
        vec![current]
    }
}

fn apply_timing(app: &mut EffectcraftApp, ids: &[u64], field: &str, value: f64) {
    let params = match field {
        "delta" => json!({"layers": ids, "delta": value, "merge": true}),
        "inDelta" => json!({"layers": ids, "inDelta": value, "merge": true}),
        "outDelta" => json!({"layers": ids, "outDelta": value, "merge": true}),
        _ => return,
    };
    if let Err(error) = app.session.execute("layer.timing", params) {
        app.ui.status = error.to_string();
    }
}

fn select_layer(app: &mut EffectcraftApp, id: u64) {
    if let Err(error) = app.session.execute("layer.select", json!({"layer": id})) {
        app.ui.status = error.to_string();
    }
}

fn draw_timeline(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let p = ui.painter().with_clip_rect(rect);
    p.rect_filled(rect, 0.0, t.app_bg);
    let Some(comp) = app.session.active_comp().cloned() else {
        p.text(rect.center(), Align2::CENTER_CENTER, "打开或新建工程后，图层轨道会显示在这里", Tokens::ui(12.0), t.text_dim);
        return;
    };
    let duration = comp.duration.seconds().max(0.001);
    let view_id = Id::new("am-independent-timeline-view");
    let mut view = ui.ctx().data(|d| d.get_temp::<TimelineView>(view_id)).unwrap_or_default();
    view.zoom = view.zoom.clamp(1.0, 16.0);

    let label_w = NAME_W.min((rect.width() * 0.28).max(64.0));
    let ruler_h = 28.0;
    let ruler = Rect::from_min_size(rect.min, vec2(rect.width(), ruler_h));
    let content = Rect::from_min_max(pos2(rect.min.x, ruler.max.y), rect.max);
    let labels = Rect::from_min_max(content.min, pos2(content.min.x + label_w, content.max.y));
    let tracks = Rect::from_min_max(pos2(labels.max.x, content.min.y), content.max);
    let visible_secs = (duration / view.zoom).clamp(0.1, duration.max(0.1));
    let pps = (tracks.width() as f64 / visible_secs).max(0.01);
    let max_start = (duration - visible_secs).max(0.0);
    view.start = view.start.clamp(0.0, max_start);

    // Pinch zoom and background finger swipe are handled here; clip/edge controls are
    // registered later and therefore retain priority over the track background.
    let pointer = ui.ctx().pointer_hover_pos();
    let hovered = pointer.is_some_and(|pt| rect.contains(pt));
    let zoom_delta = ui.input(|i| i.zoom_delta());
    if hovered && (zoom_delta - 1.0).abs() > 0.002 {
        let old_visible = visible_secs;
        view.zoom = (view.zoom * zoom_delta as f64).clamp(1.0, 16.0);
        let new_visible = (duration / view.zoom).max(0.1);
        if let Some(pt) = pointer {
            let frac = ((pt.x - tracks.min.x) / tracks.width().max(1.0)).clamp(0.0, 1.0) as f64;
            let anchored_time = view.start + old_visible * frac;
            view.start = (anchored_time - new_visible * frac).clamp(0.0, (duration - new_visible).max(0.0));
        }
    }
    if hovered {
        let wheel = ui.input(|i| i.smooth_scroll_delta);
        if wheel.y.abs() > 0.0 {
            view.scroll_y = (view.scroll_y - wheel.y).max(0.0);
        }
    }

    let pan_id = Id::new("am-independent-timeline-pan");
    let pan = ui.interact(tracks, pan_id, Sense::drag());
    let pan_state = Id::new("am-independent-timeline-pan-state");
    if pan.drag_started() {
        if let Some(pt) = pan.interact_pointer_pos() {
            ui.ctx().data_mut(|d| d.insert_temp(pan_state, pt.x));
        }
    }
    if pan.dragged() {
        if let (Some(pt), Some(last_x)) = (
            pan.interact_pointer_pos(),
            ui.ctx().data(|d| d.get_temp::<f32>(pan_state)),
        ) {
            view.start = (view.start - (pt.x - last_x) as f64 / pps).clamp(0.0, max_start);
            ui.ctx().data_mut(|d| d.insert_temp(pan_state, pt.x));
        }
    }
    if pan.drag_stopped() {
        ui.ctx().data_mut(|d| d.remove::<f32>(pan_state));
    }

    // Ruler click/drag scrubs the playhead just as it does in a mobile video editor.
    p.rect_filled(ruler, 0.0, t.panel_bg);
    p.rect_filled(Rect::from_min_size(ruler.min, vec2(label_w, ruler_h)), 0.0, t.panel_bg);
    p.text(pos2(ruler.min.x + 8.0, ruler.center().y), Align2::LEFT_CENTER, "时间轴", Tokens::semibold(10.5), t.text_dim);
    let ruler_track = Rect::from_min_max(pos2(tracks.min.x, ruler.min.y), pos2(tracks.max.x, ruler.max.y));
    let ruler_resp = ui.interact(ruler_track, Id::new("am-mobile-ruler-scrub"), Sense::click_and_drag());
    if (ruler_resp.clicked() || ruler_resp.dragged())
        && let Some(pt) = ruler_resp.interact_pointer_pos()
    {
        let target = view.start + (pt.x - tracks.min.x) as f64 / pps;
        seek_to(app, target.clamp(0.0, duration));
    }

    let tick_count = 5;
    for i in 0..=tick_count {
        let time = view.start + visible_secs * i as f64 / tick_count as f64;
        let x = tracks.min.x + tracks.width() * i as f32 / tick_count as f32;
        p.line_segment([pos2(x, ruler.min.y + 18.0), pos2(x, rect.max.y)], Stroke::new(1.0, t.separator.gamma_multiply(0.35)));
        p.text(pos2(x + 3.0, ruler.min.y + 6.0), Align2::LEFT_TOP, format!("{time:.1}s"), Tokens::ui(9.0), t.text_faint);
    }

    let row_count = comp.layers.len();
    let full_rows_h = row_count as f32 * ROW_H;
    let max_scroll = (full_rows_h - content.height()).max(0.0);
    view.scroll_y = view.scroll_y.clamp(0.0, max_scroll);
    p.rect_filled(labels, 0.0, t.panel_bg.gamma_multiply(0.7));
    p.rect_filled(tracks, 0.0, t.app_bg.gamma_multiply(0.8));
    let now = app.session.time().seconds();
    let playhead_x = tracks.min.x + ((now - view.start) * pps) as f32;
    let playhead = Rect::from_min_max(pos2(playhead_x - 1.0, ruler.min.y), pos2(playhead_x + 1.0, rect.max.y));
    p.rect_filled(playhead, 0.0, Color32::from_rgb(255, 76, 92));

    for (index, layer) in comp.layers.iter().enumerate() {
        let y = content.min.y + index as f32 * ROW_H - view.scroll_y;
        let row = Rect::from_min_size(pos2(rect.min.x, y), vec2(rect.width(), ROW_H));
        if row.max.y < content.min.y || row.min.y > content.max.y {
            continue;
        }
        let selected = app.session.state.selected_layers.contains(&layer.id);
        let row_bg = if selected { t.row_selected } else if index % 2 == 0 { t.panel_bg } else { t.app_bg };
        p.rect_filled(row.intersect(content), 0.0, row_bg);
        p.line_segment([row.left_bottom(), row.right_bottom()], Stroke::new(1.0, t.separator.gamma_multiply(0.45)));
        let eye_rect = Rect::from_min_size(pos2(row.min.x + 3.0, row.min.y + 6.0), vec2(20.0, 24.0));
        let eye_response = ui.interact(eye_rect, Id::new(("am-mobile-layer-eye", layer.id.0)), Sense::click());
        p.text(eye_rect.center(), Align2::CENTER_CENTER, if layer.switches.video { "◉" } else { "○" }, Tokens::ui(12.0), if layer.switches.video { t.text } else { t.text_faint });
        app.auto.add_response(&format!("am.timeline.eye.{}", layer.id.0), &eye_response, "切换图层可见性");
        if eye_response.clicked() {
            if let Err(error) = app.session.execute("layer.setSwitch", json!({
                "layers": [layer.id.0],
                "switch": "video",
                "value": !layer.switches.video
            })) {
                app.ui.status = error.to_string();
            }
        }
        let name_rect = Rect::from_min_max(pos2(row.min.x + 25.0, row.min.y), pos2(row.min.x + label_w, row.max.y));
        p.with_clip_rect(name_rect).text(
            name_rect.shrink2(vec2(3.0, 0.0)).left_center(),
            Align2::LEFT_CENTER,
            layer.name.clone(),
            Tokens::ui(10.5),
            if selected { t.text } else { t.text_dim },
        );
        let name_response = ui.interact(name_rect, Id::new(("am-mobile-layer-name", layer.id.0)), Sense::click());
        if name_response.clicked() {
            select_layer(app, layer.id.0);
        }
        app.auto.add_response(&format!("am.timeline.layer.{}", layer.id.0), &name_response, "选择图层");

        let x0 = tracks.min.x + ((layer.in_point.seconds() - view.start) * pps) as f32;
        let x1 = tracks.min.x + ((layer.out_point.seconds() - view.start) * pps) as f32;
        let bar_min_x = x0.max(tracks.min.x + 1.0);
        let bar_max_x = x1.min(tracks.max.x - 1.0);
        if bar_max_x <= bar_min_x {
            continue;
        }
        let bar = Rect::from_min_max(pos2(bar_min_x, y + 5.0), pos2(bar_max_x, y + ROW_H - 5.0));
        let fill = if selected { Color32::from_rgb(43, 132, 205) } else { Color32::from_rgb(56, 89, 125) };
        p.rect_filled(bar, 5.0, fill);
        if bar.width() > 45.0 {
            p.with_clip_rect(bar.shrink2(vec2(4.0, 1.0))).text(
                bar.shrink2(vec2(7.0, 0.0)).left_center(),
                Align2::LEFT_CENTER,
                layer.name.clone(),
                Tokens::ui(9.5),
                Color32::WHITE,
            );
        }

        // Body movement: a horizontal drag moves the whole selected layer group together.
        let body_resp = ui.interact(bar, Id::new(("am-mobile-clip", layer.id.0)), Sense::click_and_drag());
        app.auto.add_response(&format!("am.timeline.clip.{}", layer.id.0), &body_resp, "拖动片段移动图层");
        if body_resp.clicked() {
            select_layer(app, layer.id.0);
        }
        let move_id = Id::new(("am-mobile-move-state", layer.id.0));
        if body_resp.drag_started() {
            if !app.session.state.selected_layers.contains(&layer.id) {
                select_layer(app, layer.id.0);
            }
            if let Some(pt) = body_resp.interact_pointer_pos() {
                let ids = layer_ids_for_drag(app, layer.id.0);
                ui.ctx().data_mut(|d| d.insert_temp(move_id, (pt.x, ids)));
            }
        }
        if body_resp.dragged()
            && let (Some(pt), Some((last_x, ids))) = (
                body_resp.interact_pointer_pos(),
                ui.ctx().data(|d| d.get_temp::<(f32, Vec<u64>)>(move_id)),
            )
        {
            let delta = (pt.x - last_x) as f64 / pps;
            if delta.abs() > 0.00001 {
                apply_timing(app, &ids, "delta", delta);
                ui.ctx().data_mut(|d| d.insert_temp(move_id, (pt.x, ids)));
            }
        }
        if body_resp.drag_stopped() {
            ui.ctx().data_mut(|d| d.remove::<(f32, Vec<u64>)>(move_id));
            app.session.history.merge_key = None;
        }

        // Separate, finger-sized In / Out handles; these edit the clip edges, not a
        // fixed four-second duration. Every update remains frame-snapped by the engine.
        for (edge, edge_x, field) in [
            ("in", x0, "inDelta"),
            ("out", x1, "outDelta"),
        ] {
            if edge_x < tracks.min.x - 1.0 || edge_x > tracks.max.x + 1.0 {
                continue;
            }
            let grip = Rect::from_center_size(pos2(edge_x, bar.center().y), vec2(16.0, ROW_H - 2.0));
            p.rect_filled(Rect::from_min_max(pos2(edge_x - 2.0, bar.min.y + 2.0), pos2(edge_x + 2.0, bar.max.y - 2.0)), 2.0, Color32::WHITE);
            let response = ui.interact(grip, Id::new(("am-mobile-trim", edge, layer.id.0)), Sense::drag());
            app.auto.add_response(&format!("am.timeline.trim.{}.{}", layer.id.0, edge), &response, if edge == "in" { "拖动片段左边缘调整起点" } else { "拖动片段右边缘延长或缩短时长" });
            let drag_id = Id::new(("am-mobile-trim-state", edge, layer.id.0));
            if response.drag_started() {
                if !app.session.state.selected_layers.contains(&layer.id) {
                    select_layer(app, layer.id.0);
                }
                if let Some(pt) = response.interact_pointer_pos() {
                    let ids = layer_ids_for_drag(app, layer.id.0);
                    ui.ctx().data_mut(|d| d.insert_temp(drag_id, (pt.x, ids)));
                }
            }
            if response.dragged()
                && let (Some(pt), Some((last_x, ids))) = (
                    response.interact_pointer_pos(),
                    ui.ctx().data(|d| d.get_temp::<(f32, Vec<u64>)>(drag_id)),
                )
            {
                let delta = (pt.x - last_x) as f64 / pps;
                if delta.abs() > 0.00001 {
                    apply_timing(app, &ids, field, delta);
                    ui.ctx().data_mut(|d| d.insert_temp(drag_id, (pt.x, ids)));
                }
            }
            if response.drag_stopped() {
                ui.ctx().data_mut(|d| d.remove::<(f32, Vec<u64>)>(drag_id));
                app.session.history.merge_key = None;
            }
        }
    }

    let visible_playhead_x = playhead_x.clamp(tracks.min.x, tracks.max.x);
    p.line_segment([pos2(visible_playhead_x, ruler.min.y), pos2(visible_playhead_x, rect.max.y)], Stroke::new(1.5, Color32::from_rgb(255, 76, 92)));
    p.circle_filled(pos2(visible_playhead_x, ruler.min.y + 2.0), 4.0, Color32::from_rgb(255, 76, 92));
    ui.ctx().data_mut(|d| d.insert_temp(view_id, view));
}

fn bottom_tools(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let p = ui.painter().with_clip_rect(rect);
    p.rect_filled(rect, 0.0, t.header_bg);
    p.line_segment([rect.left_top(), rect.right_top()], Stroke::new(1.0, t.separator));
    let buttons = [
        ("＋ 添加", "add"),
        ("效果", "effects"),
        ("变换", "controls"),
        ("属性", "properties"),
        ("项目", "project"),
    ];
    let width = rect.width() / buttons.len() as f32;
    for (i, (label, action)) in buttons.into_iter().enumerate() {
        let r = Rect::from_min_size(pos2(rect.min.x + i as f32 * width + 3.0, rect.min.y + 5.0), vec2((width - 6.0).max(1.0), rect.height() - 10.0));
        let response = ui.interact(r, Id::new(("am-bottom-tool", action)), Sense::click());
        p.rect_filled(r, 7.0, if response.hovered() { t.hover } else { t.field_bg });
        p.text(r.center(), Align2::CENTER_CENTER, label, Tokens::semibold(11.0), if response.hovered() { t.text } else { t.text_dim });
        app.auto.add_response(&format!("am.tools.{action}"), &response, label);
        if response.clicked() {
            match action {
                "add" => { ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), "add".to_string())); }
                "effects" => { ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), "effects".to_string())); }
                "controls" => { ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), "controls".to_string())); }
                "properties" => { ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), "properties".to_string())); }
                "project" => { ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), "project".to_string())); }
                _ => {}
            }
        }
    }
}

fn tool_drawer(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let id = Id::new("am-mobile-tool-drawer");
    let Some(kind) = ui.ctx().data(|d| d.get_temp::<String>(id)) else { return };
    let panel = match kind.as_str() {
        "effects" => Some(PanelKind::EffectsPresets),
        "properties" => Some(PanelKind::Properties),
        "controls" => Some(PanelKind::EffectControls),
        "project" => Some(PanelKind::Project),
        "keyframes" => Some(PanelKind::Timeline),
        "add" => None,
        _ => return,
    };
    let t = app.tokens;
    let header = Rect::from_min_size(rect.min, vec2(rect.width(), 32.0));
    let body = Rect::from_min_max(pos2(rect.min.x, header.max.y), rect.max);
    let p = ui.painter().with_clip_rect(rect);
    p.rect_filled(rect, 10.0, t.panel_bg);
    p.line_segment([header.left_bottom(), header.right_bottom()], Stroke::new(1.0, t.separator));
    let title = match kind.as_str() {
        "add" => "添加图层",
        "effects" => "效果",
        "controls" => "变换 / 效果控件",
        "properties" => "属性",
        "project" => "项目",
        "keyframes" => "关键帧 / 曲线",
        _ => "工具",
    };
    p.text(pos2(header.min.x + 10.0, header.center().y), Align2::LEFT_CENTER, title, Tokens::semibold(11.0), t.text);

    // The portrait clip timeline remains quick to use; this button opens the original
    // native Ae Timeline panel for detailed keyframe and graph/curve editing.
    if kind != "add" {
        let switch_rect = Rect::from_min_size(
            pos2(header.max.x - 102.0, header.min.y + 2.0),
            vec2(60.0, 28.0),
        );
        let switch_label = if kind == "keyframes" { "返回" } else { "关键帧" };
        let switch = ui.put(switch_rect, egui::Button::new(switch_label).min_size(switch_rect.size()));
        app.auto.add_response("am.drawer.keyframes", &switch, switch_label);
        if switch.clicked() {
            let next = if kind == "keyframes" { "controls" } else { "keyframes" };
            ui.ctx().data_mut(|d| d.insert_temp(id, next.to_string()));
        }
    }

    let close = Rect::from_min_size(pos2(header.max.x - 36.0, header.min.y + 2.0), vec2(32.0, 28.0));
    let response = ui.put(close, egui::Button::new("×").min_size(close.size()));
    if response.clicked() {
        ui.ctx().data_mut(|d| d.remove::<String>(id));
        return;
    }
    if kind == "add" {
        let actions = [
            ("照片/视频", "media"),
            ("音频", "audio"),
            ("文字", "text"),
            ("形状", "shape"),
            ("空对象", "null"),
            ("钢笔", "pen"),
            ("木偶", "puppet"),
            ("木偶弯曲", "puppet_bend"),
            ("木偶加固", "puppet_starch"),
            ("木偶重叠", "puppet_overlap"),
        ];
        let columns = 5;
        let gap = 3.0;
        let cell_w = ((body.width() - 12.0 - gap * (columns - 1) as f32) / columns as f32).max(1.0);
        for (index, (label, action)) in actions.into_iter().enumerate() {
            let col = index % columns;
            let row = index / columns;
            let r = Rect::from_min_size(
                pos2(body.min.x + 6.0 + col as f32 * (cell_w + gap), body.min.y + 12.0 + row as f32 * 54.0),
                vec2(cell_w, 46.0),
            );
            let response = ui.put(r, egui::Button::new(label).min_size(r.size()));
            app.auto.add_response(&format!("am.addLayer.{action}"), &response, label);
            if response.clicked() {
                match action {
                    "media" => invoke(app, ui.ctx(), "file.import", json!({"picturesAndVideos": true})),
                    "audio" => invoke(app, ui.ctx(), "file.import", json!({})),
                    "text" => invoke(app, ui.ctx(), "layer.newText", json!({})),
                    "shape" => invoke(app, ui.ctx(), "layer.newShape", json!({"kind": "rect"})),
                    "null" => invoke(app, ui.ctx(), "layer.newNull", json!({})),
                    "pen" => app.ui.tool = Tool::Pen,
                    "puppet" => app.ui.tool = Tool::Puppet,
                    "puppet_bend" => app.ui.tool = Tool::PuppetBend,
                    "puppet_starch" => app.ui.tool = Tool::PuppetStarch,
                    "puppet_overlap" => app.ui.tool = Tool::PuppetOverlap,
                    _ => {}
                }
                ui.ctx().data_mut(|d| d.remove::<String>(id));
            }
        }
    } else if let Some(panel) = panel {
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
        crate::panels::show(app, &mut child, panel, body);
    }
}

pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    ui.painter().rect_filled(rect, 0.0, t.app_bg);

    // AM is a separate UI surface: no Ae header, no Ae menu strip, no DockArea, and
    // no Ae Timeline widget. The shared composition renderer stays the canvas backend.
    let top_rect = Rect::from_min_size(rect.min, vec2(rect.width(), TOP_H));
    top_bar(app, ui, top_rect);

    let bottom_rect = Rect::from_min_size(pos2(rect.min.x, rect.max.y - BOTTOM_H), vec2(rect.width(), BOTTOM_H));
    let middle_bottom = bottom_rect.min.y;
    let available = (middle_bottom - top_rect.max.y - TRANSPORT_H - 8.0).max(210.0);
    let preview_h = (available * 0.36).clamp(130.0, 260.0).min((available - 160.0).max(100.0));
    let preview_rect = Rect::from_min_size(pos2(rect.min.x, top_rect.max.y + 4.0), vec2(rect.width(), preview_h));
    let transport_rect = Rect::from_min_size(pos2(rect.min.x, preview_rect.max.y), vec2(rect.width(), TRANSPORT_H));
    let timeline_rect = Rect::from_min_max(pos2(rect.min.x, transport_rect.max.y), pos2(rect.max.x, middle_bottom));

    let comp_id = app.session.active_comp_id();
    if comp_id.is_some() {
        let mut viewer_ui = ui.new_child(egui::UiBuilder::new().max_rect(preview_rect));
        let viewer_id = app.ui.active_viewer;
        crate::panels::viewers::show(app, &mut viewer_ui, viewer_id, preview_rect);
    } else {
        let p = ui.painter().with_clip_rect(preview_rect);
        p.rect_filled(preview_rect, 0.0, Color32::from_rgb(15, 17, 21));
        p.text(preview_rect.center(), Align2::CENTER_CENTER, "请打开或新建一个工程", Tokens::ui(12.0), t.text_dim);
    }

    transport(app, ui, transport_rect);
    draw_timeline(app, ui, timeline_rect);
    bottom_tools(app, ui, bottom_rect);

    // Panels open as an AM-style bottom drawer rather than replacing the whole Ae dock.
    let drawer_id = Id::new("am-mobile-tool-drawer");
    if ui.ctx().data(|d| d.get_temp::<String>(drawer_id)).is_some() {
        let drawer_kind = ui.ctx().data(|d| d.get_temp::<String>(drawer_id)).unwrap_or_default();
        let drawer_h = if drawer_kind == "keyframes" {
            (rect.height() * 0.68).clamp(260.0, 500.0).min(timeline_rect.height().max(220.0))
        } else {
            (rect.height() * 0.42).clamp(180.0, 340.0).min(timeline_rect.height().max(140.0))
        };
        let drawer_rect = Rect::from_min_max(pos2(rect.min.x, timeline_rect.max.y - drawer_h), pos2(rect.max.x, bottom_rect.min.y));
        tool_drawer(app, ui, drawer_rect);
    }

    // Export uses the existing encoder, queue and confirmation/progress state.
    crate::header::export_dialog(app, ui);
    crate::header::export_progress_dialog(app, ui);
}
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count == 0 and new in source:
        return source
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_module(root: Path) -> None:
    lib = root / "crates/ui-egui/src/lib.rs"
    source = lib.read_text(encoding="utf-8")
    if "pub mod am_editor;" not in source:
        source = replace_once(source, "pub mod audio;\n", "pub mod am_editor;\npub mod audio;\n", "declare the independent AM editor module")
        lib.write_text(source, encoding="utf-8")
    module = root / "crates/ui-egui/src/am_editor.rs"
    module.write_text(MODULE, encoding="utf-8")


def patch_export_access(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    source = source.replace("fn export_dialog(app:", "pub(crate) fn export_dialog(app:")
    source = source.replace("fn export_progress_dialog(app:", "pub(crate) fn export_progress_dialog(app:")
    if "pub(crate) fn export_dialog(app:" not in source or "pub(crate) fn export_progress_dialog(app:" not in source:
        raise SystemExit("Could not expose the existing native export dialogs to the independent AM page.")
    path.write_text(source, encoding="utf-8")


def patch_frame(root: Path) -> None:
    path = root / "crates/ui-egui/src/app/frame.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    source = source.replace(
        "if self.ui.show_menu_bar {",
        'if self.ui.show_menu_bar && self.ui.workspace != "AM 竖屏" {',
        1,
    )

    old_header = "        header::show(self, ui, header);\n"
    new_header = "        // AM draws its own top bar; do not render the Ae toolbar on the AM page.\n        if self.ui.workspace != \"AM 竖屏\" || self.ui.start_screen {\n            header::show(self, ui, header);\n        }\n"
    source = replace_once(source, old_header, new_header, "skip the Ae toolbar in AM mode")

    source = replace_once(
        source,
        "        self.dock_area(ui, body);\n",
        '''        if self.ui.workspace == "AM 竖屏" && !self.ui.start_screen {
            crate::am_editor::show(self, ui, full);
        } else {
            self.dock_area(ui, body);
        }
        // EFFECTCRAFT_AM_INDEPENDENT_EDITOR_SURFACE_V1
''',
        "route AM editing to its independent surface instead of the Ae DockArea",
    )

    # The old AM base patch used a 64 px header for an extra selector row. The independent
    # surface owns its complete top bar, so the underlying DockArea header height is irrelevant;
    # keep Home's 40 px header and avoid an extra dead strip when the user returns to Home.
    source = source.replace(
        "let header_h = if self.ui.start_screen { 40.0 } else { 64.0 };",
        "let header_h = 40.0;",
    )
    source = source.replace("let header_h = 64.0;", "let header_h = 40.0;")
    path.write_text(source, encoding="utf-8")
    if MARKER not in path.read_text(encoding="utf-8"):
        raise SystemExit("The independent AM editor route was not installed.")


def verify(root: Path) -> None:
    lib = (root / "crates/ui-egui/src/lib.rs").read_text(encoding="utf-8")
    frame = (root / "crates/ui-egui/src/app/frame.rs").read_text(encoding="utf-8")
    module = (root / "crates/ui-egui/src/am_editor.rs").read_text(encoding="utf-8")
    header = (root / "crates/ui-egui/src/header.rs").read_text(encoding="utf-8")
    if "pub mod am_editor;" not in lib:
        raise SystemExit("Independent AM editor module is not registered.")
    for token in (
        MARKER,
        "crate::am_editor::show(self, ui, full);",
        'self.ui.workspace == "AM 竖屏" && !self.ui.start_screen',
    ):
        if token not in frame:
            raise SystemExit(f"AM independent frame route missing: {token}")
    for token in (
        "pub fn show(app:",
        "crate::panels::viewers::show",
        "fn draw_timeline",
        "layer.timing",
        "am-mobile-trim",
        "time.set",
        "fn bottom_tools",
        "fn tool_drawer",
        "am.timeline.eye.",
        "am.addLayer.",
        "PanelKind::Timeline",
        "am.drawer.keyframes",
        "Tool::Pen",
        "Tool::Puppet",
        "照片/视频",
        "木偶弯曲",
    ):
        if token not in module:
            raise SystemExit(f"Independent AM editor module missing feature: {token}")
    if "pub(crate) fn export_dialog(app:" not in header or "pub(crate) fn export_progress_dialog(app:" not in header:
        raise SystemExit("AM editor cannot access the original video export workflow.")
    if "self.dock_area(ui, body);" not in frame:
        raise SystemExit("The Ae DockArea must remain available for the original Ae workspace.")
    print("Verified a separate AM editing surface with its own top bar, canvas, transport, clip tracks, trim handles and bottom tools.")
    print("Verified the Ae DockArea remains the render path for Ae mode; AM no longer uses the Ae dock tree or timeline widget.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to checked-out EffectCraft source.")
    patch_module(root)
    patch_export_access(root)
    patch_frame(root)
    verify(root)


if __name__ == "__main__":
    main()
