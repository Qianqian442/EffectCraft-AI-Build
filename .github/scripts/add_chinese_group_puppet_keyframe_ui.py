#!/usr/bin/env python3
"""Add the requested Chinese, Puppet quick-access, project grouping and single-item keyframe controls."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_default_language(root: Path) -> None:
    path = root / "crates/engine/src/settings/prefs/sections.rs"
    source = path.read_text(encoding="utf-8")
    old = '    language: String = "system".into(),'
    new = '    language: String = "zh-hans".into(),'
    path.write_text(replace_once(source, old, new, "Simplified Chinese default"), encoding="utf-8")

    # Existing installations may retain a saved "system" preference. On Android, that
    # fallback resolves to Simplified Chinese; explicit language choices remain untouched.
    language_path = root / "crates/ui-egui/src/i18n.rs"
    language_source = language_path.read_text(encoding="utf-8")
    old_system = '        "system" => system_language(),'
    new_system = '''        "system" => {
            #[cfg(target_os = "android")]
            { "zh-hans" }
            #[cfg(not(target_os = "android"))]
            { system_language() }
        },'''
    language_path.write_text(
        replace_once(language_source, old_system, new_system, "Android Simplified Chinese runtime default"),
        encoding="utf-8",
    )


def patch_project_commands(root: Path) -> None:
    path = root / "crates/engine/src/cmd/project_items.rs"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "use effectcraft_project::{ItemId, Project};",
        "use effectcraft_color::Label;\nuse effectcraft_project::{ItemId, ItemKind, Project};",
        "Project item grouping imports",
    )

    marker = "/// Grouping commands for the Project panel. All changes are one undoable edit.\n"
    if marker not in source:
        code = r'''
/// Group selected Project-panel items in a new folder. The group keeps their common parent
/// when they share one; otherwise the new group is placed at the project root.
fn group_items(s: &mut Session, p: &Value) -> Result<Value> {
    let cmd = "project.group";
    let mut ids = items_p(s, p, cmd)?;
    let mut unique = Vec::new();
    for id in ids.drain(..) {
        if !unique.contains(&id) {
            unique.push(id);
        }
    }
    if unique.len() < 2 {
        return Err(bad(cmd, "请至少选择两个素材进行编组"));
    }
    for id in &unique {
        let item = s.project.item(*id).ok_or_else(|| bad(cmd, format!("project item {} no longer exists", id.0)))?;
        if item.is_folder() {
            return Err(bad(cmd, "不能将文件夹加入新编组"));
        }
    }

    let first = s.project.item(unique[0]).ok_or_else(|| bad(cmd, "first project item no longer exists"))?;
    let label = first.label;
    let first_parent = first.parent;
    let parent = if unique.iter().all(|id| s.project.item(*id).is_some_and(|it| it.parent == first_parent)) {
        first_parent
    } else {
        None
    };
    let name = str_p(p, "name").map(str::trim).filter(|name| !name.is_empty()).unwrap_or("编组").to_string();

    let folder = s.edit("编组素材", None, |proj, st| {
        let unique_name = proj.numbered_item_name(&name, |_| false);
        let folder = proj.add_item(&unique_name, label, parent, ItemKind::Folder);
        for id in &unique {
            proj.item_mut(*id).ok_or_else(|| bad(cmd, format!("project item {} vanished", id.0)))?.parent = Some(folder);
        }
        st.project_selection = vec![folder];
        Ok(folder)
    })?;
    Ok(json!({"folder": folder.0, "items": unique.len()}))
}

/// Remove a group folder and move its direct children to the folder's former parent.
fn ungroup_item(s: &mut Session, p: &Value) -> Result<Value> {
    let cmd = "project.ungroup";
    let id = match p.get("item") {
        Some(value) => item_ref(s, value, cmd)?,
        None => *s.state.project_selection.first().ok_or_else(|| bad(cmd, "请先选择一个编组文件夹"))?,
    };
    let folder = s.project.item(id).ok_or_else(|| bad(cmd, "编组文件夹已不存在"))?;
    if !folder.is_folder() {
        return Err(bad(cmd, "所选项目不是编组文件夹"));
    }
    let parent = folder.parent;
    let children: Vec<ItemId> = s.project.items.values()
        .filter(|item| item.parent == Some(id))
        .map(|item| item.id)
        .collect();

    s.edit("解除编组", None, |proj, st| {
        for child in &children {
            proj.item_mut(*child).ok_or_else(|| bad(cmd, format!("group child {} vanished", child.0)))?.parent = parent;
        }
        proj.items.remove(&id);
        st.project_selection = children.clone();
        Ok(())
    })?;
    Ok(json!({"folder": id.0, "items": children.len()}))
}

'''
        source = replace_once(source, "pub fn specs() -> Vec<CommandSpec> {", marker + code + "pub fn specs() -> Vec<CommandSpec> {", "Project grouping commands")
    specs_anchor = '        cmd!("project.duplicate", "Duplicate Project Items", [], None, "{items?: [id|name] (default: selected)} → {items}", always, duplicate),'
    specs_replacement = (
        '        cmd!("project.group", "Group Project Items", [], None, "{items: [id,...], name?}", always, group_items),\n'
        '        cmd!("project.ungroup", "Ungroup Project Items", [], None, "{item?: id (default: selected folder)}", always, ungroup_item),\n'
        + specs_anchor
    )
    source = replace_once(source, specs_anchor, specs_replacement, "Project grouping command registration")
    path.write_text(source, encoding="utf-8")


def patch_puppet_quick_button(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    call_anchor = (
        "    let x = brand_and_home(app, ui, &p, x, cy);\n"
        "    let x = plugin_import_button(app, ui, x, cy);\n"
        "    let x = tool_slots(app, ui, &p, x, cy);"
    )
    call_replacement = (
        "    let x = brand_and_home(app, ui, &p, x, cy);\n"
        "    let x = plugin_import_button(app, ui, x, cy);\n"
        "    let x = puppet_quick_button(app, ui, x, cy);\n"
        "    let x = tool_slots(app, ui, &p, x, cy);"
    )
    source = replace_once(source, call_anchor, call_replacement, "Puppet quick button toolbar insertion")

    marker = "/// EFFECTCRAFT_ANDROID_PUPPET_QUICK_BUTTON_V1\n"
    if marker not in source:
        anchor = "/// The tool slots (with group separators after camera tools and pan-behind); returns the x after them.\n"
        helper = r'''/// EFFECTCRAFT_ANDROID_PUPPET_QUICK_BUTTON_V1
/// A dedicated top-left shortcut for the native Puppet Position Pin tool.
fn puppet_quick_button(app: &mut EffectcraftApp, ui: &mut egui::Ui, x: f32, cy: f32) -> f32 {
    let t = app.tokens;
    let rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(26.0, 26.0));
    let response = widgets::icon_button(
        ui,
        rect,
        Icon::Puppet,
        app.ui.tool == Tool::Puppet,
        &t,
        egui::Id::new("effectcraft-puppet-quick-button"),
    )
    .on_hover_text("木偶控点：单击添加控点，拖动控点可调整位置");
    app.auto.add_response("header.puppetQuick", &response, "木偶控点工具");
    widgets::focus_outline(ui, &response, &t);
    if response.clicked() {
        app.ui.tool = Tool::Puppet;
    }
    x + 30.0
}

'''
        source = replace_once(source, anchor, helper + anchor, "Puppet quick button helper")
    path.write_text(source, encoding="utf-8")


def patch_project_panel(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")

    state_anchor = "const ROW_H: f32 = 19.0;\n"
    state_code = r'''
#[derive(Clone)]
struct ProjectGroupMode {
    selected: Vec<ItemId>,
    ungroup: Option<ItemId>,
}

#[derive(Clone, Copy)]
struct ProjectRowLongPress {
    item: ItemId,
    started: f64,
    triggered: bool,
}

fn project_group_mode_id() -> egui::Id {
    egui::Id::new("effectcraft-project-group-mode")
}

fn project_row_long_press_id() -> egui::Id {
    egui::Id::new("effectcraft-project-row-long-press")
}
'''
    source = replace_once(source, state_anchor, state_anchor + state_code, "Project grouping UI state")

    action_anchor = '    let mut actions: Vec<(String, serde_json::Value)> = vec![];\n'
    action_ui = r'''    let group_mode: Option<ProjectGroupMode> = ctx.data(|data| data.get_temp(project_group_mode_id()));
    if let Some(mode) = group_mode {
        let label = if mode.ungroup.is_some() { "解除编组" } else { "编组" };
        let enabled = mode.ungroup.is_some() || mode.selected.len() >= 2;
        let button_rect = Rect::from_min_size(pos2(rect.max.x - 92.0, rect.min.y + 6.0), vec2(84.0, 26.0));
        let response = ui.interact(
            button_rect,
            egui::Id::new("effectcraft-project-group-action"),
            if enabled { Sense::click() } else { Sense::hover() },
        );
        p.rect_filled(button_rect, 4.0, if enabled { t.accent } else { t.row });
        p.rect_stroke(button_rect, 4.0, Stroke::new(1.0, if enabled { t.accent } else { t.separator }), egui::StrokeKind::Inside);
        p.text(
            button_rect.center(),
            Align2::CENTER_CENTER,
            label,
            Tokens::semibold(12.0),
            if enabled { Color32::WHITE } else { t.text_dim },
        );
        app.auto.add("project.groupAction", button_rect, label);
        if response.clicked() && enabled {
            if let Some(folder) = mode.ungroup {
                actions.push(("project.ungroup".into(), json!({"item": folder.0})));
            } else {
                actions.push(("project.group".into(), json!({"items": mode.selected.iter().map(|id| id.0).collect::<Vec<_>>()})));
            }
        }
    }
'''
    source = replace_once(source, action_anchor, action_anchor + action_ui, "Project grouping action button")

    row_anchor = '        let mut resp = ui.interact(r.intersect(list), row_id(*id), Sense::click_and_drag());\n'
    long_press_code = r'''        // A 550 ms press starts group selection for files, or ungroup mode for a folder.
        let now = ctx.input(|input| input.time);
        let pointer_pressed = ctx.input(|input| input.pointer.button_pressed(egui::PointerButton::Primary));
        let pointer_down = ctx.input(|input| input.pointer.button_down(egui::PointerButton::Primary));
        let mut row_press: Option<ProjectRowLongPress> = ctx.data(|data| data.get_temp(project_row_long_press_id()));
        if pointer_pressed && resp.contains_pointer() {
            let new_press = ProjectRowLongPress { item: *id, started: now, triggered: false };
            row_press = Some(new_press);
            ctx.data_mut(|data| data.insert_temp(project_row_long_press_id(), new_press));
        }
        if resp.drag_started() {
            ctx.data_mut(|data| data.remove::<ProjectRowLongPress>(project_row_long_press_id()));
            row_press = None;
        } else if pointer_down && resp.contains_pointer()
            && let Some(mut held) = row_press.filter(|held| held.item == *id)
        {
            if !held.triggered && now - held.started >= 0.55 {
                let mode = if it.is_folder() {
                    ProjectGroupMode { selected: Vec::new(), ungroup: Some(*id) }
                } else {
                    ProjectGroupMode { selected: vec![*id], ungroup: None }
                };
                ctx.data_mut(|data| data.insert_temp(project_group_mode_id(), mode));
                app.session.state.project_selection = vec![*id];
                ctx.request_repaint();
                held.triggered = true;
                row_press = Some(held);
                ctx.data_mut(|data| data.insert_temp(project_row_long_press_id(), held));
            } else if !held.triggered {
                ctx.request_repaint_after(std::time::Duration::from_millis(50));
            }
        }
        let long_press_consumed = row_press.is_some_and(|held| held.item == *id && held.triggered);
'''
    source = replace_once(source, row_anchor, row_anchor + long_press_code, "Project row long-press handling")

    icon_anchor = '        icons::paint(&lp, Rect::from_center_size(pos2(x0 + 18.0, r.center().y), vec2(14.0, 14.0)), item_icon(it), t.text_dim);\n'
    check_code = r'''        let grouping: Option<ProjectGroupMode> = ctx.data(|data| data.get_temp(project_group_mode_id()));
        if grouping.as_ref().is_some_and(|mode| mode.selected.contains(id)) {
            let check = Rect::from_min_size(pos2(x0 - 2.0, r.center().y - 6.0), vec2(12.0, 12.0));
            lp.rect_filled(check, 2.0, t.accent);
            lp.line_segment([pos2(check.min.x + 2.5, check.center().y), pos2(check.min.x + 5.0, check.max.y - 2.5)], Stroke::new(1.5, Color32::WHITE));
            lp.line_segment([pos2(check.min.x + 5.0, check.max.y - 2.5), pos2(check.max.x - 2.0, check.min.y + 2.5)], Stroke::new(1.5, Color32::WHITE));
        }
'''
    source = replace_once(source, icon_anchor, check_code + icon_anchor, "Project grouping checkmarks")

    click_anchor = '''        if resp.clicked() {
            select_click(app, ui, &ctx, *id, &rows);
        }
'''
    click_replacement = r'''        if resp.clicked() && !long_press_consumed {
            let mut grouping: Option<ProjectGroupMode> = ctx.data(|data| data.get_temp(project_group_mode_id()));
            if let Some(mut mode) = grouping.take() {
                if mode.ungroup.is_none() && !it.is_folder() {
                    if let Some(index) = mode.selected.iter().position(|selected| selected == id) {
                        mode.selected.remove(index);
                    } else {
                        mode.selected.push(*id);
                    }
                    app.session.state.project_selection = mode.selected.clone();
                    ctx.data_mut(|data| data.insert_temp(project_group_mode_id(), mode));
                    ctx.request_repaint();
                }
            } else {
                select_click(app, ui, &ctx, *id, &rows);
            }
        }
'''
    source = replace_once(source, click_anchor, click_replacement, "Project grouping row selection")

    release_anchor = '        crate::widgets::context_menu(&resp, |ui| item_menu(app, ui, &ctx, it, *id, selected, &mut actions));\n'
    release_code = r'''        if ctx.input(|input| input.pointer.button_released(egui::PointerButton::Primary))
            && row_press.is_some_and(|held| held.item == *id)
        {
            ctx.data_mut(|data| data.remove::<ProjectRowLongPress>(project_row_long_press_id()));
        }
'''
    source = replace_once(source, release_anchor, release_anchor + release_code, "Project long-press release cleanup")

    # Keep the action visible if an engine operation fails; dismiss it only after success.
    action_loop = '''    for (id, params) in actions {
        if let Err(e) = crate::menus::invoke(app, &ctx, &id, params) {
            app.ui.status = e;
        }
    }
'''
    action_loop_new = '''    for (id, params) in actions {
        let is_group_action = matches!(id.as_str(), "project.group" | "project.ungroup");
        if let Err(e) = crate::menus::invoke(app, &ctx, &id, params) {
            app.ui.status = e;
        } else if is_group_action {
            ctx.data_mut(|data| data.remove::<ProjectGroupMode>(project_group_mode_id()));
        }
    }
'''
    source = replace_once(source, action_loop, action_loop_new, "Project group action success cleanup")
    path.write_text(source, encoding="utf-8")


def patch_timeline_keyframe_button(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "fn footer_bar(app: &mut EffectcraftApp, ui: &mut egui::Ui, g: &Rw) -> Rect {",
        "fn footer_bar(app: &mut EffectcraftApp, ui: &mut egui::Ui, g: &mut Rw) -> Rect {",
        "Single-item keyframe footer mutability",
    )
    anchor = '    let tgl = Rect::from_min_size(pos2(footer.min.x + 10.0, footer.min.y + 3.0), vec2(150.0, 18.0));\n'
    keyframe_code = r'''    // The keyframe control is active only for one Project-panel asset and its one matching
    // selected layer. Selected properties on that layer are keyed; with none selected, Position
    // receives the key at the current composition time. No other layer can be modified.
    let project_item = (app.session.state.project_selection.len() == 1).then(|| app.session.state.project_selection[0]);
    let selected_layer = project_item.and_then(|item| {
        // Prefer the one explicitly selected matching layer; otherwise auto-target only when the
        // asset appears exactly once in the active composition.
        let selected_match = match app.session.state.selected_layers.as_slice() {
            [layer] => g.tl.comp.layer(*layer).filter(|layer| layer.source.item() == Some(item)).map(|layer| layer.id),
            _ => None,
        };
        selected_match.or_else(|| {
            let mut matches = g.tl.comp.layers.iter().filter(|layer| layer.source.item() == Some(item));
            let first = matches.next()?;
            if matches.next().is_none() { Some(first.id) } else { None }
        })
    });
    let keyframe_enabled = project_item.is_some() && selected_layer.is_some();
    let keyframe_rect = Rect::from_min_size(pos2(footer.min.x + 8.0, footer.min.y + 2.0), vec2(24.0, 22.0));
    let keyframe_hint = if keyframe_enabled {
        "添加关键帧（仅作用于当前单个素材）"
    } else {
        "请先在左侧项目面板选中一个素材；若素材在当前合成中出现多次，请在时间轴中选中其中一个对应图层"
    };
    let keyframe_response = ui.add_enabled_ui(keyframe_enabled, |ui| {
        widgets::icon_button(
            ui,
            keyframe_rect,
            Icon::Keyframe,
            false,
            &t,
            egui::Id::new("effectcraft-single-item-keyframe"),
        )
    }).inner.on_hover_text(keyframe_hint);
    app.auto.add_response("timeline.addKeyframe", &keyframe_response, "添加关键帧");
    if keyframe_response.clicked() && keyframe_enabled {
        if let (Some(_item), Some(layer_id)) = (project_item, selected_layer) {
            let mut properties: Vec<u64> = app.session.state.selected_props.iter()
                .filter_map(|(selected, property)| (*selected == layer_id).then_some(*property))
                .collect();
            properties.sort_unstable();
            properties.dedup();
            if properties.is_empty()
                && let Some(position) = g.tl.comp.layer(layer_id)
                    .and_then(|layer| layer.props.group("transform"))
                    .and_then(|transform| transform.get("position"))
            {
                properties.push(position.uid);
            }
            if properties.is_empty() {
                app.ui.status = "当前素材没有可添加关键帧的属性。".into();
            } else {
                for property in properties {
                    g.tl.actions.push(("prop.addKey".into(), json!({"layer": layer_id.0, "prop": property})));
                }
            }
        }
    }
'''
    if "effectcraft-single-item-keyframe" not in source:
        source = replace_once(source, anchor, keyframe_code + anchor, "Single-item keyframe button")
    source = replace_once(
        source,
        'let tgl = Rect::from_min_size(pos2(footer.min.x + 10.0, footer.min.y + 3.0), vec2(150.0, 18.0));',
        'let tgl = Rect::from_min_size(pos2(footer.min.x + 38.0, footer.min.y + 3.0), vec2(150.0, 18.0));',
        "Timeline footer spacing",
    )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_default_language(root)
    patch_project_commands(root)
    patch_puppet_quick_button(root)
    patch_project_panel(root)
    patch_timeline_keyframe_button(root)
    print("Default interface language set to Simplified Chinese.")
    print("Added one-tap access to the original native Puppet Position Pin tool.")
    print("Added long-press project grouping and folder ungrouping.")
    print("Added a keyframe button restricted to one selected project item and its matching layer.")


if __name__ == "__main__":
    main()
