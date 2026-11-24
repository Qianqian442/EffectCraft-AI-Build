#!/usr/bin/env python3
"""Add the requested Chinese, Puppet quick-access, project grouping and single-item keyframe controls."""
from __future__ import annotations

import os
import re
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
    if new not in source:
        source = replace_once(source, old, new, "Simplified Chinese default")
        path.write_text(source, encoding="utf-8")

    # Android builds always use the Simplified Chinese catalog, including existing
    # installations whose saved preference was English or "Match System".
    language_path = root / "crates/ui-egui/src/i18n.rs"
    language_source = language_path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_FORCE_SIMPLIFIED_CHINESE_V1"
    if marker not in language_source:
        old_function = '''pub(crate) fn language(app: &EffectcraftApp) -> &'static str {
    match app.session.prefs.general.language.as_str() {
        "system" => system_language(),
        stored => code(stored),
    }
}'''
        new_function = '''// EFFECTCRAFT_ANDROID_FORCE_SIMPLIFIED_CHINESE_V1
pub(crate) fn language(app: &EffectcraftApp) -> &'static str {
    #[cfg(target_os = "android")]
    {
        let _ = app;
        "zh-hans"
    }
    #[cfg(not(target_os = "android"))]
    {
        match app.session.prefs.general.language.as_str() {
            "system" => system_language(),
            stored => code(stored),
        }
    }
}'''
        language_source = replace_once(
            language_source, old_function, new_function,
            "Android Simplified Chinese-only interface",
        )
        language_path.write_text(language_source, encoding="utf-8")


def translate_effect_label(value: str) -> str:
    exact = {
        "Cryptomatte": "加密遮罩",
        "EXtractoR": "多通道提取器",
        "IDentifier": "通道标识器",
        "Unmult": "取消预乘",
        "Key Light": "色键抠像",
        "Lumetri 颜色": "电影调色",
        "Cineon 转换器": "电影胶片转换器",
        "Mocha 形状": "跟踪形状",
    }
    if value in exact:
        return exact[value]
    value = re.sub(r"^CC\s*", "", value)
    value = re.sub(r"^VR\s*", "全景", value)
    for old, new in (
        ("3D", "三维"),
        ("HLS", "色相、亮度和饱和度"),
        ("RGB", "红绿蓝"),
        ("HDR", "高动态范围"),
        ("OCIO", "色彩管理"),
        ("CDL", "色彩决策列表"),
        ("Alpha", "透明度"),
        ("LUT", "颜色查找表"),
        ("Roto", "智能抠像"),
        ("PS ", "像素"),
    ):
        value = value.replace(old, new)
    value = re.sub(r"\bII\b", "第二代", value)
    value = re.sub(r"\bID\s*", "编号", value)
    value = re.sub(r"\bCC\b", "", value)
    return re.sub(r"\s+", " ", value).strip()


