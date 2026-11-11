#!/usr/bin/env python3
"""Keep one top-left unified plug-in import entry and reuse the original loader."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_PLUGIN_IMPORT_BUTTON_V1"
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
/// One compact top-left entry routes both WASM effects and the DeepSeek ZIP.
fn plugin_import_button(app: &mut EffectcraftApp, ui: &mut egui::Ui, x: f32, cy: f32) -> f32 {
    let rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(78.0, 26.0));
    let menu_id = egui::Id::new("effectcraft-plugin-import-menu");
    let mut menu_open = ui.ctx().data(|d| d.get_temp::<bool>(menu_id).unwrap_or(false));
    let response = ui
        .put(rect, egui::Button::new("导入插件"))
        .on_hover_text("导入 WASM/WAT、AE 原生插件文件、ZIP/ZXP 包或 DeepSeek AI ZIP");
    app.auto.add_response("header.importPlugin", &response, "Import Plug-in");
    widgets::focus_outline(ui, &response, &app.tokens);
    if response.clicked() {
        menu_open = !menu_open;
    }

    let mut import_wasm = false;
    let mut import_ai = false;
    let mut import_folder = false;
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
                if popup.button("WASM / WAT / AE 插件文件或包").clicked() {
                    import_wasm = true;
                }
                if popup.button("AE 插件文件夹 / macOS .plugin").clicked() {
                    import_folder = true;
                }
                if popup.button("DeepSeek AI 插件 ZIP").clicked() {
                    import_ai = true;
                }
                popup.label("电脑版 AE 原生插件 .aex 不能直接在 Android 运行");
                popup.label(".aep / .aepx 是 AE 工程文件，请用“导入工程”，不要走“开始移植”。");
                popup.label("支持直接选择 .aex/.dll/.ofx 原生文件、ZIP/ZXP 包；不会按名称匹配替代。");
                if popup.button("关闭").clicked() {
                    close_menu = true;
                }
            });
        menu_open = popup_open && !close_menu && !import_wasm && !import_ai && !import_folder;
    }
    ui.ctx().data_mut(|d| d.insert_temp(menu_id, menu_open));

    if import_wasm
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "effect.plugins.load", json!({}))
    {
        app.ui.status = error;
    }
    if import_folder
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "effect.plugins.loadFolder", json!({}))
    {
        app.ui.status = error;
    }
    if import_ai {
        match crate::open_ai_plugin_import_from_toolbar() {
            Ok(()) => app.ui.status = "请选择 DeepSeek AI 插件 ZIP；随后按 Android 系统提示确认安装。".into(),
            Err(error) => app.ui.status = error,
        }
    }
    x + 84.0
}

'''
    source = source.replace(function_anchor, helper + function_anchor, 1)
    header_path.write_text(source, encoding="utf-8")
    print("Added the top-left 导入插件 button.")
    print("The button calls effect.plugins.load, reusing the original WASM loader and Android file picker.")


if __name__ == "__main__":
    main()
