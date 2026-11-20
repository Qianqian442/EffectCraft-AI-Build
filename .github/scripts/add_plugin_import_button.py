#!/usr/bin/env python3
"""Keep one top-left unified plug-in import entry and reuse the original loader."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_PLUGIN_IMPORT_BUTTON_V3"
MENU_MARKER = "EFFECTCRAFT_ANDROID_SINGLE_PLUGIN_IMPORT_ENTRY_V1"


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")

    # Keep the requested top-left button as the sole manual import entry.
    # Remove only the duplicate Effect-menu row; the original command, picker, runtime,
    # plug-in list API, and startup folder scan remain intact.
    menu_path = root / "crates/engine/src/menus.rs"
    if not menu_path.is_file():
        raise SystemExit(f"EffectCraft menu source was not found: {menu_path}")
    menu_source = menu_path.read_text(encoding="utf-8")
    if MENU_MARKER not in menu_source:
        duplicate_entry = "  Load Effect Plug-in... | effect.plugins.load\n"
        if menu_source.count(duplicate_entry) != 1:
            raise SystemExit("Could not uniquely locate the original Effect-menu plug-in row; refusing to patch.")
        menu_source = menu_source.replace(duplicate_entry, "", 1)
        tree_anchor = 'pub const TREE: &str = r#"'
        if menu_source.count(tree_anchor) != 1:
            raise SystemExit("Could not uniquely locate the original menu tree; refusing to mark the change.")
        menu_source = menu_source.replace(tree_anchor, f"// {MENU_MARKER}\n{tree_anchor}", 1)
        menu_path.write_text(menu_source, encoding="utf-8")
        print("Removed the duplicate Effect-menu plug-in import row; original loader command is preserved.")
    else:
        print("The Effect-menu duplicate import row is already removed.")

    header_path = root / "crates/ui-egui/src/header.rs"
    if not header_path.is_file():
        raise SystemExit(f"EffectCraft toolbar source was not found: {header_path}")
    source = header_path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Top-left WASM plug-in import button is already present.")
        return

    call_anchor = (
        "    let x = brand_and_home(app, ui, &p, x, cy);\n"
        "    let x = tool_slots(app, ui, &p, x, cy);"
    )
    if source.count(call_anchor) != 1:
        raise SystemExit("Could not uniquely locate the EffectCraft toolbar layout; refusing to patch.")

    call_replacement = (
        "    let x = brand_and_home(app, ui, &p, x, cy);\n"
        "    let x = plugin_import_button(app, ui, x, cy);\n"
        "    let x = tool_slots(app, ui, &p, x, cy);"
    )
    source = source.replace(call_anchor, call_replacement, 1)

    function_anchor = "/// The tool slots (with group separators after camera tools and pan-behind); returns the x after them.\n"
    if source.count(function_anchor) != 1:
        raise SystemExit("Could not uniquely locate the toolbar helper insertion point; refusing to patch.")

    helper = '''/// EFFECTCRAFT_ANDROID_PLUGIN_IMPORT_BUTTON_V1
/// EFFECTCRAFT_ANDROID_PLUGIN_IMPORT_MENU_V1
/// 一个顶部入口用于导入效果插件和电脑插件。AI 模型统一从模型管理导入或下载。
fn plugin_import_button(app: &mut EffectcraftApp, ui: &mut egui::Ui, x: f32, cy: f32) -> f32 {
    let rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(78.0, 26.0));
    let menu_id = egui::Id::new("effectcraft-plugin-import-menu");
    let mut menu_open = ui.ctx().data(|d| d.get_temp::<bool>(menu_id).unwrap_or(false));
    let response = ui
        .put(rect, egui::Button::new("导入插件"))
        .on_hover_text("导入效果插件包或电脑插件文件；AI 插件和模型请前往模型管理");
    app.auto.add_response("header.importPlugin", &response, "导入插件");
    widgets::focus_outline(ui, &response, &app.tokens);
    if response.clicked() {
        menu_open = !menu_open;
    }

    let mut import_wasm = false;
    let mut import_desktop_advanced = false;
    if menu_open {
        let mut popup_open = true;
        let mut close_menu = false;
        egui::Window::new("导入插件")
            .id(menu_id.with("popup"))
            .order(egui::Order::Foreground)
            .default_pos(rect.left_bottom() + vec2(0.0, 4.0))
            .movable(false)
            .collapsible(false)
            .resizable(false)
            .title_bar(false)
            .open(&mut popup_open)
            .show(ui.ctx(), |popup| {
                popup.label("选择插件类型");
                if popup.button("导入效果插件包（支持 .wasm、.wat、.zip）").clicked() {
                    import_wasm = true;
                }
                if popup.button("电脑插件高级移植（自动比较完整度 + 强制兼容）").clicked() {
                    import_desktop_advanced = true;
                }
                popup.label("高级移植会识别电脑插件架构，列出适用的 ARM64 转译路线和强制兼容方案。");
                popup.label("只有实际运行并通过测试的方案才能标记为已移植；当前未接入的后端会明确显示待实现。");
                popup.label(".aex / .dll / .ofx / .8bf / .prm 等电脑插件可选单文件或 ZIP；.aep / .aepx 是工程文件，请用“导入工程”。");
                if popup.button("关闭").clicked() {
                    close_menu = true;
                }
            });
        menu_open = popup_open && !close_menu && !import_wasm && !import_desktop_advanced;
    }
    ui.ctx().data_mut(|d| d.insert_temp(menu_id, menu_open));

    if (import_wasm || import_desktop_advanced)
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "effect.plugins.load", json!({}))
    {
        app.ui.status = error;
    }
    if import_desktop_advanced {
        app.ui.status = "已打开电脑插件高级移植选择器：将分析架构、转译候选、宿主接口和强制兼容方案；未实测的路线不会标记为成功。".into();
    }
    x + 84.0
}

'''
    source = source.replace(function_anchor, helper + function_anchor, 1)
    header_path.write_text(source, encoding="utf-8")
    print("Added the top-left 导入插件 button.")
    print("The menu now includes a dedicated desktop plug-in advanced migration entry.")
    print("Advanced migration reuses the native picker/interceptor and reports architecture, candidate translation routes, host API requirements and force-compatibility profiles.")
    print("AI plug-in ZIP import and model downloads are intentionally handled only by the in-app 模型管理 screen.")


if __name__ == "__main__":
    main()