def translate_ui_label(value: str) -> str:
    exact = {
        "MIT 或 Apache-2.0 • 字体：Inter、JetBrains Mono（OFL）":
            "采用开放源代码许可证 · 字体：无衬线字体、等宽字体（开放字体许可证）",
        "将绘画颜色设为黑白（D）": "将绘画颜色设为黑色和白色",
        "交换绘画颜色（X）": "交换绘画颜色",
        "{} x {}，每 8bpc 帧 {}MB": "{} × {}，每帧 {} 兆字节（8 位通道色深）",
        "Adobe 风格内置": "桌面特效软件风格内置",
        "导入 PDF / Illustrator 文件": "导入便携文档或矢量图形文件",
        "导入 Photoshop 文件": "导入图像编辑文件",
        "Mercury GPU 加速（{}）": "显卡加速（{}）",
        "sRGB IEC61966-2.1（默认）": "标准红绿蓝色彩空间（默认）",
        "缓动 (F9)": "缓动",
        "缓入 (Shift+F9)": "缓入",
        "缓出 (Ctrl+Shift+F9)": "缓出",
        "getartcraft.com 上的 EffectCraft": "效果工坊官方网站",
        "getartcraft.com 上的 效果工坊": "效果工坊官方网站",
        "视频开始 (ISO 日期时间、hh:mm:ss、时间码；为空: 文件日期)": "视频开始时间（标准日期时间、时分秒、时间码；留空则使用文件日期）",
        "在 macOS 上使用窗口内菜单栏": "在苹果电脑系统上使用窗口内菜单栏",
        "GitHub 上的 效果工坊": "效果工坊代码仓库",
        "Lottie 动画": "矢量动画",
        "面板始终由 图形处理器（wgpu）绘制。": "面板始终由图形处理器绘制。",
        "视频开始 (标准 日期时间、hh:mm:ss、时间码；为空: 文件日期)":
            "视频开始时间（标准日期时间、时分秒、时间码；留空则使用文件日期）",
        "颜色 (#rrggbb)": "颜色（十六进制色值）",
        "已合并 PR": "已合并的代码请求",
        "GitHub 上的源代码": "效果工坊项目源代码",
    }
    if value in exact:
        return exact[value]
    replacements = (
        ("EffectCraft", "效果工坊"),
        ("ArtCraft", "效果工坊"),
        ("Discord", "社群"),
        ("After Effects", "桌面特效软件"),
        ("ScriptUI", "脚本交互面板"),
        ("Illustrator", "矢量绘图软件"),
        ("Photoshop", "图像编辑软件"),
        ("OpenEXR", "高动态范围图像"),
        ("Lumetri", "电影色彩"),
        ("JavaScript", "脚本语言"),
        ("OpenGL", "图形接口"),
        ("sRGB IEC61966-2.1", "标准红绿蓝色彩空间"),
        ("Rec. 2020", "2020 广色域标准"),
        ("Feet + Frames", "英尺与帧"),
        ("35mm", "35 毫米"),
        ("16mm", "16 毫米"),
        ("Opus", "音频编码"),
        ("Mercury", "显卡渲染"),
        ("GPU", "图形处理器"),
        ("CPU", "处理器"),
        ("OCIO", "色彩管理"),
        ("ACES", "色彩标准"),
        ("Alpha", "透明度"),
        ("3D", "三维"),
        ("VR", "全景"),
        ("RGB", "红绿蓝"),
        ("LUT", "颜色查找表"),
        ("HLS", "色相、亮度和饱和度"),
        ("Roto", "智能抠像"),
        ("URL", "网址"),
        ("Ctrl", "控制键"),
        ("Shift", "上档键"),
        ("Alt", "替换键"),
        ("ISO", "标准"),
        ("8bpc", "8 位通道色深"),
        ("bpc", "位通道"),
        ("MB", "兆字节"),
        ("kbps", "千比特/秒"),
        ("fps", "帧/秒"),
        ("A–Z", "升序"),
        ("A-Z", "升序"),
        ("PRs", "代码请求"),
        ("X and Y", "横向和纵向"),
        ("X only", "仅横向"),
        ("Y only", "仅纵向"),
        ("X", "横向"),
        ("Y", "纵向"),
        ("Enter", "回车"),
        ("GitHub", "代码仓库"),
        ("Lottie", "矢量动画"),
        ("wgpu", "图形渲染框架"),
        ("macOS", "苹果电脑系统"),
        ("getartcraft.com", "效果工坊官网"),
    )
    for old, new in replacements:
        value = value.replace(old, new)
    value = value.replace("⌘/控制键+Enter", "组合键+回车")
    value = value.replace("⌘/控制键+回车", "组合键+回车")
    value = value.replace(" • ", " · ")
    value = value.replace("代码仓库 上的 效果工坊", "效果工坊代码仓库")
    value = value.replace("代码仓库 上的源代码", "效果工坊项目源代码")
    return re.sub(r"\s+", " ", value).strip()


def patch_simplified_chinese_catalogs(root: Path) -> None:
    effects_path = root / "crates/ui-egui/src/i18n/effects.rs"
    effects_source = effects_path.read_text(encoding="utf-8")
    effects_start = effects_source.find("const SIMPLIFIED_CHINESE: &[Row] = &[")
    effects_end = effects_source.find("\n];", effects_start)
    if effects_start < 0 or effects_end < 0:
        raise SystemExit("Could not locate the Simplified Chinese effect-name catalog.")
    effects_block = effects_source[effects_start:effects_end]
    effect_row = re.compile(r'(\(\s*"[^"]+"\s*,\s*"[^"]+"\s*,\s*")([^"]*)("\s*\),)')

    def patch_effect(match: re.Match[str]) -> str:
        translated = translate_effect_label(match.group(2))
        if re.search(r"[A-Za-z]", translated):
            raise SystemExit(f"Effect name still contains English: {translated}")
        return match.group(1) + translated + match.group(3)

    effects_block, effect_count = effect_row.subn(patch_effect, effects_block)
    if effect_count < 300:
        raise SystemExit(f"Only {effect_count} Simplified Chinese effect names were found.")
    effects_source = effects_source[:effects_start] + effects_block + effects_source[effects_end:]
    effects_path.write_text(effects_source, encoding="utf-8")

    ui_path = root / "crates/ui-egui/src/i18n/ui.rs"
    ui_source = ui_path.read_text(encoding="utf-8")
    ui_start = ui_source.find("const SIMPLIFIED_CHINESE:")
    ui_end = ui_source.find("\n];", ui_start)
    if ui_start < 0 or ui_end < 0:
        raise SystemExit("Could not locate the Simplified Chinese interface catalog.")
    ui_block = ui_source[ui_start:ui_end]
    ui_row = re.compile(r'(\(\s*"(?:\\.|[^"]*)"\s*,\s*")((?:\\.|[^"])*)("\s*\),)')

    def patch_ui(match: re.Match[str]) -> str:
        translated = translate_ui_label(match.group(2))
        visible = re.sub(r"\\[nrt]", "", translated)
        if re.search(r"[A-Za-z]", visible):
            raise SystemExit(f"Interface label still contains English: {translated}")
        return match.group(1) + translated + match.group(3)

    ui_block, ui_count = ui_row.subn(patch_ui, ui_block)
    if ui_count < 1000:
        raise SystemExit(f"Only {ui_count} Simplified Chinese interface labels were found.")
    ui_source = ui_source[:ui_start] + ui_block + ui_source[ui_end:]
    ui_path.write_text(ui_source, encoding="utf-8")
    print(f"Translated {effect_count} effect names and {ui_count} interface labels into Chinese.")


