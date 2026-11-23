#!/usr/bin/env python3
"""AM effect stack: paired reverse slide layers and long-press vertical parameter scrubbing."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_AM_EFFECT_STACK_REVERSE_SLIDE_V1"
WIDGET_MARKER = "EFFECTCRAFT_AM_EFFECT_VALUE_VERTICAL_SCRUB_V1"

REVERSE_SLIDE = r'''
    // EFFECTCRAFT_AM_EFFECT_STACK_NAV_V1
    // EFFECTCRAFT_AM_EFFECT_STACK_REVERSE_SLIDE_V1
    if section == "effects" {
        let params_open = ctx.data(|d| d.get_temp::<bool>(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_OPEN")).unwrap_or(false));
        // Both layers animate at the same time in opposite directions. The list's ScrollArea
        // keeps its stable id_salt, so its scroll offset survives opening/closing parameters.
        let progress = ctx.animate_value_with_time(
            Id::new("EFFECTCRAFT_AM_EFFECT_REVERSE_SLIDE"),
            if params_open { 1.0 } else { 0.0 },
            0.24,
        );
        let list_body = Rect::from_min_max(
            pos2(center.min.x + 3.0, center.min.y + 36.0),
            center.max,
        );
        if progress < 0.999 {
            let list_rect = list_body.translate(vec2(0.0, progress * list_body.height()));
            let items: Vec<(u64, String)> = app.session.active_comp()
                .and_then(|comp| comp.layers.iter().find(|layer| layer.id.0 == layer_id))
                .and_then(|layer| layer.effects())
                .map(|stack| stack.groups().filter_map(|g| {
                    if let effectcraft_engine::project::GroupKind::Effect { effect } = &g.kind {
                        Some((g.uid, crate::i18n::effects::group(effect, &g.name)))
                    } else { None }
                }).collect())
                .unwrap_or_default();
            let mut list = ui.new_child(egui::UiBuilder::new().max_rect(list_rect));
            egui::ScrollArea::vertical()
                .id_salt("am-effect-stack-list")
                .auto_shrink([false, false])
                .show(&mut list, |list_ui| {
                    if items.is_empty() {
                        list_ui.label("尚未添加效果");
                    }
                    for (uid, name) in &items {
                        let response = list_ui.add_sized(
                            [list_body.width() - 8.0, 42.0],
                            egui::Button::new(name),
                        );
                        app.auto.add_response(&format!("am.motion.effect.select.{uid}"), &response, name);
                        if response.clicked() {
                            ctx.data_mut(|d| {
                                d.insert_temp(Id::new("EFFECTCRAFT_AM_SELECTED_EFFECT_ID"), *uid);
                                d.insert_temp(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_OPEN"), true);
                            });
                        }
                    }
                });
        }

        // The parameter sheet rises from the bottom while the effect stack moves down.
        if params_open || progress > 0.001 {
            let sheet_base = Rect::from_min_max(
                pos2(center.min.x + 3.0, center.min.y + 3.0),
                rect.max,
            );
            let params_rect = sheet_base.translate(vec2(0.0, (1.0 - progress) * sheet_base.height()));
            let header = Rect::from_min_size(params_rect.min, vec2(params_rect.width(), 34.0));
            let back = ui.put(
                Rect::from_min_size(pos2(header.min.x + 5.0, header.min.y + 3.0), vec2(118.0, 27.0)),
                egui::Button::new("‹ 返回效果列表"),
            );
            app.auto.add_response("am.motion.effect_params.back", &back, "向下收起参数面板，返回效果列表");
            if back.clicked() {
                ctx.data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_OPEN"), false));
            }
            // A downward swipe on the free part of the handle also dismisses the parameter layer.
            let swipe_area = Rect::from_min_max(
                pos2(header.min.x + 128.0, header.min.y),
                header.right_bottom(),
            );
            let swipe = ui.interact(swipe_area, Id::new("am-effect-params-dismiss-swipe"), Sense::drag());
            if swipe.dragged() && swipe.drag_delta().y > 34.0 {
                ctx.data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_OPEN"), false));
            }
            let controls_rect = Rect::from_min_max(pos2(params_rect.min.x, header.max.y), params_rect.max);
            ctx.data_mut(|d| {
                d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true);
                d.insert_temp(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY"), true);
            });
            let mut child = ui.new_child(egui::UiBuilder::new().max_rect(controls_rect));
            crate::panels::show(app, &mut child, PanelKind::EffectControls, controls_rect);
            ctx.data_mut(|d| {
                d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"));
                d.remove::<bool>(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY"));
            });
        }

        if progress < 0.001 && !params_open {
            let add = ui.put(
                Rect::from_min_size(pos2(footer.max.x - 105.0, footer.min.y + 5.0), vec2(98.0, 32.0)),
                egui::Button::new("＋ 加入效果"),
            );
            app.auto.add_response("am.motion.effects.add", &add, "打开效果浏览器");
            if add.clicked() {
                am_open_effect_browser(&ctx, Some(layer_id));
            }
            let back = ui.put(
                Rect::from_min_size(pos2(center.min.x + 5.0, center.min.y + 3.0), vec2(94.0, 28.0)),
                egui::Button::new("‹ 返回变换"),
            );
            app.auto.add_response("am.motion.effects.back", &back, "关闭效果面板并返回移动与变换");
            if back.clicked() {
                ctx.data_mut(|d| {
                    d.insert_temp(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_OPEN"), false);
                    d.insert_temp(Id::new(AM_MOTION_TAB_ID), "transform".to_string());
                });
                section = "transform".into();
            }
        }
        return;
    }
'''

def replace_effect_view(source: str) -> str:
    if MARKER in source:
        return source
    start = source.find("    // EFFECTCRAFT_AM_EFFECT_STACK_NAV_V1")
    if start < 0:
        raise SystemExit("AM effect stack navigation anchor was not found")
    end = source.find("\n    let time = app.session.time();", start)
    if end < 0:
        raise SystemExit("AM transform workspace end anchor was not found")
    return source[:start] + REVERSE_SLIDE + source[end:]

def patch_vertical_scrub(source: str) -> str:
    if WIDGET_MARKER in source:
        return source
    anchor = '    let resp = ui.interact(rect, id, Sense::click_and_drag());\n    crate::pointer_wrap::track(&resp);'
    if source.count(anchor) != 1:
        raise SystemExit("hot_number_at interaction anchor was not found exactly once")
    source = source.replace(anchor, anchor + r'''
    // EFFECTCRAFT_AM_EFFECT_VALUE_VERTICAL_SCRUB_V1
    // In AM effect parameters, require a deliberate press-hold before vertical scrubbing.
    // The classic Ae workspace retains its original horizontal hot-number behavior.
    let am_vertical_scrub = ui.ctx().data(|d| {
        d.get_temp::<bool>(egui::Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY")).unwrap_or(false)
    });
    let am_press_time_id = id.with("am-vertical-press-time");
    let am_last_pointer_id = id.with("am-vertical-last-pointer");
    if am_vertical_scrub {
        if resp.is_pointer_button_down_on() {
            let now = ui.input(|i| i.time);
            if ui.input(|i| i.pointer.button_pressed(egui::PointerButton::Primary))
                || ui.data(|d| d.get_temp::<f64>(am_press_time_id)).is_none()
            {
                ui.data_mut(|d| d.insert_temp(am_press_time_id, now));
            }
            if let Some(pos) = resp.interact_pointer_pos() {
                ui.data_mut(|d| d.insert_temp(am_last_pointer_id, pos));
            }
        } else {
            ui.data_mut(|d| {
                d.remove::<f64>(am_press_time_id);
                d.remove::<egui::Pos2>(am_last_pointer_id);
            });
        }
    }''', 1)
    source = source.replace(
        '    if resp.hovered() || resp.dragged() {\n        ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);\n    }',
        '''    if resp.hovered() || resp.dragged() {
        ui.ctx().set_cursor_icon(if am_vertical_scrub {
            egui::CursorIcon::ResizeVertical
        } else {
            egui::CursorIcon::ResizeHorizontal
        });
    }''',
        1,
    )
    old = '''    if resp.dragged() {
        let dx = resp.drag_delta().x as f64;
        let mult = ui.input(|i| {
            if i.modifiers.shift {
                10.0
            } else if i.modifiers.command && !proportional_scrub(i.modifiers) {
                0.1
            } else {
                1.0
            }
        });
        let nv = (value + dx * speed * mult).clamp(range.0, range.1);
        if (nv - value).abs() > f64::EPSILON {
            out = Some(nv);
        }
    }'''
    new = '''    if resp.dragged() {
        let mult = ui.input(|i| {
            if i.modifiers.shift {
                10.0
            } else if i.modifiers.command && !proportional_scrub(i.modifiers) {
                0.1
            } else {
                1.0
            }
        });
        let delta = if am_vertical_scrub {
            let started = ui.data(|d| d.get_temp::<f64>(am_press_time_id)).unwrap_or_else(|| ui.input(|i| i.time));
            if ui.input(|i| i.time) - started >= 0.28 {
                if let Some(current) = resp.interact_pointer_pos() {
                    let previous = ui.data(|d| d.get_temp::<egui::Pos2>(am_last_pointer_id));
                    ui.data_mut(|d| d.insert_temp(am_last_pointer_id, current));
                    previous.map(|last| (last.y - current.y) as f64).unwrap_or(0.0)
                } else {
                    0.0
                }
            } else {
                if let Some(current) = resp.interact_pointer_pos() {
                    ui.data_mut(|d| d.insert_temp(am_last_pointer_id, current));
                }
                0.0
            }
        } else {
            resp.drag_delta().x as f64
        };
        let nv = (value + delta * speed * mult).clamp(range.0, range.1);
        if (nv - value).abs() > f64::EPSILON {
            out = Some(nv);
        }
    }'''
    if source.count(old) != 1:
        raise SystemExit("hot_number_at drag block was not found exactly once")
    source = source.replace(old, new, 1)
    return source

def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    editor = root / "crates/ui-egui/src/am_editor.rs"
    widgets = root / "crates/ui-egui/src/widgets.rs"
    if not editor.is_file() or not widgets.is_file():
        raise SystemExit("AM editor or shared widgets source not found")
    editor_source = replace_effect_view(editor.read_text(encoding="utf-8"))
    widgets_source = patch_vertical_scrub(widgets.read_text(encoding="utf-8"))
    editor.write_text(editor_source, encoding="utf-8")
    widgets.write_text(widgets_source, encoding="utf-8")
    print("Installed reverse AM effect/parameter slide and long-press vertical value scrubbing.")

if __name__ == "__main__":
    main()
