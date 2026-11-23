#!/usr/bin/env python3
"""Unify AM layer transform, effect and animation controls in one AM-only sheet."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_AM_MOTION_EFFECT_EDITOR_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


MOTION_HELPERS = r'''
// EFFECTCRAFT_AM_MOTION_EFFECT_EDITOR_V1
const AM_MOTION_TAB_ID: &str = "am-mobile-motion-tab";

/// Read the selected layer's 3D state without changing the independent Ae workspace.
fn am_layer_is_3d(app: &EffectcraftApp, layer_id: u64) -> bool {
    app.session.active_comp()
        .and_then(|comp| comp.layers.iter().find(|layer| layer.id.0 == layer_id))
        .is_some_and(|layer| layer.is_3d())
}

/// Mirror the current Scale component at the playhead. When the property is animated,
/// prop.set writes the value at the current time and therefore preserves the other keys.
fn am_flip_scale(app: &mut EffectcraftApp, ctx: &egui::Context, layer_id: u64, axis: usize) {
    let time = app.session.time();
    let scale = app.session.active_comp()
        .and_then(|comp| comp.layers.iter().find(|layer| layer.id.0 == layer_id))
        .and_then(|layer| {
            let prop = layer.props.prop("transform/scale")?;
            let mut value = prop.value_at(layer.layer_time(time)).as_vec3();
            if axis >= value.len() {
                return None;
            }
            value[axis] = -value[axis];
            Some(value)
        });
    if let Some(value) = scale {
        invoke(app, ctx, "prop.set", json!({
            "layer": layer_id,
            "path": "transform/scale",
            "value": value,
            "merge": "am-motion-flip"
        }));
    } else {
        app.ui.status = "无法读取该图层的缩放参数。".into();
    }
}

/// AM-owned tab sheet. Shared engine/property panels are reused only as content; the
/// sheet, navigation, 3D switch, flip controls and touch context belong to AM alone.
fn am_motion_editor(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let ctx = ui.ctx().clone();
    let tab_id = Id::new(AM_MOTION_TAB_ID);
    let mut active = ctx.data(|d| d.get_temp::<String>(tab_id)).unwrap_or_else(|| "transform".to_string());
    let tabs = [
        ("变换", "transform"),
        ("效果", "effects"),
        ("关键帧 / 曲线", "keyframes"),
    ];
    let tab_h = 34.0;
    let tab_rect = Rect::from_min_size(rect.min, vec2(rect.width(), tab_h));
    let p = ui.painter().with_clip_rect(tab_rect);
    p.rect_filled(tab_rect, 0.0, app.tokens.header_bg);
    let tab_w = (tab_rect.width() / tabs.len() as f32).max(1.0);
    for (index, (label, value)) in tabs.into_iter().enumerate() {
        let r = Rect::from_min_size(
            pos2(tab_rect.min.x + index as f32 * tab_w + 3.0, tab_rect.min.y + 3.0),
            vec2((tab_w - 6.0).max(1.0), tab_h - 6.0),
        );
        let selected = active == value;
        let response = ui.interact(r, Id::new(("am-motion-tab", value)), Sense::click());
        p.rect_filled(r, 6.0, if selected { app.tokens.row_selected } else { app.tokens.field_bg });
        p.text(r.center(), Align2::CENTER_CENTER, label, Tokens::semibold(11.0),
            if selected { app.tokens.accent } else { app.tokens.text_dim });
        app.auto.add_response(&format!("am.motion.tab.{value}"), &response, label);
        if response.clicked() {
            active = value.to_string();
            ctx.data_mut(|d| d.insert_temp(tab_id, active.clone()));
        }
    }

    let content = Rect::from_min_max(pos2(rect.min.x, tab_rect.max.y + 2.0), rect.max);
    let layer_id = ctx.data(|d| d.get_temp::<u64>(Id::new(AM_ACTIVE_LAYER_ID)));
    let Some(layer_id) = layer_id else {
        ui.painter().text(content.center(), Align2::CENTER_CENTER,
            "请先在时间轴中选择一个图层素材。", Tokens::ui(12.0), app.tokens.text_dim);
        return;
    };

    match active.as_str() {
        "transform" => {
            let toolbar_h = 38.0;
            let toolbar = Rect::from_min_size(content.min, vec2(content.width(), toolbar_h));
            let p = ui.painter().with_clip_rect(toolbar);
            p.rect_filled(toolbar, 0.0, app.tokens.panel_bg);
            let is_3d = am_layer_is_3d(app, layer_id);
            let buttons = [
                (if is_3d { "关闭三维" } else { "开启三维侧翻" }, "three_d"),
                ("水平翻转", "flip_x"),
                ("垂直翻转", "flip_y"),
            ];
            let gap = 4.0;
            let width = ((toolbar.width() - 16.0 - gap * 2.0) / 3.0).max(1.0);
            for (index, (label, action)) in buttons.into_iter().enumerate() {
                let r = Rect::from_min_size(
                    pos2(toolbar.min.x + 6.0 + index as f32 * (width + gap), toolbar.min.y + 4.0),
                    vec2(width, toolbar.height() - 8.0),
                );
                let response = ui.put(r, egui::Button::new(label).min_size(r.size()));
                app.auto.add_response(&format!("am.motion.transform.{action}"), &response, label);
                if response.clicked() {
                    match action {
                        "three_d" => invoke(app, &ctx, "layer.setSwitch", json!({
                            "layers": [layer_id], "switch": "threeD", "value": !is_3d
                        })),
                        "flip_x" => am_flip_scale(app, &ctx, layer_id, 0),
                        "flip_y" => am_flip_scale(app, &ctx, layer_id, 1),
                        _ => {}
                    }
                }
            }
            let body = Rect::from_min_max(pos2(content.min.x, toolbar.max.y + 2.0), content.max);
            let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
            crate::panels::show(app, &mut child, PanelKind::Properties, body);
        }
        "effects" => {
            let toolbar_h = 38.0;
            let toolbar = Rect::from_min_size(content.min, vec2(content.width(), toolbar_h));
            let r = Rect::from_min_size(pos2(toolbar.min.x + 7.0, toolbar.min.y + 4.0),
                vec2((toolbar.width() - 14.0).max(1.0), toolbar.height() - 8.0));
            let add = ui.put(r, egui::Button::new("＋ 添加效果").min_size(r.size()));
            app.auto.add_response("am.motion.effects.add", &add, "打开效果浏览器并添加效果");
            if add.clicked() {
                am_open_effect_browser(&ctx, Some(layer_id));
            }
            let body = Rect::from_min_max(pos2(content.min.x, toolbar.max.y + 2.0), content.max);
            let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
            crate::panels::show(app, &mut child, PanelKind::EffectControls, body);
        }
        "keyframes" => {
            let info_h = 32.0;
            let info = Rect::from_min_size(content.min, vec2(content.width(), info_h));
            ui.painter().text(pos2(info.min.x + 8.0, info.center().y),
                Align2::LEFT_CENTER, "选中属性后可添加关键帧；在两个关键帧之间调整曲线。", Tokens::ui(10.0), app.tokens.text_dim);
            let body = Rect::from_min_max(pos2(content.min.x, info.max.y + 2.0), content.max);
            let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
            crate::panels::show(app, &mut child, PanelKind::Timeline, body);
        }
        _ => {
            ctx.data_mut(|d| d.insert_temp(tab_id, "transform".to_string()));
        }
    }
}
'''


def patch_module(root: Path) -> None:
    path = root / "crates/ui-egui/src/am_editor.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("AM motion/effect editor is already installed.")
        return

    source = replace_once(
        source,
        'fn tool_drawer(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {',
        MOTION_HELPERS + '\nfn tool_drawer(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {',
        "install AM motion/effect editor helpers",
    )

    source = replace_once(
        source,
        '        "keyframes" => Some(PanelKind::Timeline),\n        "add" => None,',
        '        "keyframes" => Some(PanelKind::Timeline),\n        "motion" => None,\n        "add" => None,',
        "register the unified AM motion drawer",
    )

    source = replace_once(
        source,
        '        "keyframes" => "关键帧 / 曲线",\n        _ => "工具",',
        '        "keyframes" => "关键帧 / 曲线",\n        "motion" => "移动与效果",\n        _ => "工具",',
        "name the unified AM motion drawer",
    )

    source = replace_once(
        source,
        '    if kind != "add" {',
        '    if kind != "add" && kind != "motion" {',
        "keep the unified motion drawer tabs inside the AM sheet",
    )

    old_cards = '''    let cards = [
        ("颜色和填充", "fill"),
        ("边框和阴影", "border"),
        ("混合和不透明度", "blend"),
        ("移动和转换", "transform"),
        ("编辑形状", "shape"),
        ("预设", "presets"),
        ("效果", "effects"),
    ];'''
    new_cards = '''    let cards = [
        ("颜色和填充", "fill"),
        ("边框和阴影", "border"),
        ("混合和不透明度", "blend"),
        ("移动与效果", "motion"),
        ("编辑形状", "shape"),
        ("预设", "presets"),
    ];'''
    source = replace_once(source, old_cards, new_cards, "combine AM transform and effects entries")

    old_grid = '''        let (column, row, columns) = if index < 3 { (index, 0, 3) } else { (index - 3, 1, 4) };'''
    new_grid = '''        let columns = 3;
        let column = index % columns;
        let row = index / columns;'''
    source = replace_once(source, old_grid, new_grid, "lay out the six AM layer-action cards evenly")

    old_click = '''            if kind == "effects" { am_open_effect_browser(ui.ctx(), Some(layer_id)); } else { ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), kind.to_string())); }'''
    new_click = '''            if kind == "motion" {
                select_layer(app, layer_id);
                ui.ctx().data_mut(|d| {
                    d.insert_temp(Id::new(AM_ACTIVE_LAYER_ID), layer_id);
                    d.insert_temp(Id::new(AM_MOTION_TAB_ID), "transform".to_string());
                    d.insert_temp(Id::new("am-mobile-tool-drawer"), "motion".to_string());
                });
            } else {
                ui.ctx().data_mut(|d| d.insert_temp(Id::new("am-mobile-tool-drawer"), kind.to_string()));
            }'''
    source = replace_once(source, old_click, new_click, "open the AM motion/effect sheet for the tapped layer")

    old_draw = '''    } else if let Some(panel) = panel {
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
        // This flag is scoped to the AM drawer's native parameter panel for this frame.
        // The shared Ae panels never enable the AM-only touch-scroll path.
        ui.ctx().data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true));
        crate::panels::show(app, &mut child, panel, body);
        ui.ctx().data_mut(|d| d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1")));
    }'''
    new_draw = '''    } else if kind == "motion" {
        // All three tabs are hosted by the AM-owned sheet; only the inner editing widgets
        // are shared. Keep Android touch scrolling scoped to this AM sheet.
        ui.ctx().data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true));
        // EFFECTCRAFT_AM_MOTION_PANIC_BOUNDARY_V1
        // Isolate recoverable Rust panics in the AM-specific controls before they
        // unwind through the Android editor event loop. Keep the shared project intact.
        if let Err(payload) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            am_motion_editor(app, ui, body);
        })) {
            let detail = payload.downcast_ref::<String>().map(String::as_str)
                .or_else(|| payload.downcast_ref::<&str>().copied()).unwrap_or("unknown panic");
            log::error!("AM Move & Transform panel panic isolated: {detail}");
            app.ui.status = "移动与变换面板出现异常，已保护工程并关闭面板。".to_string();
            ui.ctx().data_mut(|d| {
                d.remove::<String>(Id::new("am-mobile-tool-drawer"));
                d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"));
                d.remove::<bool>(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY"));
            });
        }
        ui.ctx().data_mut(|d| d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1")));
    } else if let Some(panel) = panel {
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
        // This flag is scoped to the AM drawer's native parameter panel for this frame.
        // The shared Ae panels never enable the AM-only touch-scroll path.
        ui.ctx().data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true));
        crate::panels::show(app, &mut child, panel, body);
        ui.ctx().data_mut(|d| d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1")));
    }'''
    source = replace_once(source, old_draw, new_draw, "render the unified AM motion/effect editor")

    old_success = '''                d.insert_temp(Id::new("am-mobile-tool-drawer"), "controls".to_string());
                d.remove::<u64>(Id::new(AM_ACTIVE_LAYER_ID));'''
    new_success = '''                d.insert_temp(Id::new("am-mobile-tool-drawer"), "motion".to_string());
                d.insert_temp(Id::new(AM_MOTION_TAB_ID), "effects".to_string());
                d.insert_temp(Id::new(AM_ACTIVE_LAYER_ID), layer_id);'''
    source = replace_once(source, old_success, new_success, "return to AM effect parameters after applying an effect")

    old_height = '''        if kind == "keyframes" {
            (rect.height() * 0.76).clamp(300.0, 620.0).min(rect.height() * 0.82)
        } else if kind == "controls" {'''
    new_height = '''        if kind == "motion" {
            (rect.height() * 0.74).clamp(340.0, 680.0).min(rect.height() * 0.84)
        } else if kind == "keyframes" {
            (rect.height() * 0.76).clamp(300.0, 620.0).min(rect.height() * 0.82)
        } else if kind == "controls" {'''
    source = replace_once(source, old_height, new_height, "give the AM motion sheet enough room for touch editing")

    required = (
        MARKER,
        '("移动与效果", "motion")',
        '("关键帧 / 曲线", "keyframes")',
        'PanelKind::Properties',
        'PanelKind::EffectControls',
        'PanelKind::Timeline',
        '"layer.setSwitch"',
        '"transform/scale"',
        '"prop.set"',
        'am_open_effect_browser(&ctx, Some(layer_id))',
        'd.insert_temp(Id::new(AM_ACTIVE_LAYER_ID), layer_id)',
    )
    missing = [token for token in required if token not in source]
    if missing:
        raise SystemExit("AM motion/effect editor verification failed: " + "; ".join(missing))
    path.write_text(source, encoding="utf-8")
    print("Installed the AM-only Move & Effects sheet with Transform, Effects, and Keyframes/Curves tabs.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to checked-out EffectCraft source.")
    patch_module(root)


if __name__ == "__main__":
    main()