def verify_simplified_chinese_catalogs(root: Path) -> None:
    effects = (root / "crates/ui-egui/src/i18n/effects.rs").read_text(encoding="utf-8")
    effects_start = effects.find("const SIMPLIFIED_CHINESE: &[Row] = &[")
    effects_end = effects.find("\n];", effects_start)
    ui = (root / "crates/ui-egui/src/i18n/ui.rs").read_text(encoding="utf-8")
    ui_start = ui.find("const SIMPLIFIED_CHINESE:")
    ui_end = ui.find("\n];", ui_start)
    if min(effects_start, effects_end, ui_start, ui_end) < 0:
        raise SystemExit("Simplified Chinese catalog verification could not locate a table.")
    effects_block = effects[effects_start:effects_end]
    ui_block = ui[ui_start:ui_end]
    effect_names = re.findall(r'\(\s*"[^"]+"\s*,\s*"[^"]+"\s*,\s*"((?:\\.|[^"])*)"\s*\)', effects_block)
    ui_labels = re.findall(r'\(\s*"(?:\\.|[^"]*)"\s*,\s*"((?:\\.|[^"])*)"\s*\)', ui_block)
    for label in effect_names + ui_labels:
        visible = re.sub(r"\\[nrt]", "", label)
        if re.search(r"[A-Za-z]", visible):
            raise SystemExit(f"Simplified Chinese catalog still displays English: {label}")
    if len(effect_names) < 300 or len(ui_labels) < 1000:
        raise SystemExit("Simplified Chinese catalog is unexpectedly incomplete.")


