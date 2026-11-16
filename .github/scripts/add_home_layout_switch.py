#!/usr/bin/env python3
"""Add a Nova-style Home layout chooser and remove the obsolete repository link."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_HOME_LAYOUT_MENU_NOVA_V3"


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
        print("Home Nova-style layout chooser is already installed.")
        return

    # Remove only the obsolete code-repository shortcut; preserve other Home links.
    github_entry = '        (Icon::Code, "EffectCraft on GitHub", "help.github"),\n'
    if github_entry in source:
        source = source.replace(github_entry, "", 1)
    elif '"EffectCraft on GitHub"' in source or '"help.github"' in source:
        raise SystemExit("The Home GitHub link changed unexpectedly; refusing an unsafe partial removal.")

    anchor = '''        app.auto.add(&format!("home.{id}"), r, label);
        y += 42.0;
    }
'''
    replacement = '''        app.auto.add(&format!("home.{id}"), r, label);
        y += 42.0;

        // EFFECTCRAFT_HOME_LAYOUT_MENU_NOVA_V3
        // Place the layout chooser directly after New Project. It does not rely on an
        // Open Project button being present or visible on the user's Home screen.
        if id == "file.newProject" {
            let layout_menu_id = egui::Id::new("home-layout-menu");
            let active_layout = if app.ui.workspace == "Standard" {
                "Ae 原布局".to_string()
            } else {
                app.ui.workspace.clone()
            };
            let switch_label = format!("布局 ▾  ·  {active_layout}");
            let switch_rect = Rect::from_min_size(pos2(x0, y), vec2(w, 36.0));
            if widgets::text_button(ui, switch_rect, &switch_label, true, &t, egui::Id::new("home-layout-switch")).clicked() {
                widgets::open_popup(ui, layout_menu_id);
            }
            app.auto.add("home.layout.switch", switch_rect, "布局选择");
            let workspace_names = app.workspace_names();
            let workspace_labels: Vec<String> = workspace_names.iter().map(|name| {
                if name == "Standard" { "Ae 原布局".to_string() } else { name.clone() }
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
            y += 44.0;
        }
    }
'''
    source = replace_once(source, anchor, replacement, "Home layout chooser immediately below New Project")
    path.write_text(source, encoding="utf-8")
    print("Added the Nova-style Home layout chooser directly below New Project.")
    print("Removed the EffectCraft GitHub/code-repository shortcut from the Home page.")


if __name__ == "__main__":
    main()
