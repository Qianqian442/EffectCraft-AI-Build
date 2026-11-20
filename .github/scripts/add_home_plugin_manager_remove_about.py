#!/usr/bin/env python3
"""Add a Home plug-in manager beside account management and remove the About Ae UI."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_HOME_PLUGIN_MANAGER_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


PLUGIN_MANAGER_FN = r'''
// EFFECTCRAFT_HOME_PLUGIN_MANAGER_V1
/// Home-page plug-in manager. Lists the engine's registered effects and routes supported
/// effect/desktop plug-in files through the existing, sandboxed importer.
fn show_home_plugin_manager(app: &mut EffectcraftApp, ctx: &egui::Context, open: &mut bool) {
    let cache_id = Id::new("effectcraft-home-plugin-manager-cache");
    let mut data = ctx.data(|d| d.get_temp::<Value>(cache_id).unwrap_or(Value::Null));
    let mut refresh = data.is_null();
    let mut import_effects = false;
    let mut import_desktop = false;

    egui::Window::new("主页插件管理")
        .id(Id::new("effectcraft-home-plugin-manager-window"))
        .order(Order::Foreground)
        .default_size((430.0, 500.0))
        .min_size((300.0, 260.0))
        .movable(true)
        .collapsible(false)
        .resizable(true)
        .open(open)
        .show(ctx, |ui| {
            ui.label("查看 Ae 当前已加载的效果插件，并从这里导入新的插件。");
            ui.horizontal_wrapped(|ui| {
                if ui.button("导入效果插件").clicked() {
                    import_effects = true;
                }
                if ui.button("导入电脑插件 / 高级移植").clicked() {
                    import_desktop = true;
                }
                if ui.button("刷新列表").clicked() {
                    refresh = true;
                }
            });
            ui.separator();
            if data.is_null() {
                ui.spinner();
                ui.label("正在读取插件列表…");
            } else if let Some(error) = data.get("error").and_then(Value::as_str) {
                ui.colored_label(egui::Color32::LIGHT_RED, error);
            } else {
                let plugins = data.get("plugins").and_then(Value::as_array);
                let count = plugins.map_or(0, |items| items.len());
                ui.strong(format!("已注册效果插件：{count} 个"));
                if data.get("wasm").and_then(Value::as_bool) == Some(false) {
                    ui.small("当前构建未启用 WASM 插件加载器；内置插件仍可显示。");
                }
                egui::ScrollArea::vertical().max_height(ui.available_height()).show(ui, |ui| {
                    match plugins {
                        Some(items) if !items.is_empty() => {
                            for plugin in items {
                                ui.group(|ui| {
                                    let name = plugin.get("name").and_then(Value::as_str).unwrap_or("未命名插件");
                                    ui.strong(name);
                                    if let Some(id) = plugin.get("id").and_then(Value::as_str) {
                                        ui.small(format!("ID：{id}"));
                                    }
                                    let category = plugin.get("category").and_then(Value::as_str).unwrap_or("未分类");
                                    let version = plugin.get("version").and_then(Value::as_str).unwrap_or("未知版本");
                                    let author = plugin.get("author").and_then(Value::as_str).unwrap_or("未知作者");
                                    ui.small(format!("分类：{category}  ·  版本：{version}  ·  作者：{author}"));
                                    if let Some(source) = plugin.get("source").and_then(Value::as_str) {
                                        ui.small(format!("来源：{source}"));
                                    }
                                    if let Some(description) = plugin.get("description").and_then(Value::as_str) {
                                        if !description.is_empty() {
                                            ui.label(description);
                                        }
                                    }
                                    let params = plugin.get("params").and_then(Value::as_array).map_or(0, |items| items.len());
                                    ui.small(format!("可调参数：{params} 项"));
                                });
                                ui.add_space(4.0);
                            }
                        }
                        _ => {
                            ui.label("暂未发现已注册的效果插件。可通过上方按钮导入插件。");
                        }
                    }
                });
            }
            ui.separator();
            ui.small("AI 插件包导入和本地模型下载统一在 AI 助手的“模型管理”中进行；这里不提供 AI 插件 ZIP 入口。");
            ui.small("电脑原生插件会先进行架构分析和路线选择；未通过真实转译与渲染测试的文件不会被标记为已移植。");
        });

    if refresh {
        data = match app.session.execute("effect.plugins.list", json!({})) {
            Ok(value) => value,
            Err(error) => json!({"error": error.to_string(), "plugins": []}),
        };
    }
    if import_effects || import_desktop {
        match crate::menus::invoke(app, ctx, "effect.plugins.load", json!({})) {
            Ok(_) => {
                data = Value::Null;
                app.ui.status = if import_desktop {
                    "已打开电脑插件导入；将进入架构分析和高级移植路线选择。".into()
                } else {
                    "已打开效果插件导入。".into()
                };
            }
            Err(error) => app.ui.status = error,
        }
    }
    ctx.data_mut(|d| d.insert_temp(cache_id, data));
}
'''


def remove_once(source: str, old: str, label: str) -> str:
    count = source.count(old)
    if count == 0:
        return source
    if count != 1:
        raise SystemExit(f"{label}: expected one removal target, found {count}")
    return source.replace(old, "", 1)


def patch_home_account_ui(account_path: Path) -> None:
    source = account_path.read_text(encoding="utf-8")
    if MARKER not in source:
        old = '''        if app.ui.start_screen {
            egui::Area::new(Id::new("effectcraft-home-account-button"))
                .order(Order::Foreground)
                .anchor(Align2::RIGHT_TOP, vec2(-12.0, 12.0))
                .show(ctx, |ui| {
                    if ui.button("账号信息").clicked() {
                        if let Some(user) = app.account.user.as_ref() {
                            app.account.edit_qq = user.qq.clone();
                            app.account.edit_wechat = user.wechat.clone();
                            app.account.edit_name = user.name.clone();
                            app.account.edit_avatar = user.avatar_url.clone();
                            app.account.edit_open = true;
                        }
                    }
                });
        } else {'''
        new = '''        let plugin_manager_id = Id::new("effectcraft-home-plugin-manager-open");
        let mut plugin_manager_open = ctx.data(|d| d.get_temp::<bool>(plugin_manager_id).unwrap_or(false));
        if app.ui.start_screen {
            egui::Area::new(Id::new("effectcraft-home-account-button"))
                .order(Order::Foreground)
                .anchor(Align2::RIGHT_TOP, vec2(-12.0, 12.0))
                .show(ctx, |ui| {
                    ui.horizontal(|ui| {
                        if ui.button("账号管理").clicked() {
                            if let Some(user) = app.account.user.as_ref() {
                                app.account.edit_qq = user.qq.clone();
                                app.account.edit_wechat = user.wechat.clone();
                                app.account.edit_name = user.name.clone();
                                app.account.edit_avatar = user.avatar_url.clone();
                                app.account.edit_open = true;
                            }
                        }
                        if ui.button("插件管理").clicked() {
                            plugin_manager_open = true;
                        }
                    });
                });
            if plugin_manager_open {
                show_home_plugin_manager(app, ctx, &mut plugin_manager_open);
            }
            ctx.data_mut(|d| d.insert_temp(plugin_manager_id, plugin_manager_open));
        } else {'''
        source = replace_once(source, old, new, "home account/plugin toolbar")
    if "fn show_home_plugin_manager(" not in source:
        source = replace_once(
            source,
            "pub(crate) fn show(app: &mut EffectcraftApp, ctx: &egui::Context) {",
            PLUGIN_MANAGER_FN + "\npub(crate) fn show(app: &mut EffectcraftApp, ctx: &egui::Context) {",
            "home plug-in manager function",
        )
    account_path.write_text(source, encoding="utf-8")


def remove_about_ui(root: Path) -> None:
    ui = root / "crates/ui-egui/src"
    header = ui / "header.rs"
    source = header.read_text(encoding="utf-8")
    source = source.replace(
        "/// The brand mark (About) and the Home button; returns the x after them.",
        "/// The decorative Ae brand mark and the Home button; returns the x after them.",
    )
    about_click = '''    let bresp = ui.interact(brand, egui::Id::unique("brand"), Sense::click());
    app.auto.add_response("header.about", &bresp, "About EffectCraft");
    widgets::focus_outline(ui, &bresp, &t);
    if bresp.on_hover_text(tr("About EffectCraft")).clicked() {
        app.dialog = Some(Dialog::About);
    }
'''
    source = replace_once(
        source,
        about_click,
        "    // The logo is decorative; the former About click target and dialog are removed.\n",
        "About logo click target",
    )
    source = source.replace("/// Draws the Tools bar into rect: brand (About), Home,", "/// Draws the Tools bar into rect: brand mark, Home,")
    source = source.replace("/// 24 px Tools bar to the About dialog). Nothing is drawn if it can't be decoded.",
                          "/// 24 px Tools bar to larger interface surfaces). Nothing is drawn if it can't be decoded.")
    header.write_text(source, encoding="utf-8")

    lib = ui / "lib.rs"
    source = lib.read_text(encoding="utf-8")
    source = remove_once(source, "    About,\n", "About dialog enum variant")
    lib.write_text(source, encoding="utf-8")

    frontend = ui / "menus/frontend.rs"
    source = frontend.read_text(encoding="utf-8")
    source = remove_once(
        source,
        '''        "app.about" => {
            app.dialog = Some(crate::Dialog::About);
            Value::Null
        }
''',
        "About command handler",
    )
    frontend.write_text(source, encoding="utf-8")

    dialogs = ui / "panels/dialogs.rs"
    source = dialogs.read_text(encoding="utf-8")
    source = remove_once(source, "        Dialog::About => about(app, ctx, &t),\n", "About dialog dispatch")
    start = source.find("/// About tabs: About · Contributors · Models.")
    end = source.find("\nfn comp_settings(", start)
    if start < 0 or end < 0:
        raise SystemExit("About dialog implementation range was not found.")
    source = source[:start] + source[end + 1:]
    source = source.replace(
        "//! Modal dialogs: About (community links, Contributors and Models credits), New Composition /",
        "//! Modal dialogs: New Composition /",
    )
    dialogs.write_text(source, encoding="utf-8")

    engine_menus = root / "crates/engine/src/menus.rs"
    source = engine_menus.read_text(encoding="utf-8")
    source = remove_once(source, "  About EffectCraft... | app.about\n", "macOS About menu")
    source = remove_once(source, "  [!mac] About EffectCraft... | app.about\n", "non-macOS About menu")
    engine_menus.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    account_path = root / "crates/ui-egui/src/account.rs"
    required = [
        account_path,
        root / "crates/ui-egui/src/header.rs",
        root / "crates/ui-egui/src/lib.rs",
        root / "crates/ui-egui/src/menus/frontend.rs",
        root / "crates/ui-egui/src/panels/dialogs.rs",
        root / "crates/engine/src/menus.rs",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing required EffectCraft source files: " + ", ".join(missing))
    patch_home_account_ui(account_path)
    remove_about_ui(root)
    account_source = account_path.read_text(encoding="utf-8")
    header_source = (root / "crates/ui-egui/src/header.rs").read_text(encoding="utf-8")
    dialogs_source = (root / "crates/ui-egui/src/panels/dialogs.rs").read_text(encoding="utf-8")
    frontend_source = (root / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    menus_source = (root / "crates/engine/src/menus.rs").read_text(encoding="utf-8")
    if "账号管理" not in account_source or "插件管理" not in account_source or "effect.plugins.list" not in account_source:
        raise SystemExit("Home plug-in manager controls or list command were not installed.")
    if "Dialog::About" in dialogs_source or "fn about(" in dialogs_source or '"app.about"' in frontend_source:
        raise SystemExit("About dialog functionality is still reachable.")
    if "app.about" in menus_source or "header.about" in header_source:
        raise SystemExit("About menu or header action is still present.")
    print("Added Home plug-in management beside account management and verified the registered plug-in list/import actions.")
    print("Removed the About Ae logo hit target, Dialog::About implementation, command handler and menu entries.")


if __name__ == "__main__":
    main()
