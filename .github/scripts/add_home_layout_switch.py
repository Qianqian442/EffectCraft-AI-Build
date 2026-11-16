#!/usr/bin/env python3
"""Add a Nova-style layout selector directly to the Home screen surface."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_HOME_LAYOUT_SURFACE_MENU_V4"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/panels/home.rs"
    if not path.is_file():
        raise SystemExit(f"EffectCraft Home panel source is missing: {path}")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Home-surface Nova-style layout selector is already installed.")
        return

    # Remove only the obsolete Home code-repository shortcut; do not change other Home links.
    github_entry = '        (Icon::Code, "EffectCraft on GitHub", "help.github"),\n'
    if github_entry in source:
        source = source.replace(github_entry, "", 1)
    elif '"EffectCraft on GitHub"' in source or '"help.github"' in source:
        raise SystemExit("The Home GitHub link changed unexpectedly; refusing an unsafe partial removal.")

    show_anchor = '''    run_actions(app, &ctx, actions);
}'''
    replacement = '''    // EFFECTCRAFT_HOME_LAYOUT_SURFACE_MENU_V4
    // Draw on the actual Home surface, independent of any New/Open Project controls in the rail.
    let layout_menu_id = egui::Id::new("home-surface-layout-menu");
    let active_layout = if app.ui.workspace == "Standard" {
        "Ae 原布局".to_string()
    } else if app.ui.workspace == "AM 竖屏" {
        "AM 竖屏".to_string()
    } else {
        app.ui.workspace.clone()
    };
    let layout_label = format!("布局 ▾  ·  {active_layout}");
    let switch_rect = Rect::from_min_size(
        pos2((rect.max.x - 186.0).max(rect.min.x + 8.0), rect.min.y + 8.0),
        vec2((rect.width() - 16.0).clamp(132.0, 178.0), 34.0),
    );
    if widgets::text_button(
        ui,
        switch_rect,
        &layout_label,
        true,
        &t,
        egui::Id::new("home-surface-layout-switch"),
    ).clicked() {
        widgets::open_popup(ui, layout_menu_id);
    }
    app.auto.add("home.layout.surface.switch", switch_rect, "Home layout selector");

    let workspace_names = app.workspace_names();
    let workspace_labels: Vec<String> = workspace_names.iter().map(|name| {
        match name.as_str() {
            "Standard" => "Ae 原布局".to_string(),
            "AM 竖屏" => "AM 竖屏".to_string(),
            _ => crate::i18n::command_label("window.workspace", name).to_string(),
        }
    }).collect();
    let selected_layout = workspace_names.iter().position(|name| name == &app.ui.workspace);
    if let Some(index) = widgets::popup_menu(
        ui,
        layout_menu_id,
        switch_rect.left_bottom(),
        &workspace_labels,
        selected_layout,
    ) {
        if let Some(target_workspace) = workspace_names.get(index) {
            app.set_workspace(target_workspace);
            app.ui.start_screen = false;
            app.ui.home_learn = false;
            app.ui.home_templates = false;
        }
    }

    run_actions(app, &ctx, actions);
}'''
    source = replace_once(source, show_anchor, replacement, "actual Home surface layout selector")
    path.write_text(source, encoding="utf-8")
    print("Added the Nova-style layout menu to the Home surface top-right corner, independent of project buttons.")
    print("Removed the EffectCraft GitHub/code-repository shortcut from the Home page.")


if __name__ == "__main__":
    main()
