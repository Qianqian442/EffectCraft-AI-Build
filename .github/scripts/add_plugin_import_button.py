#!/usr/bin/env python3
"""Keep one top-left WASM plug-in import entry and reuse the original loader."""
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
/// A persistent import entry beside the app logo and Home button, at the far left of the Tools bar.
/// It deliberately invokes the existing engine command so Android's SAF picker and the original
/// Wasmi loader remain the single source of truth.
fn plugin_import_button(app: &mut EffectcraftApp, ui: &mut egui::Ui, x: f32, cy: f32) -> f32 {
    let rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(78.0, 26.0));
    let response = ui
        .put(rect, egui::Button::new("导入插件"))
        .on_hover_text("选择 .wasm 或 .wat 插件文件");
    app.auto.add_response("header.importPlugin", &response, "Import Effect Plug-in");
    widgets::focus_outline(ui, &response, &app.tokens);
    if response.clicked()
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "effect.plugins.load", json!({}))
    {
        app.ui.status = error;
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
