#!/usr/bin/env python3
"""Chinese-first EffectCraft UI, Puppet shortcut, Project grouping and single-asset keyframes."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)


def patch_chinese_default(root: Path) -> None:
    path = root / "crates/ui-egui/src/app.rs"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "    pub fn new(session: Session) -> Self {\n",
        '    pub fn new(mut session: Session) -> Self {\n'
        '        // Android defaults to Simplified Chinese unless the user explicitly chose a language.\n'
        '        if session.prefs.general.language == "system" {\n'
        '            session.prefs.general.language = "zh-hans".to_string();\n'
        '        }\n',
        "Chinese-first Android language default",
    )
    path.write_text(source, encoding="utf-8")


def patch_header(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    old = (
        "    p.line_segment([pos2(x, cy - 10.0), pos2(x, cy + 10.0)], Stroke::new(1.0, t.separator));\n"
        "    x + 6.0\n"
    )
    new = (
        "    p.line_segment([pos2(x, cy - 10.0), pos2(x, cy + 10.0)], Stroke::new(1.0, t.separator));\n"
        "    x += 6.0;\n"
        "    // Dedicated Puppet Position Pin shortcut; the existing five-tool flyout remains available.\n"
        "    let puppet_rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(26.0, 26.0));\n"
        "    let puppet_response = widgets::icon_button(\n"
        "        ui, puppet_rect, Icon::Puppet, app.ui.tool.puppet_kind().is_some(), &t,\n"
        '        egui::Id::new("effectcraft-top-left-puppet"),\n'
        "    ).on_hover_text(tr(\"Puppet Pin Tool\"));\n"
        '    app.auto.add_response("tools.puppetPin", &puppet_response, "Puppet Pin Tool");\n'
        "    if puppet_response.clicked() {\n"
        "        app.ui.tool = Tool::Puppet;\n"
        "    }\n"
        "    x + 32.0\n"
    )
    source = replace_once(source, old, new, "Top-left Puppet tool button")
    path.write_text(source, encoding="utf-8")


def patch_project_engine(root: Path) -> None:
    path = root / "crates/engine/src/cmd/project_items.rs"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "use effectcraft_project::{ItemId, Project};\n",
        "use effectcraft_project::{ItemId, ItemKind, Project};\n",
        "Project ItemKind import",
    )
    anchor = "pub fn specs() -> Vec<CommandSpec> {\n"
    function = r'''
/// Group two or more Project-panel assets into one real folder, in a single undoable edit.
fn group_items(s: &mut Session, p: &Value) -> Result<Value> {
    let c = "project.group";
    let mut ids = items_p(s, p, c)?;
    ids.sort();
    ids.dedup();
    if ids.len() < 2 {
        return Err(bad(c, "select at least two project assets"));
    }
    if ids.iter().any(|id| s.project.item(*id).is_some_and(|item| item.is_folder())) {
        return Err(bad(c, "folders cannot be included in a new group"));
    }
    let first = s.project.item(ids[0]).ok_or_else(|| bad(c, "project item vanished"))?;
    let label = first.label.clone();
    let candidate_parent = first.parent;
    let parent = if ids.iter().all(|id| s.project.item(*id).is_some_and(|item| item.parent == candidate_parent)) {
        candidate_parent
    } else {
        None
    };
    let name = str_p(p, "name").map(str::trim).filter(|name| !name.is_empty()).unwrap_or("编组").to_string();
    let mut created = None;
    s.edit("Group Project Items", None, |proj, state| {
        for id in &ids {
            if proj.item(*id).is_none() {
                return Err(bad(c, format!("project item {} no longer exists", id.0)));
            }
        }
        let folder = proj.add_item(&name, label.clone(), parent, ItemKind::Folder);
        for id in &ids {
            proj.item_mut(*id).ok_or_else(|| bad(c, "project item vanished"))?.parent = Some(folder);
        }
        state.project_selection = vec![folder];
        created = Some(folder);
        Ok(())
    })?;
    let folder = created.ok_or_else(|| bad(c, "group folder was not created"))?;
    Ok(json!({"folder": folder.0, "items": ids.iter().map(|id| id.0).collect::<Vec<_>>()}))
}

'''
    if "fn group_items(s: &mut Session" not in source:
        if source.count(anchor) != 1:
            raise SystemExit("Group command insertion anchor not found uniquely")
        source = source.replace(anchor, function + anchor, 1)
    spec_anchor = (
        '        cmd!("project.move", "Move to Folder", [], None, "{items?: [id|name] (default: selected), folder: id|name|null (root)}", always, move_items),\n'
    )
    spec_new = spec_anchor + (
        '        cmd!("project.group", "Group Project Items", [], None, "{items: [id|name] (two or more), name?}", always, group_items),\n'
    )
    source = replace_once(source, spec_anchor, spec_new, "Project group command registration")
    path.write_text(source, encoding="utf-8")


def patch_project_panel(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "    details_header(app, ui, &p, &ctx, head);\n",
        "    details_header(app, ui, &p, &ctx, head);\n"
        "    group_controls(app, ui, &ctx, head);\n",
        "Project panel grouping control",
    )
    helper_anchor = "/// The selected item's thumbnail and details (with the comps that use it), or a hint.\n"
    if "fn group_controls(" not in source:
        helpers = r'''
fn group_selection_id() -> egui::Id {
    egui::Id::new("effectcraft-project-group-selection")
}

fn ungroup_target_id() -> egui::Id {
    egui::Id::new("effectcraft-project-ungroup-target")
}

fn long_press_start_id(item: ItemId) -> egui::Id {
    egui::Id::new(("effectcraft-project-long-press-start", item.0))
}

fn long_press_fired_id(item: ItemId) -> egui::Id {
    egui::Id::new(("effectcraft-project-long-press-fired", item.0))
}

/// The Project-panel top-right action appears only after a long press.
fn group_controls(app: &mut EffectcraftApp, ui: &mut egui::Ui, ctx: &egui::Context, head: Rect) {
    let selected = ctx.data(|data| data.get_temp::<Vec<ItemId>>(group_selection_id()).unwrap_or_default());
    let ungroup = ctx.data(|data| data.get_temp::<ItemId>(ungroup_target_id()));
    if selected.is_empty() && ungroup.is_none() {
        return;
    }
    let label = if ungroup.is_some() { crate::i18n::tr("Ungroup") } else { crate::i18n::tr("Group") };
    let enabled = ungroup.is_some() || selected.len() >= 2;
    let rect = Rect::from_min_size(pos2(head.max.x - 82.0, head.min.y + 7.0), vec2(74.0, 24.0));
    let response = ui.add_enabled_ui(enabled, |ui| ui.put(rect, egui::Button::new(label).min_size(vec2(70.0, 22.0)))).inner;
    app.auto.add_response("project.groupAction", &response, if ungroup.is_some() { "Ungroup" } else { "Group" });
    if !response.clicked() {
        return;
    }

    if let Some(folder) = ungroup {
        let Some(folder_item) = app.session.project.item(folder).cloned().filter(|item| item.is_folder()) else {
            app.ui.status = "所选编组已不存在。".into();
            ctx.data_mut(|data| data.remove::<ItemId>(ungroup_target_id()));
            return;
        };
        let children: Vec<u64> = app.session.project.children(Some(folder)).iter().map(|item| item.id.0).collect();
        let parent = folder_item.parent.map(|item| json!(item.0)).unwrap_or(serde_json::Value::Null);
        if !children.is_empty()
            && let Err(error) = crate::menus::invoke(app, ctx, "project.move", json!({"items": children, "folder": parent}))
        {
            app.ui.status = error;
            return;
        }
        if let Err(error) = crate::menus::invoke(app, ctx, "project.delete", json!({"items": [folder.0]})) {
            app.ui.status = error;
            return;
        }
        if !children.is_empty()
            && let Err(error) = crate::menus::invoke(app, ctx, "project.select", json!({"items": children, "add": false}))
        {
            app.ui.status = error;
        }
        ctx.data_mut(|data| {
            data.remove::<ItemId>(ungroup_target_id());
            data.remove::<Vec<ItemId>>(group_selection_id());
        });
        return;
    }

    if selected.len() < 2 {
        return;
    }
    let items: Vec<u64> = selected.iter().map(|item| item.0).collect();
    if let Err(error) = crate::menus::invoke(
        app,
        ctx,
        "project.group",
        json!({"items": items, "name": crate::i18n::tr("Group")}),
    ) {
        app.ui.status = error;
        return;
    }
    ctx.data_mut(|data| {
        data.remove::<Vec<ItemId>>(group_selection_id());
        data.remove::<ItemId>(ungroup_target_id());
    });
}

/// A row held for 550 ms enters group/ungroup mode; short taps retain normal selection behavior.
fn update_long_press_grouping(app: &mut EffectcraftApp, ui: &egui::Ui, ctx: &egui::Context, response: &egui::Response, item: &effectcraft_engine::project::Item) {
    let start_id = long_press_start_id(item.id);
    let fired_id = long_press_fired_id(item.id);
    if response.hovered() && ui.input(|input| input.pointer.primary_pressed()) {
        let now = ui.input(|input| input.time);
        ctx.data_mut(|data| {
            data.insert_temp(start_id, now);
            data.remove::<bool>(fired_id);
        });
    }
    if response.is_pointer_button_down_on()
        && ui.input(|input| input.pointer.primary_down())
        && !response.dragged()
        && let Some(started) = ctx.data(|data| data.get_temp::<f64>(start_id))
        && ui.input(|input| input.time) - started >= 0.55
    {
        let mut first_selection = false;
        ctx.data_mut(|data| {
            data.remove::<f64>(start_id);
            data.insert_temp(fired_id, true);
            if item.is_folder() {
                data.remove::<ItemId>(ungroup_target_id());
                data.insert_temp(ungroup_target_id(), item.id);
                data.remove::<Vec<ItemId>>(group_selection_id());
            } else {
                data.remove::<ItemId>(ungroup_target_id());
                let mut pending = data.get_temp::<Vec<ItemId>>(group_selection_id()).unwrap_or_default();
                first_selection = pending.is_empty();
                if !pending.contains(&item.id) {
                    pending.push(item.id);
                }
                data.insert_temp(group_selection_id(), pending);
            }
        });
        if first_selection && !item.is_folder() {
            app.session.state.project_selection = vec![item.id];
        }
        ctx.request_repaint();
    }
}

'''
        if helper_anchor not in source:
            raise SystemExit("Project grouping helper insertion anchor not found")
        source = source.replace(helper_anchor, helpers + helper_anchor, 1)

    check_anchor = "        let mut resp = ui.interact(r.intersect(list), row_id(*id), Sense::click_and_drag());\n"
    check_mark = r'''        let pending_group = ctx.data(|data| data.get_temp::<Vec<ItemId>>(group_selection_id()).unwrap_or_default());
        if pending_group.contains(id) {
            let check_rect = Rect::from_center_size(pos2(r.max.x - 12.0, r.center().y), vec2(16.0, 16.0));
            lp.circle_filled(check_rect.center(), 7.0, t.accent);
            lp.text(check_rect.center(), Align2::CENTER_CENTER, "✓", Tokens::semibold(11.0), Color32::WHITE);
        }
'''
    source = replace_once(source, check_anchor, check_anchor + check_mark, "Project grouping checkmark")

    click_anchor = (
        "        let resp = resp.union(nresp);\n"
        "        if resp.clicked() {\n"
        "            select_click(app, ui, &ctx, *id, &rows);\n"
        "        }\n"
    )
    click_new = r'''        let resp = resp.union(nresp);
        update_long_press_grouping(app, ui, &ctx, &resp, it);
        let long_press_fired = ctx.data(|data| data.get_temp::<bool>(long_press_fired_id(*id))).unwrap_or(false);
        if resp.clicked() {
            if long_press_fired {
                ctx.data_mut(|data| data.remove::<bool>(long_press_fired_id(*id)));
            } else {
                let grouping = ctx.data(|data| data.get_temp::<Vec<ItemId>>(group_selection_id()).unwrap_or_default());
                let ungrouping = ctx.data(|data| data.get_temp::<ItemId>(ungroup_target_id())).is_some();
                if !ungrouping && !grouping.is_empty() {
                    if !it.is_folder() && !grouping.contains(id) {
                        let mut next = grouping;
                        next.push(*id);
                        ctx.data_mut(|data| data.insert_temp(group_selection_id(), next));
                        ctx.request_repaint();
                    }
                } else if !ungrouping {
                    select_click(app, ui, &ctx, *id, &rows);
                }
            }
        }
'''
    source = replace_once(source, click_anchor, click_new, "Project row click/grouping behavior")
    source = replace_once(
        source,
        "        if resp.double_clicked() {\n            open_item(app, it, *id, &mut actions);\n        }\n",
        "        if resp.double_clicked()\n"
        "            && ctx.data(|data| data.get_temp::<Vec<ItemId>>(group_selection_id()).unwrap_or_default().is_empty())\n"
        "            && ctx.data(|data| data.get_temp::<ItemId>(ungroup_target_id())).is_none()\n"
        "        {\n"
        "            open_item(app, it, *id, &mut actions);\n"
        "        }\n",
        "Project double-click suppression during grouping",
    )
    path.write_text(source, encoding="utf-8")


def patch_timeline_keyframe(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    old = '    let tgl = Rect::from_min_size(pos2(footer.min.x + 10.0, footer.min.y + 3.0), vec2(150.0, 18.0));\n'
    new = r'''    // Require exactly one selected Project asset and exactly one matching layer in this comp.
    let key_target = if let [item] = app.session.state.project_selection.as_slice() {
        let matches: Vec<_> = g.tl.comp.layers.iter().filter(|layer| layer.source.item() == Some(*item)).collect();
        if let [layer] = matches.as_slice() {
            layer.transform().and_then(|transform| transform.get("position")).map(|property| (layer.id, property.uid))
        } else {
            None
        }
    } else {
        None
    };
    let key_rect = Rect::from_min_size(pos2(footer.min.x + 8.0, footer.min.y + 2.0), vec2(24.0, 20.0));
    let key_ctx = g.tl.ctx.clone();
    let key_response = ui.add_enabled_ui(key_target.is_some(), |ui| {
        widgets::icon_button(ui, key_rect, Icon::Keyframe, false, &t, egui::Id::new("timeline-single-asset-keyframe"))
    }).inner.on_hover_text(crate::i18n::tr("Select one project asset before adding a keyframe"));
    app.auto.add_response("timeline.addKeyframe", &key_response, "Add Keyframe");
    if key_response.clicked()
        && let Some((layer, property)) = key_target
    {
        app.session.state.selected_layers = vec![layer];
        app.session.state.selected_props = vec![(layer, property)];
        if let Err(error) = crate::menus::invoke(app, &key_ctx, "anim.addKeyframe", json!({})) {
            app.ui.status = error;
        } else {
            app.ui.status = "已为当前素材的位置添加关键帧。".into();
        }
    }

    let tgl = Rect::from_min_size(pos2(footer.min.x + 38.0, footer.min.y + 3.0), vec2(150.0, 18.0));
'''
    source = replace_once(source, old, new, "Single-asset keyframe button")
    path.write_text(source, encoding="utf-8")


def patch_chinese_catalog(root: Path) -> None:
    path = root / "crates/ui-egui/src/i18n/ui.rs"
    source = path.read_text(encoding="utf-8")
    anchor = 'const SIMPLIFIED_CHINESE: &[(&str, &str)] = &[\n'
    rows = (
        '    ("Puppet Pin Tool", "木偶控点工具"),\n'
        '    ("Group", "编组"),\n'
        '    ("Ungroup", "解除编组"),\n'
        '    ("Add Keyframe", "添加关键帧"),\n'
        '    ("Select one project asset before adding a keyframe", "请先在左上角项目面板选择一个素材；一次仅可对一个素材添加关键帧。"),\n'
    )
    if '("Puppet Pin Tool", "木偶控点工具")' not in source:
        if source.count(anchor) != 1:
            raise SystemExit("Simplified Chinese panel catalog anchor not found uniquely")
        source = source.replace(anchor, anchor + rows, 1)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    patch_chinese_default(root)
    patch_header(root)
    patch_project_engine(root)
    patch_project_panel(root)
    patch_timeline_keyframe(root)
    patch_chinese_catalog(root)
    print("Enabled Simplified Chinese, top-left Puppet shortcut, Project grouping/ungrouping, and single-asset keyframes.")


if __name__ == "__main__":
    main()
