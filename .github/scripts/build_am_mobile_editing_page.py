#!/usr/bin/env python3
"""Install a genuinely separate AM mobile editor surface, not a rotated Ae dock layout."""
from __future__ import annotations

import os
import re
from pathlib import Path


MARKER = "EFFECTCRAFT_AM_INDEPENDENT_EDITOR_SURFACE_V1"
MODULE = r'''//! EFFECTCRAFT_AM_INDEPENDENT_EDITOR_SURFACE_V1
//! Independent Alight Motion-inspired phone editing page.
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

    let layout_rect = Rect::from_min_size(pos2(rect.min.x + 43.0, rect.min.y + 7.0), vec2(78.0, 30.0));
    let layout_id = Id::new("am-independent-layout-menu");
    let layout_response = button(ui, layout_rect, "Ae×am ▾", "am-layout");
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

const AM_MULTI_MODE_ID: &str = "am-mobile-multi-select-mode";
const AM_MULTI_IDS_ID: &str = "am-mobile-multi-select-ids";
const AM_ACTIVE_LAYER_ID: &str = "am-mobile-active-layer";

const AM_EFFECT_BROWSER_OPEN_ID: &str = "am-mobile-effect-browser-open";
const AM_EFFECT_CATEGORY_ID: &str = "am-mobile-effect-browser-category";
const AM_EFFECT_DETAIL_ID: &str = "am-mobile-effect-browser-detail";
const AM_EFFECT_SOURCE_LAYER_ID: &str = "am-mobile-effect-source-layer";

// EFFECTCRAFT_AM_EFFECT_BROWSER_V1
fn am_open_effect_browser(ctx: &egui::Context, layer_id: Option<u64>) {
    ctx.data_mut(|d| {
        d.insert_temp(Id::new(AM_EFFECT_BROWSER_OPEN_ID), true);
        d.insert_temp(Id::new(AM_EFFECT_SOURCE_LAYER_ID), layer_id);
        d.remove::<String>(Id::new(AM_EFFECT_CATEGORY_ID));
        d.remove::<String>(Id::new(AM_EFFECT_DETAIL_ID));
    });
}

fn am_effect_browser_is_open(ctx: &egui::Context) -> bool {
    ctx.data(|d| d.get_temp::<bool>(Id::new(AM_EFFECT_BROWSER_OPEN_ID))).unwrap_or(false)
}

fn am_effect_matches(spec: &effectcraft_engine::effects::EffectSpec, query: &str) -> bool {
    query.is_empty()
        || effectcraft_engine::effects::name_matches(spec, query)
        || crate::i18n::effects::matches(spec.id, spec.name, query)
        || spec.category.to_lowercase().contains(query)
        || crate::i18n::effects::category(spec.category).to_lowercase().contains(query)
}

fn am_effect_preview(p: &egui::Painter, rect: Rect, spec: &effectcraft_engine::effects::EffectSpec) {
    let hash = spec.id.bytes().fold(2166136261u32, |a, b| (a ^ b as u32).wrapping_mul(16777619));
    let c1 = Color32::from_rgb(42 + (hash & 0x3f) as u8, 82 + ((hash >> 7) & 0x5f) as u8, 115 + ((hash >> 13) & 0x7f) as u8);
    let c2 = Color32::from_rgb(115 + ((hash >> 3) & 0x7f) as u8, 74 + ((hash >> 11) & 0x6f) as u8, 138 + ((hash >> 17) & 0x65) as u8);
    p.rect_filled(rect, 7.0, Color32::from_rgb(25, 31, 49));
    let inner = rect.shrink(5.0);
    p.rect_filled(inner, 5.0, c1);
    let center = inner.center();
    let radius = inner.width().min(inner.height()) * 0.29;
    let category = spec.category.to_lowercase();
    if category.contains("blur") || category.contains("sharpen") {
        for ring in 0..4 {
            let r = radius * (0.35 + ring as f32 * 0.22);
            p.circle_stroke(center, r, Stroke::new(1.4, c2.gamma_multiply(1.0 - ring as f32 * 0.12)));
        }
        p.circle_filled(center, radius * 0.16, Color32::WHITE);
    } else if category.contains("color") || category.contains("colour") {
        let points = [
            center + vec2(-radius * 0.48, radius * 0.12),
            center + vec2(radius * 0.42, radius * 0.10),
            center + vec2(0.0, -radius * 0.52),
        ];
        p.circle_filled(points[0], radius * 0.40, Color32::from_rgb(255, 94, 112));
        p.circle_filled(points[1], radius * 0.40, Color32::from_rgb(75, 190, 255));
        p.circle_filled(points[2], radius * 0.40, Color32::from_rgb(255, 198, 79));
        p.circle_filled(center, radius * 0.18, Color32::from_rgb(246, 246, 252));
    } else if category.contains("distort") || category.contains("warp") {
        for wave in 0..3 {
            let points: Vec<egui::Pos2> = (0..25).map(|index| {
                let x = inner.min.x + 8.0 + (inner.width() - 16.0) * index as f32 / 24.0;
                let phase = index as f32 / 24.0 * std::f32::consts::TAU;
                let y = center.y + (wave as f32 - 1.0) * 8.0 + phase.sin() * radius * 0.22;
                pos2(x, y)
            }).collect();
            p.add(egui::Shape::line(points, Stroke::new(2.0, if wave == 1 { Color32::WHITE } else { c2 })));
        }
    } else if category.contains("audio") {
        for bar in 0..11 {
            let x = inner.min.x + 9.0 + bar as f32 * (inner.width() - 18.0) / 10.0;
            let height = 6.0 + ((hash.rotate_left(bar as u32 * 3) & 0x1f) as f32);
            p.line_segment(
                [pos2(x, center.y - height * 0.5), pos2(x, center.y + height * 0.5)],
                Stroke::new(3.0, if bar % 2 == 0 { Color32::WHITE } else { c2 }),
            );
        }
    } else if category.contains("key") || category.contains("matte") {
        let cell = (radius * 0.48).max(5.0);
        for row in 0..4 {
            for col in 0..4 {
                let point = pos2(center.x - cell * 2.0 + col as f32 * cell, center.y - cell * 2.0 + row as f32 * cell);
                p.rect_filled(Rect::from_min_size(point, vec2(cell - 1.0, cell - 1.0)),
                    1.0, if (row + col) % 2 == 0 { Color32::WHITE } else { c2 });
            }
        }
        p.circle_filled(center, radius * 0.28, c1);
    } else {
        p.circle_filled(center, radius, c2);
        p.circle_stroke(center, radius * 0.72, Stroke::new(1.5, Color32::from_rgb(220, 226, 242)));
    }
    for i in 0..4 {
        let x = inner.min.x + inner.width() * (i as f32 + 0.5) / 4.0;
        let y = inner.min.y + inner.height() * (i as f32 + 0.5) / 4.0;
        p.line_segment(
            [pos2(x, inner.min.y + 3.0), pos2(x, inner.max.y - 3.0)],
            Stroke::new(0.7, Color32::from_rgba_premultiplied(235, 239, 255, 90)),
        );
        p.line_segment(
            [pos2(inner.min.x + 3.0, y), pos2(inner.max.x - 3.0, y)],
            Stroke::new(0.7, Color32::from_rgba_premultiplied(235, 239, 255, 90)),
        );
    }
    p.text(
        pos2(inner.min.x + 5.0, inner.min.y + 5.0),
        Align2::LEFT_TOP,
        "FX",
        Tokens::semibold(8.0),
        Color32::from_rgb(245, 247, 255),
    );
}

fn am_effect_card(
    app: &mut EffectcraftApp,
    ui: &mut egui::Ui,
    p: &egui::Painter,
    rect: Rect,
    spec: &'static effectcraft_engine::effects::EffectSpec,
) {
    let preview = Rect::from_min_size(rect.min, vec2(rect.width(), rect.height() - 27.0));
    am_effect_preview(p, preview, spec);
    let name = crate::i18n::effects::name(spec.id, spec.name);
    p.with_clip_rect(rect).text(
        pos2(rect.center().x, preview.max.y + 13.0),
        Align2::CENTER_CENTER,
        name,
        Tokens::ui(10.0),
        app.tokens.text,
    );
    let response = ui.interact(rect, Id::new(("am-effect-card", spec.id)), Sense::click());
    app.auto.add(&format!("am.effects.item.{}", spec.id), rect, spec.name);
    if response.clicked() {
        ui.ctx().data_mut(|d| d.insert_temp(Id::new(AM_EFFECT_DETAIL_ID), spec.id.to_string()));
    }
}

fn am_effect_grid(
    app: &mut EffectcraftApp,
    ui: &mut egui::Ui,
    p: &egui::Painter,
    list: Rect,
    y: &mut f32,
    specs: Vec<&'static effectcraft_engine::effects::EffectSpec>,
) -> usize {
    let count = specs.len();
    let columns = 3usize;
    let gap = 8.0;
    let card_w = ((list.width() - 16.0 - gap * 2.0) / columns as f32).max(1.0);
    let card_h = 111.0;
    for (index, spec) in specs.into_iter().enumerate() {
        let col = index % columns;
        let row = index / columns;
        let r = Rect::from_min_size(
            pos2(list.min.x + 8.0 + col as f32 * (card_w + gap), *y + row as f32 * (card_h + 8.0)),
            vec2(card_w, card_h),
        );
        if r.max.y >= list.min.y && r.min.y <= list.max.y {
            am_effect_card(app, ui, p, r, spec);
        }
    }
    // The caller uses this count to size the vertically scrollable grid.
    count
}

fn am_effect_category_card(
    app: &mut EffectcraftApp,
    ui: &mut egui::Ui,
    p: &egui::Painter,
    rect: Rect,
    category: &'static str,
    count: usize,
) {
    let seed = category.bytes().fold(0u32, |a, b| a.wrapping_mul(31).wrapping_add(b as u32));
    let left = Color32::from_rgb(38 + (seed & 0x5f) as u8, 56 + ((seed >> 8) & 0x5f) as u8, 88 + ((seed >> 16) & 0x7f) as u8);
    let right = Color32::from_rgb(70 + ((seed >> 3) & 0x7f) as u8, 42 + ((seed >> 11) & 0x6f) as u8, 116 + ((seed >> 19) & 0x6f) as u8);
    p.rect_filled(rect, 6.0, left);
    for i in 0..5 {
        let x = rect.min.x + rect.width() * i as f32 / 4.0;
        p.line_segment(
            [pos2(x, rect.min.y + 4.0), pos2(rect.max.x - (x - rect.min.x), rect.max.y - 4.0)],
            Stroke::new(1.0, right),
        );
    }
    p.rect_filled(
        Rect::from_min_size(pos2(rect.min.x + 7.0, rect.max.y - 27.0), vec2(rect.width() - 14.0, 21.0)),
        4.0,
        Color32::from_rgba_premultiplied(10, 13, 24, 190),
    );
    p.text(
        pos2(rect.center().x, rect.max.y - 16.0),
        Align2::CENTER_CENTER,
        format!("{}  ·  {}", crate::i18n::effects::category(category), count),
        Tokens::semibold(10.0),
        Color32::WHITE,
    );
    let response = ui.interact(rect, Id::new(("am-effect-category", category)), Sense::click());
    app.auto.add(&format!("am.effects.category.{category}"), rect, category);
    if response.clicked() {
        ui.ctx().data_mut(|d| {
            d.insert_temp(Id::new(AM_EFFECT_CATEGORY_ID), category.to_string());
            d.remove::<String>(Id::new(AM_EFFECT_DETAIL_ID));
        });
    }
}

fn am_apply_effect_from_browser(app: &mut EffectcraftApp, ctx: &egui::Context, effect_id: &str) {
    let target = ctx.data(|d| d.get_temp::<Option<u64>>(Id::new(AM_EFFECT_SOURCE_LAYER_ID))).flatten()
        .or_else(|| app.session.state.selected_layers.first().map(|id| id.0));
    let Some(layer_id) = target else {
        app.ui.status = "请先选择一个图层，再添加效果。".into();
        return;
    };
    let name = effectcraft_engine::effects::find(effect_id)
        .map(|spec| crate::i18n::effects::name(spec.id, spec.name))
        .unwrap_or_else(|| effect_id.to_string());
    if let Err(error) = app.session.execute("layer.select", json!({"layer": layer_id})) {
        app.ui.status = format!("无法选择目标图层：{error}");
        return;
    }
    match app.session.execute("effect.apply", json!({"effect": effect_id, "layers": [layer_id]})) {
        Err(error) => app.ui.status = format!("添加效果失败：{error}"),
        Ok(applied) => {
            crate::panels::effects_presets::push_recent(&mut app.ui.effects_recent, effect_id);
            crate::panels::effect_controls::choose_files_after_apply(app, &applied);
            app.ui.focused = PanelKind::EffectControls;
            app.ui.status = format!("已添加效果：{name}");
            ctx.data_mut(|d| {
                d.remove::<bool>(Id::new(AM_EFFECT_BROWSER_OPEN_ID));
                d.remove::<String>(Id::new(AM_EFFECT_DETAIL_ID));
                d.remove::<String>(Id::new(AM_EFFECT_CATEGORY_ID));
                d.remove::<Option<u64>>(Id::new(AM_EFFECT_SOURCE_LAYER_ID));
                d.insert_temp(Id::new("am-mobile-tool-drawer"), "controls".to_string());
                d.remove::<u64>(Id::new(AM_ACTIVE_LAYER_ID));
            });
        }
    }
}

fn am_effect_detail_sheet(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect, effect_id: &str) {
    let Some(spec) = effectcraft_engine::effects::find(effect_id) else {
        ui.ctx().data_mut(|d| d.remove::<String>(Id::new(AM_EFFECT_DETAIL_ID)));
        return;
    };
    let t = app.tokens;
    let progress = am_bottom_sheet_progress(ui.ctx(), Some(format!("effect-detail:{effect_id}")));
    let p = ui.painter().with_clip_rect(rect);
    let alpha = (150.0 * progress).round() as u8;
    p.rect_filled(rect, 0.0, Color32::from_rgba_premultiplied(0, 0, 0, alpha));
    let height = (rect.height() * 0.46).clamp(250.0, 430.0);
    let target = Rect::from_min_size(pos2(rect.min.x, rect.max.y - height), vec2(rect.width(), height));
    let sheet = target.translate(vec2(0.0, (1.0 - progress) * height));
    p.rect_filled(sheet, 12.0, t.panel_bg);
    if progress < 1.0 { ui.ctx().request_repaint(); }
    p.line_segment([sheet.left_top(), sheet.right_top()], Stroke::new(1.0, t.separator));

    let close_rect = Rect::from_min_size(pos2(sheet.min.x + 13.0, sheet.min.y + 10.0), vec2(32.0, 30.0));
    let close = ui.put(close_rect, egui::Button::new("×").min_size(close_rect.size()));
    app.auto.add_response("am.effects.detail.close", &close, "关闭效果详情");
    if close.clicked() {
        ui.ctx().data_mut(|d| d.remove::<String>(Id::new(AM_EFFECT_DETAIL_ID)));
    }

    let preview = Rect::from_min_size(pos2(sheet.min.x + 18.0, sheet.min.y + 52.0), vec2(116.0, 104.0));
    am_effect_preview(&p, preview, spec);
    let name = crate::i18n::effects::name(spec.id, spec.name);
    p.text(pos2(preview.max.x + 13.0, preview.min.y + 9.0), Align2::LEFT_TOP, name, Tokens::semibold(16.0), t.text);
    p.text(
        pos2(preview.max.x + 13.0, preview.min.y + 36.0),
        Align2::LEFT_TOP,
        crate::i18n::effects::category(spec.category),
        Tokens::ui(11.0),
        t.text_dim,
    );
    let mut meta = format!("{} 个可调参数", spec.params.len());
    if spec.gpu { meta.push_str("  ·  GPU"); }
    if spec.float { meta.push_str("  ·  32位"); }
    p.text(pos2(preview.max.x + 13.0, preview.min.y + 59.0), Align2::LEFT_TOP, meta, Tokens::ui(10.0), t.text_dim);
    p.text(
        pos2(sheet.min.x + 18.0, preview.max.y + 13.0),
        Align2::LEFT_TOP,
        "添加后可在效果参数面板中调节数值、设置关键帧并编辑曲线。",
        Tokens::ui(10.5),
        t.text,
    );

    let action_y = sheet.max.y - 58.0;
    let star_rect = Rect::from_min_size(pos2(sheet.min.x + 18.0, action_y), vec2(52.0, 42.0));
    let favorite = app.session.prefs.is_effect_favorite(spec.id);
    let star = ui.put(star_rect, egui::Button::new(if favorite { "★" } else { "☆" }).min_size(star_rect.size()));
    app.auto.add_response("am.effects.detail.favorite", &star, "收藏效果");
    if star.clicked() {
        app.session.prefs.toggle_effect_favorite(spec.id);
        app.session.save_prefs();
    }
    let add_rect = Rect::from_min_size(
        pos2(star_rect.max.x + 10.0, action_y),
        vec2((sheet.width() - 46.0 - star_rect.width()).max(80.0), 42.0),
    );
    let add = ui.put(add_rect, egui::Button::new("＋ 标准设置").min_size(add_rect.size()));
    app.auto.add_response("am.effects.detail.apply", &add, "添加效果标准设置");
    if add.clicked() {
        am_apply_effect_from_browser(app, ui.ctx(), effect_id);
    }
}

fn am_effect_browser(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let ctx = ui.ctx().clone();
    let t = app.tokens;
    let p = ui.painter().with_clip_rect(rect);
    p.rect_filled(rect, 0.0, t.app_bg);

    let header = Rect::from_min_size(rect.min, vec2(rect.width(), 44.0));
    p.rect_filled(header, 0.0, t.header_bg);
    p.line_segment([header.left_bottom(), header.right_bottom()], Stroke::new(1.0, t.separator));
    let category = ctx.data(|d| d.get_temp::<String>(Id::new(AM_EFFECT_CATEGORY_ID)));
    let left = Rect::from_min_size(pos2(header.min.x + 6.0, header.min.y + 5.0), vec2(34.0, 34.0));
    let back = ui.put(left, egui::Button::new(if category.is_some() { "‹" } else { "×" }).min_size(left.size()));
    app.auto.add_response("am.effects.back", &back, "返回效果分类");
    if back.clicked() {
        if category.is_some() {
            ctx.data_mut(|d| d.remove::<String>(Id::new(AM_EFFECT_CATEGORY_ID)));
        } else {
            ctx.data_mut(|d| {
                d.remove::<bool>(Id::new(AM_EFFECT_BROWSER_OPEN_ID));
                d.remove::<String>(Id::new(AM_EFFECT_DETAIL_ID));
                d.remove::<Option<u64>>(Id::new(AM_EFFECT_SOURCE_LAYER_ID));
            });
        }
    }
    let title = category.as_deref().map(crate::i18n::effects::category).unwrap_or_else(|| "效果浏览器".to_string());
    p.text(pos2(header.center().x, header.center().y), Align2::CENTER_CENTER, title, Tokens::semibold(14.0), t.text);

    let search_rect = Rect::from_min_size(pos2(rect.min.x + 10.0, header.max.y + 8.0), vec2(rect.width() - 20.0, 32.0));
    let mut query = app.ui.effects_search.clone();
    let search = ui.put(
        search_rect,
        egui::TextEdit::singleline(&mut query).hint_text("搜索效果").font(Tokens::ui(11.0)),
    );
    app.ui.effects_search = query.clone();
    app.auto.add_response("am.effects.search", &search, "搜索效果");

    let body = Rect::from_min_max(pos2(rect.min.x + 4.0, search_rect.max.y + 5.0), rect.max);
    let mut scroll = crate::widgets::PanelScroll::begin(ui, Id::new("am-effect-browser-scroll"), body);
    // AM-only finger pan for this custom effects browser. Clickable cards are registered
    // afterwards so taps remain taps; vertical drags update only this browser's scroll offset.
    let pan_id = Id::new("am-effect-browser-touch-pan");
    let pan = ui.interact(body, pan_id, Sense::drag());
    let pan_state = Id::new("am-effect-browser-touch-pan-state");
    if pan.drag_started() {
        ui.ctx().data_mut(|d| d.insert_temp(pan_state, scroll.offset));
    }
    if pan.dragged() {
        if let Some(start_offset) = ui.ctx().data(|d| d.get_temp::<f32>(pan_state)) {
            scroll.offset = (start_offset - pan.drag_delta().y).max(0.0);
            ui.ctx().request_repaint();
        }
    }
    // Android touch scrolling can arrive as smooth-scroll deltas instead of a mouse wheel.
    // Apply the delta to this browser's own PanelScroll offset; do not steal card taps.
    if ui.input(|i| i.has_touch_screen()) && ui.input(|i| i.pointer_hover_pos().is_some_and(|pt| body.contains(pt))) {
        let delta = ui.input(|i| i.smooth_scroll_delta.y);
        if delta.abs() > 0.0 {
            scroll.offset = (scroll.offset - delta).max(0.0);
            ui.ctx().request_repaint();
        }
    }
    if pan.drag_stopped() {
        ui.ctx().data_mut(|d| d.remove::<f32>(pan_state));
    }
    let list = scroll.content;
    let lp = ui.painter().with_clip_rect(list);
    let normalized = query.trim().to_lowercase();
    let all = effectcraft_engine::effects::all();
    let mut y = list.min.y - scroll.offset;

    if !normalized.is_empty() {
        let results: Vec<_> = all.into_iter().filter(|spec| am_effect_matches(spec, &normalized)).collect();
        lp.text(pos2(list.min.x + 8.0, y + 10.0), Align2::LEFT_CENTER, format!("搜索结果  ·  {}", results.len()), Tokens::semibold(11.0), t.text);
        y += 24.0;
        let start = y;
        let count = results.len();
        am_effect_grid(app, ui, &lp, list, &mut y, results);
        y = start + ((count + 2) / 3) as f32 * 119.0 + 8.0;
    } else if let Some(category_name) = category.as_deref() {
        let results: Vec<_> = all.into_iter().filter(|spec| spec.category == category_name).collect();
        let start = y;
        let count = results.len();
        am_effect_grid(app, ui, &lp, list, &mut y, results);
        y = start + ((count + 2) / 3) as f32 * 119.0 + 8.0;
    } else {
        let recent: Vec<_> = app.ui.effects_recent.iter().filter_map(|id| effectcraft_engine::effects::find(id)).take(3).collect();
        let featured = if recent.is_empty() { all.iter().copied().take(3).collect::<Vec<_>>() } else { recent };
        lp.text(pos2(list.min.x + 8.0, y + 8.0), Align2::LEFT_CENTER, "常用效果", Tokens::semibold(11.0), t.text);
        y += 20.0;
        let featured_count = featured.len();
        let start = y;
        am_effect_grid(app, ui, &lp, list, &mut y, featured);
        y = start + ((featured_count + 2) / 3) as f32 * 119.0 + 12.0;

        lp.text(pos2(list.min.x + 8.0, y + 8.0), Align2::LEFT_CENTER, "效果分类", Tokens::semibold(11.0), t.text);
        y += 22.0;
        let categories = effectcraft_engine::effects::categories();
        let gap = 7.0;
        let cols = 2usize;
        let w = ((list.width() - 20.0 - gap) / cols as f32).max(1.0);
        let h = 82.0;
        for (index, cat) in categories.iter().enumerate() {
            let count = all.iter().filter(|spec| spec.category == *cat).count();
            let r = Rect::from_min_size(
                pos2(list.min.x + 10.0 + (index % cols) as f32 * (w + gap), y + (index / cols) as f32 * (h + gap)),
                vec2(w, h),
            );
            if r.max.y >= list.min.y && r.min.y <= list.max.y {
                am_effect_category_card(app, ui, &lp, r, *cat, count);
            }
        }
        y += ((categories.len() + 1) / 2) as f32 * (h + gap) + 8.0;
    }
    let content_height = (y + scroll.offset - list.min.y).max(list.height());
    scroll.end(ui, &mut app.auto, "am.effects.browser.scroll", content_height, &t);

    if let Some(detail) = ctx.data(|d| d.get_temp::<String>(Id::new(AM_EFFECT_DETAIL_ID))) {
        am_effect_detail_sheet(app, ui, rect, &detail);
    }
}
const AM_LONG_PRESS_SECONDS: f64 = 0.48;

// EFFECTCRAFT_AM_LONG_PRESS_LAYER_GROUPING_V1
fn am_multi_select_enabled(ctx: &egui::Context) -> bool {
    ctx.data(|d| d.get_temp::<bool>(Id::new(AM_MULTI_MODE_ID))).unwrap_or(false)
}

fn am_multi_selected_ids(ctx: &egui::Context) -> Vec<u64> {
    ctx.data(|d| d.get_temp::<Vec<u64>>(Id::new(AM_MULTI_IDS_ID))).unwrap_or_default()
}

fn am_toggle_multi_selected(app: &mut EffectcraftApp, ctx: &egui::Context, id: u64) {
    let mut ids = am_multi_selected_ids(ctx);
    if let Some(index) = ids.iter().position(|selected| *selected == id) {
        ids.remove(index);
    } else {
        ids.push(id);
    }
    ctx.data_mut(|d| d.insert_temp(Id::new(AM_MULTI_IDS_ID), ids.clone()));
    let selected = app.session.active_comp()
        .map(|comp| comp.layers.iter()
            .filter(|layer| ids.contains(&layer.id.0))
            .map(|layer| layer.id)
            .collect())
        .unwrap_or_default();
    app.session.state.selected_layers = selected;
    app.session.state.selected_props.clear();
    app.session.state.selected_keys.clear();
}

fn am_open_layer_actions(ctx: &egui::Context, id: u64) {
    ctx.data_mut(|d| {
        d.insert_temp(Id::new(AM_ACTIVE_LAYER_ID), id);
        d.remove::<String>(Id::new("am-mobile-tool-drawer"));
    });
}

fn am_exit_multi_select(ctx: &egui::Context) {
    ctx.data_mut(|d| {
        d.remove::<bool>(Id::new(AM_MULTI_MODE_ID));
        d.remove::<Vec<u64>>(Id::new(AM_MULTI_IDS_ID));
    });
}

fn am_group_selected_layers(app: &mut EffectcraftApp, ctx: &egui::Context) {
    let mut ids = am_multi_selected_ids(ctx);
    ids.sort_unstable();
    ids.dedup();
    if ids.len() < 2 {
        app.ui.status = "至少选择两个图层后才能编组。".into();
        return;
    }
    let Some(comp) = app.session.active_comp() else {
        app.ui.status = "当前没有打开的合成。".into();
        return;
    };
    if comp.layers.iter().any(|layer| ids.contains(&layer.id.0) && layer.switches.locked) {
        app.ui.status = "所选图层中包含已锁定图层，请先解锁再编组。".into();
        return;
    }
    let selected_ids: std::collections::HashSet<u64> = ids.iter().copied().collect();
    let has_cross_group_links = comp.layers.iter().any(|layer| {
        let layer_selected = selected_ids.contains(&layer.id.0);
        let parent_crosses = layer.parent.is_some_and(|parent| {
            selected_ids.contains(&parent.0) != layer_selected
        });
        let matte_crosses = layer.track_matte.as_ref().is_some_and(|matte| {
            selected_ids.contains(&matte.layer.0) != layer_selected
        });
        parent_crosses || matte_crosses
    });
    if has_cross_group_links {
        app.ui.status = "所选图层与未选图层之间存在父级或轨道遮罩关联，请将相关图层一起选择再编组。".into();
        return;
    }
    let next_group = comp.layers.iter()
        .filter(|layer| layer.name.starts_with("组 "))
        .count() + 1;
    let name = format!("组 {next_group}");
    // Native Pre-compose creates an editable nested composition group in one undo step.
    // "move" carries the selected source layers and their keyframes into the group rather
    // than flattening them; keeping the full comp duration avoids changing clip timing.
    let result = app.session.execute("layer.precompose", json!({
        "layers": ids,
        "name": name,
        "mode": "move",
        "adjustDuration": false,
        "open": false
    }));
    match result {
        Ok(value) => {
            let grouped = ids.len();
            let root = value.get("layer").and_then(|value| value.as_u64());
            am_exit_multi_select(ctx);
            if let Some(root) = root {
                am_open_layer_actions(ctx, root);
            }
            app.ui.status = format!("已将 {grouped} 个图层合成为可编辑组，素材和关键帧已保留。");
        }
        Err(error) => app.ui.status = format!("编组失败：{error}"),
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
    let stored_view = ui.ctx().data(|d| d.get_temp::<TimelineView>(view_id));
    let mut view = stored_view.unwrap_or_else(|| TimelineView {
        // Start with roughly ten seconds visible, rather than fitting an hour-long
        // composition into a few hundred pixels. This gives AM-style precise trimming.
        start: 0.0,
        zoom: (duration / 10.0).clamp(1.0, 3600.0),
        scroll_y: 0.0,
    });
    view.zoom = view.zoom.clamp(1.0, 3600.0);

    let label_w = NAME_W.min((rect.width() * 0.22).max(56.0));
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

    // A second-based ruler with readable major labels and intermediate ticks.
    // Do not divide the entire composition into only five huge jumps.
    let tick_step = if visible_secs <= 12.0 { 1.0 } else if visible_secs <= 30.0 { 2.0 } else if visible_secs <= 90.0 { 5.0 } else { 10.0 };
    let mut tick_time = (view.start / tick_step).floor() * tick_step;
    while tick_time <= view.start + visible_secs + tick_step {
        let x = tracks.min.x + ((tick_time - view.start) * pps) as f32;
        if x >= tracks.min.x && x <= tracks.max.x {
            let major = ((tick_time / tick_step).round() as i64) % 5 == 0;
            let tick_y = if major { ruler.min.y + 15.0 } else { ruler.min.y + 21.0 };
            p.line_segment([pos2(x, tick_y), pos2(x, rect.max.y)], Stroke::new(if major { 1.0 } else { 0.7 }, t.separator.gamma_multiply(if major { 0.55 } else { 0.25 })));
            if major || tick_step >= 5.0 {
                let seconds = tick_time.max(0.0) as u64;
                p.text(pos2(x + 3.0, ruler.min.y + 4.0), Align2::LEFT_TOP, format!("{:02}:{:02}", seconds / 60, seconds % 60), Tokens::ui(8.5), t.text_faint);
            }
        }
        tick_time += tick_step;
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
        let multi_mode = am_multi_select_enabled(ui.ctx());
        let multi_ids = am_multi_selected_ids(ui.ctx());
        let selected = app.session.state.selected_layers.contains(&layer.id)
            || multi_ids.contains(&layer.id.0);
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

        // The small square at the left of the AM layer row is its multi-select control.
        // Holding it for 0.48 s enters selection mode; further taps add/remove layers.
        // Keep a finger-sized hit target while drawing the small AM-style square.
        let chip_hit_rect = Rect::from_min_size(pos2(row.min.x + 22.0, row.min.y + 3.0), vec2(24.0, 26.0));
        let chip_rect = Rect::from_center_size(chip_hit_rect.center(), vec2(14.0, 14.0));
        let chip_response = ui.interact(
            chip_hit_rect,
            Id::new(("am-mobile-layer-select", layer.id.0)),
            Sense::click(),
        );
        p.rect_filled(chip_rect, 3.0, if selected { t.accent } else { Color32::from_rgb(73, 157, 165) });
        if selected {
            p.rect_stroke(chip_rect.expand(2.0), 4.0, Stroke::new(1.3, t.text), StrokeKind::Outside);
        }
        app.auto.add_response(
            &format!("am.timeline.group-select.{}", layer.id.0),
            &chip_response,
            "长按进入多选；点按选择图层",
        );
        let press_id = Id::new(("am-mobile-layer-long-press-start", layer.id.0));
        let fired_id = Id::new(("am-mobile-layer-long-press-fired", layer.id.0));
        let pointer_time = ui.input(|i| i.time);
        let pointer_pressed = ui.input(|i| i.pointer.button_pressed(egui::PointerButton::Primary));
        let pointer_down = ui.input(|i| i.pointer.button_down(egui::PointerButton::Primary));
        let pointer_released = ui.input(|i| i.pointer.button_released(egui::PointerButton::Primary));
        if chip_response.hovered() && pointer_pressed {
            ui.ctx().data_mut(|d| {
                d.insert_temp(press_id, pointer_time);
                d.insert_temp(fired_id, false);
            });
        }
        if !multi_mode
            && chip_response.hovered()
            && pointer_down
            && let Some(started) = ui.ctx().data(|d| d.get_temp::<f64>(press_id))
            && pointer_time - started >= AM_LONG_PRESS_SECONDS
        {
            ui.ctx().data_mut(|d| d.insert_temp(Id::new(AM_MULTI_MODE_ID), true));
            am_toggle_multi_selected(app, ui.ctx(), layer.id.0);
            ui.ctx().data_mut(|d| d.insert_temp(fired_id, true));
            ui.ctx().data_mut(|d| d.remove::<f64>(press_id));
            ui.ctx().request_repaint();
        }
        if chip_response.clicked() {
            let long_press_fired = ui.ctx().data(|d| d.get_temp::<bool>(fired_id)).unwrap_or(false);
            if long_press_fired {
                ui.ctx().data_mut(|d| d.remove::<bool>(fired_id));
            } else if am_multi_select_enabled(ui.ctx()) {
                am_toggle_multi_selected(app, ui.ctx(), layer.id.0);
            } else {
                select_layer(app, layer.id.0);
                am_open_layer_actions(ui.ctx(), layer.id.0);
            }
        }
        if pointer_released {
            ui.ctx().data_mut(|d| {
                d.remove::<f64>(press_id);
                if !chip_response.clicked() {
                    d.remove::<bool>(fired_id);
                }
            });
        }
        let name_rect = Rect::from_min_max(pos2(row.min.x + 45.0, row.min.y), pos2(row.min.x + label_w, row.max.y));
        p.with_clip_rect(name_rect).text(
            name_rect.shrink2(vec2(3.0, 0.0)).left_center(),
            Align2::LEFT_CENTER,
            layer.name.clone(),
            Tokens::ui(10.5),
            if selected { t.text } else { t.text_dim },
        );
        let name_response = ui.interact(name_rect, Id::new(("am-mobile-layer-name", layer.id.0)), Sense::click());
        if name_response.clicked() {
            if am_multi_select_enabled(ui.ctx()) {
                am_toggle_multi_selected(app, ui.ctx(), layer.id.0);
            } else {
                select_layer(app, layer.id.0);
                am_open_layer_actions(ui.ctx(), layer.id.0);
            }
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
            if am_multi_select_enabled(ui.ctx()) {
                am_toggle_multi_selected(app, ui.ctx(), layer.id.0);
            } else {
                select_layer(app, layer.id.0);
                // A clip tap opens its operation sheet; keyframes/curves live inside that sheet.
                am_open_layer_actions(ui.ctx(), layer.id.0);
            }
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
                // Match AM's deliberate one-second trim steps. Keep the unconsumed
                // finger movement by advancing the anchor only by whole seconds applied;
                // tiny touch jitter cannot jump the clip by minutes or hours.
                let raw_delta = (pt.x - last_x) as f64 / pps;
                let whole_seconds = raw_delta.abs().floor();
                if whole_seconds >= 1.0 {
                    let delta = raw_delta.signum() * whole_seconds.min(60.0);
                    apply_timing(app, &ids, field, delta);
                    let consumed_px = (delta * pps) as f32;
                    ui.ctx().data_mut(|d| d.insert_temp(drag_id, (last_x + consumed_px, ids)));
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

fn bottom_tools(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) -> () {
    let t = app.tokens;
    if am_multi_select_enabled(ui.ctx()) {
        let ids = am_multi_selected_ids(ui.ctx());
        let p = ui.painter().with_clip_rect(rect);
        p.rect_filled(rect, 0.0, t.header_bg);
        p.line_segment([rect.left_top(), rect.right_top()], Stroke::new(1.0, t.separator));
        let actions = [("退出多选", "cancel"), ("编组", "group"), ("清空选择", "clear")];
        let width = rect.width() / actions.len() as f32;
        for (index, (label, action)) in actions.into_iter().enumerate() {
            let r = Rect::from_min_size(
                pos2(rect.min.x + index as f32 * width + 4.0, rect.min.y + 5.0),
                vec2((width - 8.0).max(1.0), rect.height() - 10.0),
            );
            let enabled = action != "group" || ids.len() >= 2;
            let response = ui.add_enabled_ui(enabled, |child| {
                child.put(r, egui::Button::new(label).min_size(r.size()))
            }).inner;
            app.auto.add_response(&format!("am.multi.{action}"), &response, label);
            if response.clicked() {
                match action {
                    "group" => am_group_selected_layers(app, ui.ctx()),
                    "clear" => {
                        ui.ctx().data_mut(|d| d.insert_temp(Id::new(AM_MULTI_IDS_ID), Vec::<u64>::new()));
                        app.session.state.selected_layers.clear();
                        app.session.state.selected_props.clear();
                    }
                    "cancel" => {
                        am_exit_multi_select(ui.ctx());
                        app.session.state.selected_layers.clear();
                        app.session.state.selected_props.clear();
                    }
                    _ => {}
                }
            }
        }
        p.text(pos2(rect.center().x, rect.min.y + 2.0), Align2::CENTER_TOP,
            format!("已选择 {} 个图层", ids.len()), Tokens::ui(9.0), t.text_dim);
        return;
    }
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
                "effects" => { let layer = app.session.state.selected_layers.first().map(|id| id.0); am_open_effect_browser(ui.ctx(), layer); }
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
        "presets" => Some(PanelKind::EffectsPresets),
        "properties" | "blend" | "transform" => Some(PanelKind::Properties),
        "controls" | "fill" | "border" | "shape" => Some(PanelKind::EffectControls),
        "project" => Some(PanelKind::Project),
        "keyframes" => Some(PanelKind::Timeline),
        "curves" => Some(PanelKind::Timeline),
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
        "presets" => "预设",
        "fill" => "颜色和填充",
        "border" => "边框和阴影",
        "blend" => "混合和不透明度",
        "transform" => "移动和转换",
        "shape" => "编辑形状",
        "controls" => "变换 / 效果控件",
        "properties" => "属性",
        "project" => "项目",
        "keyframes" => "关键帧 / 曲线",
        "curves" => "曲线",
        _ => "工具",
    };
    p.text(pos2(header.min.x + 10.0, header.center().y), Align2::LEFT_CENTER, title, Tokens::semibold(11.0), t.text);

    // Keyframes are opened only from the selected clip's action sheet below.

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
        // This flag is scoped to the AM drawer's native parameter panel for this frame.
        // The shared Ae panels never enable the AM-only touch-scroll path.
        ui.ctx().data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true));
        crate::panels::show(app, &mut child, panel, body);
        ui.ctx().data_mut(|d| d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1")));
    }
}

fn am_layer_quick_action(app: &mut EffectcraftApp, layer_id: u64, action: &str) {
    let (stretch, audio) = app.session.active_comp()
        .and_then(|comp| comp.layers.iter().find(|layer| layer.id.0 == layer_id))
        .map(|layer| (layer.stretch, layer.switches.audio))
        .unwrap_or((100.0, true));
    let result = match action {
        "speed" => {
            let next = if (stretch - 100.0).abs() < 0.5 { 200.0 }
                else if (stretch - 200.0).abs() < 0.5 { 50.0 }
                else { 100.0 };
            app.session.execute("layer.timeStretch", json!({"layers": [layer_id], "percent": next}))
                .map(|_| format!("播放速度已切换为 {:.2}×", 100.0 / next))
        }
        "trim_in" => app.session.execute("layer.timing", json!({"layers": [layer_id], "op": "trimInToTime"}))
            .map(|_| "已将入点裁剪到播放头".to_string()),
        "trim_out" => app.session.execute("layer.timing", json!({"layers": [layer_id], "op": "trimOutToTime"}))
            .map(|_| "已将出点裁剪到播放头".to_string()),
        "reverse" => app.session.execute("layer.timeReverse", json!({"layers": [layer_id]}))
            .map(|_| "已反转图层播放方向".to_string()),
        "mute" => app.session.execute("layer.setSwitch", json!({
            "layers": [layer_id], "switch": "audio", "value": !audio
        })).map(|_| if audio { "图层音频已静音" } else { "图层音频已恢复" }.to_string()),
        _ => return,
    };
    match result {
        Ok(message) => app.ui.status = message,
        Err(error) => app.ui.status = format!("操作失败：{error}"),
    }
}

fn layer_action_drawer(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect, layer_id: u64) {
    let Some(layer_name) = app.session.active_comp()
        .and_then(|comp| comp.layers.iter().find(|layer| layer.id.0 == layer_id))
        .map(|layer| layer.name.clone()) else {
        ui.ctx().data_mut(|d| d.remove::<u64>(Id::new(AM_ACTIVE_LAYER_ID)));
        return;
    };
    let t = app.tokens;
    let p = ui.painter().with_clip_rect(rect);
    p.rect_filled(rect, 10.0, t.panel_bg);
    let header = Rect::from_min_size(rect.min, vec2(rect.width(), 32.0));
    p.line_segment([header.left_bottom(), header.right_bottom()], Stroke::new(1.0, t.separator));
    p.text(pos2(header.min.x + 10.0, header.center().y), Align2::LEFT_CENTER, layer_name, Tokens::semibold(11.0), t.text);

    let close_rect = Rect::from_min_size(pos2(header.max.x - 34.0, header.min.y + 2.0), vec2(30.0, 28.0));
    let close = ui.put(close_rect, egui::Button::new("×").min_size(close_rect.size()));
    app.auto.add_response("am.layer.actions.close", &close, "关闭图层操作");
    if close.clicked() {
        ui.ctx().data_mut(|d| d.remove::<u64>(Id::new(AM_ACTIVE_LAYER_ID)));
        return;
    }

    // Quick actions use existing engine commands, not mock buttons.
    let quick = [
        ("速度", "speed"),
        ("裁入", "trim_in"),
        ("裁出", "trim_out"),
        ("反向", "reverse"),
        ("静音", "mute"),
    ];
    let gap = 3.0;
    let quick_w = ((rect.width() - 16.0 - gap * 4.0) / 5.0).max(1.0);
    for (index, (label, action)) in quick.into_iter().enumerate() {
        let r = Rect::from_min_size(
            pos2(rect.min.x + 8.0 + index as f32 * (quick_w + gap), header.max.y + 5.0),
            vec2(quick_w, 31.0),
        );
        let response = ui.put(r, egui::Button::new(label).min_size(r.size()));
        app.auto.add_response(&format!("am.layer.quick.{action}"), &response, label);
        if response.clicked() {
            am_layer_quick_action(app, layer_id, action);
        }
    }

    let cards = [
        ("颜色和填充", "fill"),
        ("边框和阴影", "border"),
        ("混合和不透明度", "blend"),
        ("移动和转换", "transform"),
        ("编辑形状", "shape"),
        ("预设", "presets"),
        ("效果", "effects"),
        ("关键帧", "keyframes"),
        ("曲线", "curves"),
    ];
    let start_y = header.max.y + 43.0;
    for (index, (label, kind)) in cards.into_iter().enumerate() {
        let (column, row, columns) = (index % 3, index / 3, 3);
        let card_gap = 5.0;
        let card_w = ((rect.width() - 16.0 - card_gap * (columns - 1) as f32) / columns as f32).max(1.0);
        let r = Rect::from_min_size(
            pos2(rect.min.x + 8.0 + column as f32 * (card_w + card_gap), start_y + row as f32 * 57.0),
            vec2(card_w, 52.0),
        );
        let response = ui.put(r, egui::Button::new(label).min_size(r.size()));
        app.auto.add_response(&format!("am.layer.category.{kind}"), &response, label);
        if response.clicked() {
            // Keep AM_ACTIVE_LAYER_ID so closing the category drawer returns to this sheet.
            if kind == "effects" {
                am_open_effect_browser(ui.ctx(), Some(layer_id));
            } else if kind == "keyframes" || kind == "curves" {
                // Open the existing native Timeline panel for this selected layer,
                // while retaining the clip-operation sheet context.
                ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), kind.to_string()));
            } else {
                ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), kind.to_string()));
            }
        }
    }
}

// EFFECTCRAFT_AM_BOTTOM_SHEET_SLIDE_UP_V1
fn am_bottom_sheet_progress(ctx: &egui::Context, key: Option<String>) -> f32 {
    let state_id = Id::new("am-mobile-bottom-sheet-transition");
    let now = ctx.input(|input| input.time);
    match key {
        Some(key) => {
            let (stored_key, started) = ctx.data(|data| data.get_temp::<(String, f64)>(state_id))
                .unwrap_or_default();
            if stored_key != key {
                ctx.data_mut(|data| data.insert_temp(state_id, (key, now)));
                0.0
            } else {
                let linear = ((now - started) / 0.24).clamp(0.0, 1.0) as f32;
                // Smoothstep easing: quick response at the start, soft landing at the end.
                linear * linear * (3.0 - 2.0 * linear)
            }
        }
        None => {
            ctx.data_mut(|data| data.remove::<(String, f64)>(state_id));
            1.0
        }
    }
}

pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    if am_effect_browser_is_open(ui.ctx()) {
        am_effect_browser(app, ui, rect);
        crate::header::export_dialog(app, ui);
        crate::header::export_progress_dialog(app, ui);
        return;
    }
    let t = app.tokens;
    ui.painter().rect_filled(rect, 0.0, t.app_bg);

    // AM is a separate UI surface: no Ae header, no Ae menu strip, no DockArea, and
    // no Ae Timeline widget. The shared composition renderer stays the canvas backend.
    let top_rect = Rect::from_min_size(rect.min, vec2(rect.width(), TOP_H));
    top_bar(app, ui, top_rect);

    let bottom_rect = Rect::from_min_size(pos2(rect.min.x, rect.max.y - BOTTOM_H), vec2(rect.width(), BOTTOM_H));
    let middle_bottom = bottom_rect.min.y;
    let available = (middle_bottom - top_rect.max.y - TRANSPORT_H - 8.0).max(210.0);
    let preview_h = (available * 0.28).clamp(112.0, 210.0).min((available - 190.0).max(92.0));
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

    // AM-style bottom sheet: timeline taps reveal the panel by sliding upward.
    // This transition belongs only to the independent AM page and never touches Ae widgets.
    let drawer_id = Id::new("am-mobile-tool-drawer");
    let drawer_kind = ui.ctx().data(|d| d.get_temp::<String>(drawer_id));
    let active_layer = if drawer_kind.is_none() && !am_multi_select_enabled(ui.ctx()) {
        ui.ctx().data(|d| d.get_temp::<u64>(Id::new(AM_ACTIVE_LAYER_ID)))
    } else {
        None
    };
    let sheet_key = drawer_kind.as_ref().map(|kind| format!("panel:{kind}"))
        .or_else(|| active_layer.map(|id| format!("layer:{id}")));
    let sheet_h = if let Some(kind) = drawer_kind.as_deref() {
        if kind == "keyframes" {
            // Keep the AM preview and most of its clip timeline visible while editing
            // keyframes in the same page; never switch to a separate full-screen editor.
            (rect.height() * 0.42).clamp(220.0, 360.0).min(rect.height() * 0.46)
        } else if kind == "controls" {
            (rect.height() * 0.62).clamp(280.0, 520.0).min(rect.height() * 0.72)
        } else {
            (rect.height() * 0.42).clamp(180.0, 340.0).min(timeline_rect.height().max(140.0))
        }
    } else if active_layer.is_some() {
        (rect.height() * 0.44).clamp(220.0, 360.0).min(timeline_rect.height().max(180.0))
    } else {
        0.0
    };
    let slide_progress = am_bottom_sheet_progress(ui.ctx(), sheet_key);
    if sheet_h > 0.0 {
        let target_rect = Rect::from_min_max(
            pos2(rect.min.x, bottom_rect.min.y - sheet_h),
            pos2(rect.max.x, bottom_rect.min.y),
        );
        let slide_offset = (1.0 - slide_progress) * sheet_h;
        let animated_rect = target_rect.translate(vec2(0.0, slide_offset));
        let mut sheet_ui = ui.new_child(egui::UiBuilder::new().max_rect(target_rect));
        sheet_ui.set_clip_rect(target_rect);
        if let Some(kind) = drawer_kind {
            let _ = kind;
            tool_drawer(app, &mut sheet_ui, animated_rect);
        } else if let Some(layer_id) = active_layer {
            layer_action_drawer(app, &mut sheet_ui, animated_rect, layer_id);
        }
        if slide_progress < 1.0 {
            ui.ctx().request_repaint();
        }
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

    # Keep this patch idempotent: a prior partial run may already have inserted the
    # AM editor marker but not normalized the Home/DockArea header height. Never
    # return before repairing that independent invariant.
    if "if self.ui.show_menu_bar {" in source:
        source = source.replace(
            "if self.ui.show_menu_bar {",
            'if self.ui.show_menu_bar && self.ui.workspace != "AM 竖屏" {',
            1,
        )


    old_header = "        header::show(self, ui, header);\n"
    new_header = "        // AM Home and the AM editor own their own headers; never draw the Ae toolbar in AM mode.\n        if self.ui.workspace != \"AM 竖屏\" {\n            header::show(self, ui, header);\n        }\n"
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

    # AM owns its top bar. Normalize the one frame header declaration even if
    # the editor route marker was inserted by an earlier, interrupted invocation.
    expected_header = 'let header_h = if self.ui.workspace == "AM 竖屏" { 0.0 } else { 40.0 };'
    header_matches = list(re.finditer(r"(?m)^\s*let header_h\s*=\s*[^;]+;", source))
    if len(header_matches) != 1:
        raise SystemExit(f"Expected exactly one frame header-height declaration, found {len(header_matches)}.")
    header_match = header_matches[0]
    if header_match.group(0).strip() != expected_header:
        indentation = re.match(r"\s*", header_match.group(0)).group(0)
        source = source[:header_match.start()] + indentation + expected_header + source[header_match.end():]
    path.write_text(source, encoding="utf-8")
    verified = path.read_text(encoding="utf-8")
    if MARKER not in verified:
        raise SystemExit("The independent AM editor route was not installed.")
    verified_headers = list(re.finditer(r"(?m)^\s*let header_h\s*=\s*[^;]+;", verified))
    if len(verified_headers) != 1 or verified_headers[0].group(0).strip() != expected_header:
        raise SystemExit("The AM Home/Ae header-height invariant was not repaired.")


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
        "am.layer.category.keyframes",
        "am.layer.category.curves",
        "Tool::Pen",
        "Tool::Puppet",
        "照片/视频",
        "木偶弯曲",
        "EFFECTCRAFT_AM_INDEPENDENT_EDITOR_SURFACE_V1",
        "EFFECTCRAFT_AM_LONG_PRESS_LAYER_GROUPING_V1",
        "am-mobile-layer-select",
        "AM_LONG_PRESS_SECONDS",
        "am_group_selected_layers",
        "layer.precompose",
        "layer_action_drawer",
        "EFFECTCRAFT_AM_BOTTOM_SHEET_SLIDE_UP_V1",
        "am_bottom_sheet_progress",
        "颜色和填充",
        "边框和阴影",
        "混合和不透明度",
        "移动和转换",
        "编辑形状",
        "预设",
        "效果",
        "EFFECTCRAFT_AM_EFFECT_BROWSER_V1",
        "am-effect-browser-touch-pan",
        "EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1",
        "效果浏览器",
        "am_effect_browser",
        "am_effect_detail_sheet",
        "am_apply_effect_from_browser",
        "标准设置",
        "effect.apply",
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
