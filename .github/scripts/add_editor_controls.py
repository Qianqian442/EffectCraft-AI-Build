#!/usr/bin/env python3
"""Add Chinese-first Android editor controls: Puppet Pin, Project grouping and single-item keyframes."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_EDITOR_CONTROLS_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch_language(root: Path) -> None:
    path = root / "crates/ui-egui/src/i18n.rs"
    source = path.read_text(encoding="utf-8")
    old = '        "system" => system_language(),'
    new = '''        "system" => {
            // EffectCraft's Android build is delivered as a Chinese-first editor.
            // A user-selected language still takes precedence over this first-run default.
            #[cfg(target_os = "android")]
            { "zh-hans" }
            #[cfg(not(target_os = "android"))]
            { system_language() }
        },'''
    source = replace_once(source, old, new, "Android Simplified Chinese default")
    path.write_text(source, encoding="utf-8")


def patch_translations(root: Path) -> None:
    path = root / "crates/ui-egui/src/i18n/ui.rs"
    source = path.read_text(encoding="utf-8")
    rows = {
        "SIMPLIFIED_CHINESE": [
            '    ("Group", "编组"),',
            '    ("Ungroup", "解除编组"),',
            '    ("Puppet Position Pin Tool", "木偶控点工具"),',
            '    ("Add Keyframe to Selected Footage", "为选中的素材添加关键帧"),',
            '    ("Select one footage item placed in the active composition", "请先选择一个已放入当前合成的素材"),',
        ],
        "TRADITIONAL_CHINESE": [
            '    ("Group", "編組"),',
            '    ("Ungroup", "解除編組"),',
            '    ("Puppet Position Pin Tool", "木偶定位點工具"),',
            '    ("Add Keyframe to Selected Footage", "為選取的素材新增關鍵影格"),',
            '    ("Select one footage item placed in the active composition", "請先選取一個已放入目前合成的素材"),',
        ],
    }
    for table, entries in rows.items():
        start_marker = f"const {table}:"
        start = source.find(start_marker)
        if start < 0:
            raise SystemExit(f"Translation table {table} was not found")
        end = source.find("\n];", start)
        if end < 0:
            raise SystemExit(f"Translation table {table} has no terminator")
        table_text = source[start:end]
        for entry in entries:
            english = entry.split('"')[1]
            if f'("{english}"' not in table_text:
                source = source[:end] + "\n" + entry + source[end:]
                end += len(entry) + 1
                table_text = source[start:end]
    path.write_text(source, encoding="utf-8")


def patch_header(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return
    source = replace_once(
        source,
        '    let x = brand_and_home(app, ui, &p, x, cy);\n    let x = tool_slots(app, ui, &p, x, cy);',
        '    let x = brand_and_home(app, ui, &p, x, cy);\n    let x = quick_puppet_pin(app, ui, &p, x, cy);\n    let x = tool_slots(app, ui, &p, x, cy);',
        "Puppet Pin quick-access placement",
    )
    anchor = '    x + 6.0\n}\n\n/// The tool slots'
    addition = '''    x + 6.0
}

/// EFFECTCRAFT_ANDROID_EDITOR_CONTROLS_V1
/// One-tap Puppet Position Pin access beside Home; it selects the existing, fully functional
/// Puppet tool and therefore reuses its mesh, pin placement, motion recording and follow-through.
fn quick_puppet_pin(app: &mut EffectcraftApp, ui: &mut egui::Ui, _p: &egui::Painter, x: f32, cy: f32) -> f32 {
    let t = app.tokens;
    let r = Rect::from_min_size(pos2(x, cy - 13.0), vec2(26.0, 26.0));
    let active = app.ui.tool.puppet_kind().is_some();
    let response = widgets::icon_button(ui, r, Icon::Puppet, active, &t, egui::Id::unique("quick-puppet-pin"))
        .on_hover_text(tr("Puppet Position Pin Tool"));
    app.auto.add_response("tools.quickPuppetPin", &response, "Puppet Position Pin Tool");
    if response.clicked() {
        app.ui.tool = Tool::Puppet;
    }
    x + 30.0
}

/// The tool slots'''
    source = replace_once(source, anchor, addition, "Puppet Pin quick-access helper")
    path.write_text(source, encoding="utf-8")


def patch_project(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    source = replace_once(
        source,
        "use effectcraft_engine::project::{Item, ItemId, ItemKind};",
        "use effectcraft_engine::project::{Item, ItemId, ItemKind, LayerId, LayerSource};",
        "Project panel layer-source imports",
    )

    helpers = r'''
// EFFECTCRAFT_ANDROID_EDITOR_CONTROLS_V1
fn group_selection_mode_id() -> egui::Id {
    egui::Id::unique("project-group-selection-mode")
}

fn long_press_consumed_id(item: ItemId) -> egui::Id {
    egui::Id::unique(("project-group-long-press", item.0))
}

fn group_selection_mode(ctx: &egui::Context) -> bool {
    ctx.data(|data| data.get_temp::<bool>(group_selection_mode_id())).unwrap_or(false)
}

fn group_action_label(app: &EffectcraftApp, ctx: &egui::Context) -> Option<&'static str> {
    if !group_selection_mode(ctx) || app.session.state.project_selection.is_empty() {
        return None;
    }
    let selected = &app.session.state.project_selection;
    if selected.len() == 1 && app.session.project.item(selected[0]).is_some_and(|item| item.is_folder()) {
        return Some("Ungroup");
    }
    selected
        .iter()
        .all(|id| app.session.project.item(*id).is_some_and(|item| !item.is_folder()))
        .then_some("Group")
}

/// Group the checked Project items into a new folder, or move a folder's direct children out
/// before deleting that now-empty folder. Each operation uses the engine's undoable commands.
fn run_project_group_action(app: &mut EffectcraftApp, ctx: &egui::Context, action: &str) -> Result<(), String> {
    let selected = app.session.state.project_selection.clone();
    if action == "Ungroup" {
        let folder_id = *selected.first().ok_or("请先长按一个编组")?;
        let folder = app.session.project.item(folder_id).filter(|item| item.is_folder()).ok_or("请选择一个编组")?;
        let parent = folder.parent.map(|id| id.0);
        let children: Vec<u64> = app.session.project.items.values()
            .filter(|item| item.parent == Some(folder_id))
            .map(|item| item.id.0)
            .collect();
        if !children.is_empty() {
            crate::menus::invoke(app, ctx, "project.move", serde_json::json!({
                "items": children,
                "folder": parent
            }))?;
        }
        crate::menus::invoke(app, ctx, "project.delete", serde_json::json!({"items": [folder_id.0]}))?;
    } else {
        if selected.is_empty() || selected.iter().any(|id| app.session.project.item(*id).is_none_or(|item| item.is_folder())) {
            return Err("请选择一个或多个素材进行编组".into());
        }
        let first = app.session.project.item(selected[0]).ok_or("素材已不存在")?;
        let parent = first.parent.map(|id| id.0);
        let name = format!("{} 组", first.name);
        let created = crate::menus::invoke(app, ctx, "project.newFolder", serde_json::json!({
            "name": name,
            "parent": parent
        }))?;
        let folder_id = created.get("item").and_then(serde_json::Value::as_u64).ok_or("无法创建编组文件夹")?;
        if let Err(error) = crate::menus::invoke(app, ctx, "project.move", serde_json::json!({
            "items": selected.iter().map(|id| id.0).collect::<Vec<_>>(),
            "folder": folder_id
        })) {
            let _ = crate::menus::invoke(app, ctx, "project.delete", serde_json::json!({"items": [folder_id]}));
            return Err(error);
        }
    }
    crate::menus::invoke(app, ctx, "project.select", serde_json::json!({"items": []}))?;
    ctx.data_mut(|data| data.remove::<bool>(group_selection_mode_id()));
    Ok(())
}

/// Resolve exactly one selected Project item to exactly one corresponding layer in the active
/// composition. If several instances use the footage, an explicitly selected matching layer wins.
fn project_keyframe_target(app: &EffectcraftApp) -> Option<(effectcraft_engine::project::ItemId, LayerId)> {
    let selected = app.session.state.project_selection.as_slice();
    if selected.len() != 1 {
        return None;
    }
    let item_id = selected[0];
    let comp_id = app.session.active_comp_id()?;
    let comp = app.session.project.comp(comp_id)?;
    let matching: Vec<LayerId> = comp.layers.iter().filter_map(|layer| {
        let uses_item = match &layer.source {
            LayerSource::Footage { item } | LayerSource::Solid { item } | LayerSource::Comp { item } | LayerSource::Model { item } => *item == item_id,
            _ => false,
        };
        uses_item.then_some(layer.id)
    }).collect();
    let selected_matches: Vec<LayerId> = app.session.state.selected_layers.iter()
        .copied().filter(|id| matching.contains(id)).collect();
    let layer = if selected_matches.len() == 1 {
        selected_matches[0]
    } else if matching.len() == 1 {
        matching[0]
    } else {
        return None;
    };
    Some((comp_id, layer))
}

'''
    source = replace_once(source, "fn details_header(", helpers + "fn details_header(", "Project grouping/keyframe helpers")

    header_anchor = '''    let t = app.tokens;
    let sel = app.session.state.project_selection.first().copied();'''
    header_new = '''    let t = app.tokens;
    if let Some(action) = group_action_label(app, ctx) {
        let button_rect = Rect::from_min_size(pos2(head.max.x - 82.0, head.min.y + 7.0), vec2(74.0, 23.0));
        let response = ui.put(button_rect, egui::Button::new(crate::i18n::tr(action)).small());
        app.auto.add_response("project.groupAction", &response, action);
        if response.clicked() {
            if let Err(error) = run_project_group_action(app, ctx, action) {
                app.ui.status = error;
            }
        }
    }
    let sel = app.session.state.project_selection.first().copied();'''
    source = replace_once(source, header_anchor, header_new, "Project panel grouping action button")

    row_anchor = '''        let selected = app.session.state.project_selection.contains(id);
        lp.rect_filled('''
    row_new = '''        let mut selected = app.session.state.project_selection.contains(id);
        lp.rect_filled('''
    source = replace_once(source, row_anchor, row_new, "Project row selection state")

    interaction_anchor = '''        let mut resp = ui.interact(r.intersect(list), row_id(*id), Sense::click_and_drag());
        app.auto.add(&format!("project.item.{}", id.0), r, &it.name);'''
    interaction_new = '''        let mut resp = ui.interact(r.intersect(list), row_id(*id), Sense::click_and_drag());
        let held_for = resp.is_pointer_button_down_on()
            .then(|| ui.input(|i| i.pointer.press_start_time().map(|start| i.time - start)))
            .flatten();
        if let Some(seconds) = held_for {
            if seconds < 0.45 {
                ctx.request_repaint_after(std::time::Duration::from_secs_f64(0.45 - seconds));
            } else if !group_selection_mode(&ctx) {
                // Long-press checks the first item and turns on the separate grouping mode.
                selected = true;
                app.session.state.project_selection = vec![*id];
                ctx.data_mut(|data| {
                    data.insert_temp(group_selection_mode_id(), true);
                    data.insert_temp(long_press_consumed_id(*id), true);
                });
            }
        }
        let grouping = group_selection_mode(&ctx);
        if grouping {
            let check = Rect::from_center_size(pos2(r.min.x + 12.0 + 14.0 * *depth as f32, r.center().y), vec2(12.0, 12.0));
            lp.rect_filled(check, 2.0, if selected { t.accent } else { t.panel_bg });
            lp.rect_stroke(check, 2.0, Stroke::new(1.0, if selected { t.accent } else { t.field_border }), egui::StrokeKind::Inside);
            if selected {
                lp.line_segment([check.min + vec2(2.5, 6.0), check.min + vec2(5.0, 8.5)], Stroke::new(1.5, Color32::WHITE));
                lp.line_segment([check.min + vec2(5.0, 8.5), check.min + vec2(9.5, 3.0)], Stroke::new(1.5, Color32::WHITE));
            }
        }
        app.auto.add(&format!("project.item.{}", id.0), r, &it.name);'''
    source = replace_once(source, interaction_anchor, interaction_new, "Project long-press multi-selection and checkboxes")

    click_anchor = '''        let resp = resp.union(nresp);
        if resp.clicked() {
            select_click(app, ui, &ctx, *id, &rows);
        }'''
    click_new = '''        let resp = resp.union(nresp);
        let long_press_consumed = ctx.data_mut(|data| data.remove::<bool>(long_press_consumed_id(*id))).unwrap_or(false);
        if resp.clicked() && !long_press_consumed {
            if group_selection_mode(&ctx) {
                if app.session.state.project_selection.contains(id) {
                    app.session.state.project_selection.retain(|selected_id| selected_id != id);
                } else {
                    app.session.state.project_selection.push(*id);
                }
            } else {
                select_click(app, ui, &ctx, *id, &rows);
            }
        } else if ctx.input(|i| i.pointer.button_released(egui::PointerButton::Primary)) {
            ctx.data_mut(|data| data.remove::<bool>(long_press_consumed_id(*id)));
        }'''
    source = replace_once(source, click_anchor, click_new, "Project long-press click handling")

    footer_anchor = '''    let depth = app.session.project.settings.bit_depth.label();
    let dr = Rect::from_min_size(pos2(x + 4.0, foot.min.y + 5.0), vec2(48.0, 18.0));'''
    footer_new = '''    let keyframe_target = project_keyframe_target(app);
    let keyframe_rect = Rect::from_min_size(pos2(x + 1.0, foot.min.y + 3.0), vec2(22.0, 22.0));
    let keyframe_response = ui.add_enabled_ui(keyframe_target.is_some(), |ui| {
        widgets::icon_button(ui, keyframe_rect, Icon::Keyframe, false, &t, egui::Id::unique("project-add-keyframe"))
            .on_hover_text(crate::i18n::tr("Add Keyframe to Selected Footage"))
    }).inner;
    app.auto.add_response("project.addKeyframe", &keyframe_response, "Add Keyframe to Selected Footage");
    if keyframe_response.clicked()
        && let Some((comp_id, layer_id)) = keyframe_target
        && let Err(error) = crate::menus::invoke(app, &ctx, "prop.addKey", serde_json::json!({
            "comp": comp_id.0,
            "layer": layer_id.0,
            "path": "transform/position"
        }))
    {
        app.ui.status = error;
    }
    x += 26.0;
    let depth = app.session.project.settings.bit_depth.label();
    let dr = Rect::from_min_size(pos2(x + 4.0, foot.min.y + 5.0), vec2(48.0, 18.0));'''
    source = replace_once(source, footer_anchor, footer_new, "Single-item keyframe footer button")

    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    patch_language(root)
    patch_translations(root)
    patch_header(root)
    patch_project(root)
    print("Android defaults to the Simplified Chinese interface.")
    print("Added one-tap Puppet Position Pin access.")
    print("Added long-press Project grouping / ungrouping with check marks.")
    print("Added a single-selected-footage Position keyframe button.")


if __name__ == "__main__":
    main()