def verify_android_chinese_language(root: Path) -> None:
    source = (root / "crates/ui-egui/src/i18n.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_FORCE_SIMPLIFIED_CHINESE_V1" not in source:
        raise SystemExit("Android is not locked to the Simplified Chinese interface catalog.")


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
        // Match Alight Motion's selection workflow: long-press an item, select more,
        // then use the clearly visible Group action in the panel's upper-right corner.
        let label = if mode.ungroup.is_some() {
            "解除编组".to_string()
        } else {
            format!("编组（{}）", mode.selected.len())
        };
        let enabled = mode.ungroup.is_some() || mode.selected.len() >= 2;
        let y = rect.min.y + 6.0;
        let group_rect = Rect::from_min_size(pos2(rect.max.x - 176.0, y), vec2(104.0, 28.0));
        let group_response = ui.interact(
            group_rect,
            egui::Id::new("effectcraft-project-group-action"),
            if enabled { Sense::click() } else { Sense::hover() },
        );
        p.rect_filled(group_rect, 5.0, if enabled { t.accent } else { t.row });
        p.rect_stroke(group_rect, 5.0, Stroke::new(1.0, if enabled { t.accent } else { t.separator }), egui::StrokeKind::Inside);
        p.text(
            group_rect.center(),
            Align2::CENTER_CENTER,
            &label,
            Tokens::semibold(12.0),
            if enabled { Color32::WHITE } else { t.text_dim },
        );
        app.auto.add("project.groupAction", group_rect, &label);

        let cancel_rect = Rect::from_min_size(pos2(rect.max.x - 66.0, y), vec2(60.0, 28.0));
        let cancel_response = ui.interact(
            cancel_rect,
            egui::Id::new("effectcraft-project-group-cancel"),
            Sense::click(),
        );
        p.rect_filled(cancel_rect, 5.0, t.row);
        p.rect_stroke(cancel_rect, 5.0, Stroke::new(1.0, t.separator), egui::StrokeKind::Inside);
        p.text(
            cancel_rect.center(),
            Align2::CENTER_CENTER,
            "取消",
            Tokens::semibold(12.0),
            t.text,
        );
        app.auto.add("project.groupCancel", cancel_rect, "取消编组选择");

        if cancel_response.clicked() {
            ctx.data_mut(|data| data.remove::<ProjectGroupMode>(project_group_mode_id()));
        }
        if group_response.clicked() && enabled {
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
                app.ui.status = if it.is_folder() {
                    "已进入解除编组选项；点右上角“解除编组”或点“取消”。".into()
                } else {
                    "已进入编组选取：轻点其他素材加入，至少选择两个后点右上角“编组”。".into()
                };
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


def patch_project_file_selection_for_timeline(root: Path) -> None:
    """A Project-panel file click selects its matching layer and Position curve."""
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_PROJECT_FILE_SELECTION_CURVE_V2"
    if marker in source:
        return

    old = '''    } else {
        app.session.state.project_selection = vec![id];
        ctx.data_mut(|d| d.insert_temp(anchor_key, id));
    }
}'''
    new = r'''    } else {
        app.session.state.project_selection = vec![id];
        ctx.data_mut(|d| d.insert_temp(anchor_key, id));
    }
    sync_project_file_to_timeline(app);
}

/// EFFECTCRAFT_ANDROID_PROJECT_FILE_SELECTION_CURVE_V2
/// Keep the Project panel file, Timeline layer and Position curve selection in sync.
/// A single file chooses its first matching layer; multi-file selection chooses every match.
fn sync_project_file_to_timeline(app: &mut EffectcraftApp) {
    let items = app.session.state.project_selection.clone();
    let selected_layers: Vec<effectcraft_engine::project::LayerId> =
        if let Some(comp) = app.session.active_comp() {
            if let [item] = items.as_slice() {
                comp.layers.iter()
                    .find(|layer| layer.source.item() == Some(*item))
                    .map(|layer| vec![layer.id])
                    .unwrap_or_default()
            } else {
                comp.layers.iter()
                    .filter(|layer| layer.source.item().is_some_and(|item| items.contains(&item)))
                    .map(|layer| layer.id)
                    .collect()
            }
        } else {
            Vec::new()
        };
    let selected_props: Vec<(effectcraft_engine::project::LayerId, u64)> =
        if let Some(comp) = app.session.active_comp() {
            selected_layers.iter().filter_map(|layer_id| {
                comp.layer(*layer_id)
                    .and_then(|layer| layer.props.group("transform"))
                    .and_then(|transform| transform.get("position"))
                    .map(|position| (*layer_id, position.uid))
            }).collect()
        } else {
            Vec::new()
        };
    app.session.state.selected_layers = selected_layers;
    app.session.state.selected_props = selected_props;
    app.session.state.selected_keys.clear();
    app.session.state.selected_vertices.clear();
}'''
    source = replace_once(source, old, new, "Project file click to timeline and curve selection")
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
    keyframe_code = r'''    // A viewer click or Timeline tap explicitly selects the target layer. Keyframing
    // must work from that selection even when the layer source is not a Project-panel item
    // (for example, solids, nested comps or generated media). Only one unlocked layer is
    // accepted to prevent writing a key to the wrong target.
    let selected_project_item = (app.session.state.project_selection.len() == 1)
        .then(|| app.session.state.project_selection[0]);
    let selected_layer = match app.session.state.selected_layers.as_slice() {
        [layer] => g.tl.comp.layer(*layer)
            .filter(|layer| !layer.switches.locked)
            .map(|layer| layer.id),
        [] => selected_project_item.and_then(|item| {
            let movable: Vec<_> = g.tl.comp.layers.iter()
                .filter(|layer| layer.source.item() == Some(item) && !layer.switches.locked)
                .collect();
            if let [layer] = movable.as_slice() { Some(layer.id) } else { None }
        }),
        _ => None,
    };
    // EFFECTCRAFT_ANDROID_VISIBLE_KEYFRAME_BUTTON_V3
    let keyframe_enabled = selected_layer.is_some();
    let keyframe_height = (footer.height() - 2.0).max(18.0);
    let keyframe_width = (graph_x0 - footer.min.x - 16.0).clamp(56.0, 112.0);
    let keyframe_rect = Rect::from_min_size(
        pos2(footer.min.x + 8.0, footer.center().y - keyframe_height * 0.5),
        vec2(keyframe_width, keyframe_height),
    );
    let keyframe_hint = if keyframe_enabled {
        "添加关键帧（当前选中的画面或时间轴图层）"
    } else {
        "先点击画面中的素材或时间轴图层，单独选中一个未锁定图层"
    };
    // A high-contrast, wide touch target is always visible in the timeline footer.
    // It remains tappable when disabled so the required single-item selection is explained.
    let keyframe_text = if keyframe_width < 96.0 { "＋ 关键帧" } else { "＋ 添加关键帧" };
    let keyframe_button = egui::Button::new(keyframe_text)
        .fill(if keyframe_enabled { t.accent } else { t.field_bg })
        .min_size(keyframe_rect.size());
    let keyframe_response = ui.put(keyframe_rect, keyframe_button).on_hover_text(keyframe_hint);
    app.auto.add_response("timeline.addKeyframe", &keyframe_response, "添加关键帧");
    if keyframe_response.clicked() {
        if !keyframe_enabled {
            app.ui.status = keyframe_hint.to_string();
        } else if let Some(layer_id) = selected_layer {
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
    if "EFFECTCRAFT_ANDROID_VISIBLE_KEYFRAME_BUTTON_V3" not in source:
        source = replace_once(source, anchor, keyframe_code + anchor, "Single-item keyframe button")
    source = replace_once(
        source,
        'let tgl = Rect::from_min_size(pos2(footer.min.x + 10.0, footer.min.y + 3.0), vec2(150.0, 18.0));',
        'let tgl_x = keyframe_rect.max.x + 8.0;\n    let tgl_width = (graph_x0 - 6.0 - tgl_x).max(0.0).min(140.0);\n    let tgl = Rect::from_min_size(pos2(tgl_x, footer.min.y + 3.0), vec2(tgl_width, 18.0));',
        "Timeline footer spacing",
    )
    source = replace_once(
        source,
        '        crate::i18n::tr("Toggle Switches / Modes"),',
        '        if tgl.width() < 100.0 { crate::i18n::tr("模式") } else { crate::i18n::tr("Toggle Switches / Modes") },',
        "Responsive Timeline mode label",
    )
    path.write_text(source, encoding="utf-8")


def patch_layer_keyframe_markers(root: Path) -> None:
    """Draw a visible tick on each layer bar at the times where that layer has keyframes."""
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_LAYER_KEYFRAME_MARKS_V1"
    if marker in source:
        return

    helper = r'''
// EFFECTCRAFT_ANDROID_LAYER_KEYFRAME_MARKS_V1
/// Collect keyframe times from every property in this layer, including collapsed groups.
fn android_collect_layer_keyframes(group: &PropGroup, times: &mut Vec<i64>) {
    for node in &group.children {
        match node {
            Node::Prop(prop) => times.extend(prop.keys.iter().map(|key| key.time.0)),
            Node::Group(child) => android_collect_layer_keyframes(child, times),
        }
    }
}

/// Display-only marks on the layer's own duration bar; native keyframe data and hit targets are unchanged.
fn android_layer_keyframe_marks(g: &Rw, rc: &RowCtx<'_>, bar: Rect) {
    let mut times = Vec::new();
    android_collect_layer_keyframes(&rc.layer.props, &mut times);
    if times.is_empty() {
        return;
    }
    times.sort_unstable();
    times.dedup();

    let visible = bar.intersect(g.right_clip);
    if !visible.is_positive() {
        return;
    }
    let painter = g.gp.clone().with_clip_rect(visible);
    let marker_color = Color32::WHITE;
    for time in times {
        let comp_time = rc.layer.comp_time(Tick(time)).seconds();
        let x = g.tl.tm.x(comp_time);
        if x < visible.min.x || x > visible.max.x {
            continue;
        }
        let center = pos2(x, bar.center().y);
        let radius = 3.4;
        // A small diamond is visually consistent with the keyframe glyphs on the property rows.
        painter.add(egui::Shape::convex_polygon(
            vec![
                pos2(center.x, center.y - radius),
                pos2(center.x + radius, center.y),
                pos2(center.x, center.y + radius),
                pos2(center.x - radius, center.y),
            ],
            marker_color,
            Stroke::NONE,
        ));
    }
}
'''
    anchor = "/// The layer's duration bar: source extent, move and trim, markers.\nfn layer_bar("
    if source.count(anchor) != 1:
        raise SystemExit(f"Layer keyframe markers: expected one layer_bar insertion point, found {source.count(anchor)}")
    source = source.replace(anchor, helper + "\n" + anchor, 1)

    call = "    layer_bar_markers(app, ui, g, rc);\n"
    if source.count(call) != 1:
        raise SystemExit(f"Layer keyframe markers: expected one existing layer marker call, found {source.count(call)}")
    source = source.replace(call, call + "    android_layer_keyframe_marks(g, rc, bar);\n", 1)
    path.write_text(source, encoding="utf-8")



def patch_native_keyframe_color(root: Path) -> None:
    """Keep keyframes readable and dim unrelated properties while an AM effect is focused."""
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_AM_FOCUSED_KEYFRAME_OPACITY_V2"
    if marker in source:
        return

    # Carry selected property IDs into the timeline painter. The native selected_props
    # state is the source of truth, so focus follows the actual property/effect selection.
    source = replace_once(
        source,
        "    sel_keys: Vec<effectcraft_engine::KeyRef>,\n",
        "    sel_keys: Vec<effectcraft_engine::KeyRef>,\n    selected_props: Vec<(LayerId, u64)>,\n",
        "carry focused property IDs into keyframe painter",
    )
    source = replace_once(
        source,
        "        sel_keys: app.session.state.selected_keys.clone(),\n",
        "        sel_keys: app.session.state.selected_keys.clone(),\n        selected_props: app.session.state.selected_props.clone(),\n",
        "initialize focused property IDs for keyframe painter",
    )
    old = """    // Labelled keys take their label colour (brighter when selected).
    let kcol = match effectcraft_engine::color::Label::ALL.get(k.label as usize).filter(|_| k.label > 0) {
        Some(l) => {
            let c = t.label(*l);
            if ks { c } else { c.gamma_multiply(0.75) }
        }
        None if ks => t.keyframe_selected,
        None => t.keyframe,
    };
    // Muted keys stay visible and editable but no longer drive the value.
    let kcol = if k.muted { kcol.gamma_multiply(0.35) } else { kcol };
"""
    new = """    // EFFECTCRAFT_ANDROID_AM_FOCUSED_KEYFRAME_OPACITY_V3
    // A selected effect/group focuses all of its child properties as one stack.
    // A selected individual property focuses only that property's keys.
    let am_effect_params = g.tl.ctx.data(|d| {
        d.get_temp::<bool>(egui::Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY")).unwrap_or(false)
    });
    fn group_contains_key_property(group: &PropGroup, uid: u64) -> bool {
        group.children.iter().any(|node| match node {
            Node::Prop(prop) => prop.uid == uid,
            Node::Group(child) => group_contains_key_property(child, uid),
        })
    }
    let selected_effect_uid = g.tl.ctx.data(|d| {
        d.get_temp::<u64>(egui::Id::new("EFFECTCRAFT_AM_SELECTED_EFFECT_ID"))
    });
    let focused = match &rc.row.kind {
        RowKind::Prop { uid } => {
            let property_selected = g.selected_props.iter().any(|(layer_id, selected_uid)| {
                *layer_id == rc.layer.id && (
                    *selected_uid == *uid
                    || rc.layer.props.find_group(*selected_uid)
                        .is_some_and(|group| group_contains_key_property(group, *uid))
                )
            });
            let effect_selected = selected_effect_uid.is_some_and(|effect_uid| {
                rc.layer.props.find_group(effect_uid)
                    .is_some_and(|group| group_contains_key_property(group, *uid))
            });
            property_selected || effect_selected
        }
        _ => false,
    };
    let kcol = if am_effect_params {
        if focused { Color32::WHITE } else { Color32::WHITE.gamma_multiply(0.30) }
    } else {
        match effectcraft_engine::color::Label::ALL.get(k.label as usize).filter(|_| k.label > 0) {
            Some(l) => {
                let c = t.label(*l);
                if ks { c } else { c.gamma_multiply(0.75) }
            }
            None if ks => t.keyframe_selected,
            None => t.keyframe,
        }
    };
    let kcol = if k.muted { kcol.gamma_multiply(0.35) } else { kcol };
"""
    source = replace_once(source, old, new, "AM focused keyframe opacity")
    path.write_text(source, encoding="utf-8")




def patch_am_layer_delete_command(root: Path) -> None:
    path = root / "crates/engine/src/cmd/layer.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_LAYER_DELETE_COMMAND_V1"
    if marker not in source:
        helper = r"""
// EFFECTCRAFT_AM_LAYER_DELETE_COMMAND_V1
/// Delete selected composition layers without deleting their Project-panel source items.
fn delete_layers(s: &mut Session, p: &Value) -> Result<Value> {
    const C: &str = "layer.delete";
    let cid = comp_id(s, p)?;
    let ids = layers_p(s, p, C)?;
    if ids.is_empty() { return Err(bad(C, "no layers selected")); }
    let count = ids.len();
    s.edit("Delete Layers", None, |project, state| {
        let comp = project.comp_mut(cid).ok_or(EngineError::Other("composition vanished".into()))?;
        comp.layers.retain(|layer| !ids.contains(&layer.id));
        for layer in &mut comp.layers {
            if layer.parent.is_some_and(|parent| ids.contains(&parent)) { layer.parent = None; }
            if layer.track_matte.is_some_and(|matte| ids.contains(&matte.layer)) { layer.track_matte = None; }
        }
        state.selected_layers.retain(|layer| !ids.contains(layer));
        state.selected_props.retain(|(layer, _)| !ids.contains(layer));
        state.selected_keys.retain(|key| !ids.contains(&key.layer));
        Ok(())
    })?;
    s.sanitize_state();
    Ok(json!({"deleted": count}))
}
"""
        source = replace_once(source, "pub fn specs() -> Vec<CommandSpec> {", helper + "\npub fn specs() -> Vec<CommandSpec> {", "AM native layer deletion command")
        select_spec = '        cmd!("layer.select", "Select Layers", [], None, "{layers: [id|name|#n], add?, toggle?}", has_comp, select),'
        delete_spec = '        cmd!("layer.delete", "Delete Layers", [], None, "{layers?: [id|name|#n] (default: selected)}", has_layers, delete_layers),\n' + select_spec
        source = replace_once(source, select_spec, delete_spec, "AM layer deletion command registration")
        path.write_text(source, encoding="utf-8")


def patch_am_effect_parameter_keyframes(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/effect_controls/rows.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_EFFECT_PARAMETER_KEY_NAVIGATOR_V1"
    if marker not in source:
        old = """    if prop.is_animated() {
        let half = ectx.comp.frame_duration().0 / 2;
        let on_key = prop.keys.iter().any(|k| (layer.comp_time(k.time).0 - ectx.time.0).abs() <= half);
        key_navigator(app, ui, p, KeyNav { layer_id: layer.id.0, on_key }, prop, r, actions);
    }"""
        new = """    // EFFECTCRAFT_AM_EFFECT_PARAMETER_KEY_NAVIGATOR_V1
    // AM exposes the first add/remove keyframe control on every keyframe-capable parameter.
    let am_effect_params = ui.ctx().data(|d| {
        d.get_temp::<bool>(egui::Id::new("EFFECTCRAFT_AM_EFFECT_PARAMS_ONLY")).unwrap_or(false)
    });
    if prop.is_animated() || (am_effect_params && !prop.static_only) {
        let half = ectx.comp.frame_duration().0 / 2;
        let on_key = prop.keys.iter().any(|k| (layer.comp_time(k.time).0 - ectx.time.0).abs() <= half);
        key_navigator(app, ui, p, KeyNav { layer_id: layer.id.0, on_key }, prop, r, actions);
    }"""
        source = replace_once(source, old, new, "AM effect parameter add/remove keyframe controls")
        path.write_text(source, encoding="utf-8")


def patch_chinese_effect_parameter_labels(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/effect_controls/rows.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_CHINESE_EFFECT_PARAMETER_LABELS_V1"
    if marker not in source:
        helper = r"""
// EFFECTCRAFT_ANDROID_CHINESE_EFFECT_PARAMETER_LABELS_V1
/// Translate dynamic parameter names without showing English source labels.
fn localized_effect_parameter_label(source: &str) -> String {
    let catalog = crate::i18n::tr(source);
    if catalog != source { return catalog.to_string(); }
    let mut value = source.to_string();
    for (english, chinese) in [
        ("Opacity", "不透明度"), ("Radius", "半径"), ("Amount", "数量"),
        ("Angle", "角度"), ("Position", "位置"), ("Scale", "缩放"),
        ("Intensity", "强度"), ("Threshold", "阈值"), ("Width", "宽度"),
        ("Height", "高度"), ("Feather", "羽化"), ("Blur", "模糊"),
        ("Exposure", "曝光"), ("Contrast", "对比度"), ("Saturation", "饱和度"),
        ("Rotation", "旋转"), ("Frequency", "频率"), ("Strength", "强度"),
        ("Distance", "距离"), ("Color", "颜色"), ("Colour", "颜色"),
        ("Tint", "色调"), ("Speed", "速度"), ("Time", "时间"),
        ("Phase", "相位"), ("Offset", "偏移"), ("Center", "中心"),
        ("Centre", "中心"), ("Start", "起点"), ("End", "终点"),
        ("Mix", "混合"), ("Blend", "混合"), ("Mode", "模式"),
        ("Level", "级别"), ("Gamma", "伽马"), ("Gain", "增益"),
        ("Highlights", "高光"), ("Shadows", "阴影"), ("Midtones", "中间调"),
        ("Temperature", "色温"), ("Turbulence", "湍流"), ("Evolution", "演化"),
        ("Iterations", "迭代次数"), ("Amplitude", "振幅"),
        ("X", "横向"), ("Y", "纵向"), ("Z", "深度"),
    ] { value = value.replace(english, chinese); }
    if value.chars().any(|ch| ch.is_ascii_alphabetic()) { "参数".to_string() } else { value }
}
"""
        source = replace_once(source, "fn triangle(p: &egui::Painter, c: egui::Pos2, left: bool, col: Color32) {", helper + "\nfn triangle(p: &egui::Painter, c: egui::Pos2, left: bool, col: Color32) {", "Chinese dynamic effect parameter labels")
        source = replace_once(source, "    let uid = prop.uid;\n    if ui.input(|i| i.pointer.primary_pressed())", "    let uid = prop.uid;\n    let shown_name = localized_effect_parameter_label(&prop.name);\n    if ui.input(|i| i.pointer.primary_pressed())", "Chinese property label binding")
        source = replace_once(source, "p.with_clip_rect(name_clip.intersect(p.clip_rect())).text(pos2(swr.max.x + 6.0, cy), Align2::LEFT_CENTER, &prop.name, Tokens::ui(12.0), t.text);", "p.with_clip_rect(name_clip.intersect(p.clip_rect())).text(pos2(swr.max.x + 6.0, cy), Align2::LEFT_CENTER, &shown_name, Tokens::ui(12.0), t.text);", "Chinese property label drawing")
        source = replace_once(source, "    p.text(pos2(cr.max.x + 6.0, cy), Align2::LEFT_CENTER, &prop.name, Tokens::ui(12.0), t.text_dim);", "    let shown_name = localized_effect_parameter_label(&prop.name);\n    p.text(pos2(cr.max.x + 6.0, cy), Align2::LEFT_CENTER, &shown_name, Tokens::ui(12.0), t.text_dim);", "Chinese toggle parameter label")
        source = replace_once(source, "                    let name = p.text(pos2(tw.max.x + 6.0, r.center().y), Align2::LEFT_CENTER, &sg.name, Tokens::ui(12.0), t.text);", "                    let shown_group_name = localized_effect_parameter_label(&sg.name);\n                    let name = p.text(pos2(tw.max.x + 6.0, r.center().y), Align2::LEFT_CENTER, &shown_group_name, Tokens::ui(12.0), t.text);", "Chinese effect subgroup label")
        old_popup = """    if let ParamUi::Popup { options } = &prop.ui {
        let widest = options.iter().map(|o| p.layout_no_wrap(o.clone(), Tokens::ui(11.5), t.text).size().x).fold(0.0, f32::max);
        let dr = Rect::from_min_size(pos2(vx, cy - 9.0), vec2((widest + 30.0).clamp(80.0, (r.max.x - vx - 56.0).max(80.0)), 18.0));
        let pop = egui::Id::unique(("ec-epop", uid));
        if widgets::dropdown(ui, dr, options.get(*i as usize).map(String::as_str).unwrap_or(""), &t, egui::Id::unique(("ec-e", uid))).clicked() {
            widgets::open_popup(ui, pop);
        }
        app.auto.add(&format!("effectControls.prop.{uid}.value"), dr, &prop.name);
        if let Some(ni) = widgets::popup_menu(ui, pop, dr.left_bottom(), options, Some(*i as usize)) {
            cx.set_step(actions, json!(ni));
        }
    }"""
        new_popup = """    if let ParamUi::Popup { options } = &prop.ui {
        let shown_options: Vec<String> = options.iter().map(|option| localized_effect_parameter_label(option)).collect();
        let widest = shown_options.iter().map(|o| p.layout_no_wrap(o.clone(), Tokens::ui(11.5), t.text).size().x).fold(0.0, f32::max);
        let dr = Rect::from_min_size(pos2(vx, cy - 9.0), vec2((widest + 30.0).clamp(80.0, (r.max.x - vx - 56.0).max(80.0)), 18.0));
        let pop = egui::Id::unique(("ec-epop", uid));
        if widgets::dropdown(ui, dr, shown_options.get(*i as usize).map(String::as_str).unwrap_or(""), &t, egui::Id::unique(("ec-e", uid))).clicked() {
            widgets::open_popup(ui, pop);
        }
        app.auto.add(&format!("effectControls.prop.{uid}.value"), dr, &prop.name);
        if let Some(ni) = widgets::popup_menu(ui, pop, dr.left_bottom(), &shown_options, Some(*i as usize)) {
            cx.set_step(actions, json!(ni));
        }
    }"""
        source = replace_once(source, old_popup, new_popup, "Chinese effect parameter popup choices")
        path.write_text(source, encoding="utf-8")


def patch_am_effect_application_enable(root: Path) -> None:
    path = root / "crates/engine/src/cmd/effect.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_ENABLE_LAYER_EFFECTS_ON_APPLY_V1"
    if marker in source:
        return
    old = '            let l = layer_mut(proj, cid, *lid)?;\n            let fx = l.props.sub_mut("effects")'
    new = '            let l = layer_mut(proj, cid, *lid)?;\n            // Applying an effect should make it visible immediately, even if the layer\\\'s FX switch was previously off.\n            l.switches.effects = true;\n            let fx = l.props.sub_mut("effects")'
    source = replace_once(source, old, new, "Enable layer effects when applying an effect")
    source = source.replace("fn apply(s: &mut Session, p: &Value)", marker + "\\nfn apply(s: &mut Session, p: &Value)", 1)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_default_language(root)
    patch_simplified_chinese_catalogs(root)
    verify_simplified_chinese_catalogs(root)
    verify_android_chinese_language(root)
    patch_project_commands(root)
    patch_puppet_quick_button(root)
    patch_project_panel(root)
    patch_project_file_selection_for_timeline(root)
    patch_timeline_keyframe_button(root)
    patch_layer_keyframe_markers(root)
    patch_native_keyframe_color(root)
    patch_am_layer_delete_command(root)
    patch_am_effect_parameter_keyframes(root)
    patch_chinese_effect_parameter_labels(root)
    patch_am_effect_application_enable(root)
    print("Default interface language set to Simplified Chinese.")
    print("Added one-tap access to the original native Puppet Position Pin tool.")
    print("Added long-press project grouping and folder ungrouping.")
    print("Added a keyframe button restricted to one selected project item and its matching layer.")


if __name__ == "__main__":
    main()
