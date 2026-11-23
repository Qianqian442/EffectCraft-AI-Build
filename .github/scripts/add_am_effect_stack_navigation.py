#!/usr/bin/env python3
"""Give the AM Move & Transform sheet a separate scrollable effect stack and parameter view."""
from __future__ import annotations
import os
from pathlib import Path

MARKER = "EFFECTCRAFT_AM_EFFECT_STACK_NAV_V1"

def replace_once(source: str, old: str, new: str, label: str) -> str:
    if MARKER in source and new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)

def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    editor = root / "crates/ui-egui/src/am_editor.rs"
    controls = root / "crates/ui-egui/src/panels/effect_controls/panel.rs"
    if not editor.is_file() or not controls.is_file():
        raise SystemExit("AM editor or Effect Controls source not found")

    src = editor.read_text(encoding="utf-8")
    if MARKER not in src:
        old = '''    if section == "effects" {
        let back = ui.put(Rect::from_min_size(pos2(center.min.x + 5.0, center.min.y + 3.0), vec2(94.0, 28.0)), egui::Button::new("‹ 返回变换"));
        app.auto.add_response("am.motion.effects.back", &back, "返回移动与变换");
        if back.clicked() { section = "transform".into(); ctx.data_mut(|d| d.insert_temp(Id::new(AM_MOTION_TAB_ID), section.clone())); }
        let body = Rect::from_min_max(pos2(center.min.x + 3.0, center.min.y + 36.0), center.max);
        ctx.data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true));
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
        crate::panels::show(app, &mut child, PanelKind::EffectControls, body);
        ctx.data_mut(|d| d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1")));
        let add = ui.put(Rect::from_min_size(pos2(footer.max.x - 105.0, footer.min.y + 5.0), vec2(98.0, 32.0)), egui::Button::new("＋ 添加效果"));
        app.auto.add_response("am.motion.effects.add", &add, "打开效果浏览器");
        if add.clicked() { am_open_effect_browser(&ctx, Some(layer_id)); }
        return;
    }'''
        new = '''    // EFFECTCRAFT_AM_EFFECT_STACK_NAV_V1
    if section == "effects" {
        let back = ui.put(Rect::from_min_size(pos2(center.min.x + 5.0, center.min.y + 3.0), vec2(94.0, 28.0)), egui::Button::new("‹ 返回变换"));
        app.auto.add_response("am.motion.effects.back", &back, "返回移动与变换");
        if back.clicked() { section = "transform".into(); ctx.data_mut(|d| d.insert_temp(Id::new(AM_MOTION_TAB_ID), section.clone())); }
        let body = Rect::from_min_max(pos2(center.min.x + 3.0, center.min.y + 36.0), center.max);
        let items: Vec<(u64, String)> = app.session.active_comp()
            .and_then(|comp| comp.layers.iter().find(|layer| layer.id.0 == layer_id))
            .and_then(|layer| layer.effects())
            .map(|stack| stack.groups().filter_map(|g| {
                if let effectcraft_engine::project::GroupKind::Effect { effect } = &g.kind {
                    Some((g.uid, crate::i18n::effects::group(effect, &g.name)))
                } else { None }
            }).collect())
            .unwrap_or_default();
        let mut list = ui.new_child(egui::UiBuilder::new().max_rect(body));
        egui::ScrollArea::vertical().id_salt("am-effect-stack-list").auto_shrink([false, false]).show(&mut list, |list_ui| {
            if items.is_empty() {
                list_ui.label("尚未添加效果");
            }
            for (uid, name) in &items {
                let response = list_ui.add_sized([body.width() - 8.0, 42.0], egui::Button::new(name));
                app.auto.add_response(&format!("am.motion.effect.select.{uid}"), &response, name);
                if response.clicked() {
                    ctx.data_mut(|d| {
                        d.insert_temp(Id::new("EFFECTCRAFT_AM_SELECTED_EFFECT_ID"), *uid);
                        d.insert_temp(Id::new(AM_MOTION_TAB_ID), "effect_params".to_string());
                    });
                    section = "effect_params".into();
                }
            }
        });
        let add = ui.put(Rect::from_min_size(pos2(footer.max.x - 105.0, footer.min.y + 5.0), vec2(98.0, 32.0)), egui::Button::new("＋ 添加效果"));
        app.auto.add_response("am.motion.effects.add", &add, "打开效果浏览器");
        if add.clicked() { am_open_effect_browser(&ctx, Some(layer_id)); }
        return;
    }
    if section == "effect_params" {
        let back = ui.put(Rect::from_min_size(pos2(center.min.x + 5.0, center.min.y + 3.0), vec2(118.0, 28.0)), egui::Button::new("‹ 返回移动与变换"));
        app.auto.add_response("am.motion.effect_params.back", &back, "关闭参数并返回移动与变换");
        if back.clicked() {
            section = "transform".into();
            ctx.data_mut(|d| {
                d.insert_temp(Id::new(AM_MOTION_TAB_ID), section.clone());
                d.remove::<u64>(Id::new("EFFECTCRAFT_AM_SELECTED_EFFECT_ID"));
            });
            return;
        }
        let body = Rect::from_min_max(pos2(center.min.x + 3.0, center.min.y + 36.0), center.max);
        ctx.data_mut(|d| {
            d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true);
            d.insert_temp(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY"), true);
        });
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
        crate::panels::show(app, &mut child, PanelKind::EffectControls, body);
        ctx.data_mut(|d| {
            d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"));
            d.remove::<bool>(Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY"));
        });
        return;
    }'''
        src = replace_once(src, old, new, "replace old combined effects view with stack and parameter views")
        # The bottom-right Effects action opens the stack, not the browser directly.
        old_click = 'if effect.clicked(){section="effects".into();ctx.data_mut(|d|d.insert_temp(Id::new(AM_MOTION_TAB_ID),section));am_open_effect_browser(&ctx,Some(layer_id));}'
        new_click = 'if effect.clicked(){section="effects".into();ctx.data_mut(|d|d.insert_temp(Id::new(AM_MOTION_TAB_ID),section));}'
        src = replace_once(src, old_click, new_click, "route the Effects button to the effect stack")
        editor.write_text(src, encoding="utf-8")

    panel = controls.read_text(encoding="utf-8")
    old_fx = '    let fx: Vec<PropGroup> = layer.effects().map(|f| f.groups().cloned().collect()).unwrap_or_default();'
    new_fx = '''    let mut fx: Vec<PropGroup> = layer.effects().map(|f| f.groups().cloned().collect()).unwrap_or_default();
    // The AM parameter view displays only the effect selected from its stack. Ae's normal
    // Effect Controls view is unchanged because the filter is enabled only by the AM sheet.
    if ctx.data(|d| d.get_temp::<bool>(egui::Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY")).unwrap_or(false)) {
        if let Some(uid) = ctx.data(|d| d.get_temp::<u64>(egui::Id::new("EFFECTCRAFT_AM_SELECTED_EFFECT_ID"))) {
            fx.retain(|group| group.uid == uid);
        }
    }'''
    if new_fx not in panel:
        if panel.count(old_fx) != 1:
            raise SystemExit("Could not locate the Effect Controls effect stack")
        panel = panel.replace(old_fx, new_fx, 1)
        controls.write_text(panel, encoding="utf-8")
    print("Installed AM effect stack navigation and per-effect parameter filtering.")

if __name__ == "__main__":
    main()
