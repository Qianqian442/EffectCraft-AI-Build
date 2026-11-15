#!/usr/bin/env python3
"""Make the expanded Ae AI assistant nearly full-screen while keeping its title bar draggable."""
from __future__ import annotations

import os
import re
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_AI_EXPANDED_DRAG_V2"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if new in source:
        return source
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/ai_assistant.rs"
    if not path.is_file():
        raise SystemExit("The generated Ae AI assistant source is missing")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Ae AI assistant expanded draggable window is already installed.")
        return

    source = replace_once(
        source,
        "    bubble_drag_origin: Option<egui::Pos2>,\n",
        "    bubble_drag_origin: Option<egui::Pos2>,\n    full_screen: bool,\n",
        "AI assistant expanded-window state",
    )
    source = replace_once(
        source,
        "            bubble_drag_origin: None,\n",
        "            bubble_drag_origin: None,\n            full_screen: false,\n",
        "AI assistant expanded-window default",
    )
    source = replace_once(
        source,
        "    let mut manage_model = false;\n    let mut window_open = state.open;\n",
        "    let mut manage_model = false;\n    let mut toggle_full_screen = false;\n    let mut window_open = state.open;\n",
        "AI assistant expanded-window toggle state",
    )

    pattern = re.compile(
        r'    egui::Window::new\("Ae AI 助手"\).*?'
        r'        \.show\(&ctx, \|ui\| \{\n',
        re.S,
    )
    replacement = """    // Use separate egui IDs for the compact and expanded layouts so switching
    // back restores the user's previous compact-window position and size.
    let window_id = if state.full_screen {
        Id::new("effectcraft-ai-chat-window-expanded")
    } else {
        Id::new("effectcraft-ai-chat-window")
    };
    let mut chat_window = egui::Window::new("Ae AI 助手")
        .id(window_id)
        .order(Order::Foreground)
        .movable(true)
        .constrain_to(screen)
        .default_pos(pos2(
            (screen.max.x - 350.0).max(screen.min.x + 8.0),
            (screen.max.y - 560.0).max(screen.min.y + 8.0),
        ))
        .default_size(vec2(330.0, 450.0))
        .min_size(vec2(280.0, 300.0))
        .max_size(screen.size())
        .resizable(true);
    if state.full_screen {
        // Large, but not position-locked: the title bar remains a drag handle.
        let expanded_size = vec2(
            (screen.width() - 16.0).max(240.0),
            (screen.height() - 16.0).max(300.0),
        );
        chat_window = chat_window
            .default_pos(pos2(screen.min.x + 8.0, screen.min.y + 8.0))
            .default_size(expanded_size)
            .min_size(expanded_size)
            .max_size(screen.size())
            .movable(true)
            .resizable(false);
    }
    chat_window
        .open(&mut window_open)
        .show(&ctx, |ui| {
"""
    source, count = pattern.subn(replacement, source, count=1)
    if count != 1:
        raise SystemExit(f"AI assistant window builder: expected one draggable window block, found {count}")

    # Attach expand/restore to the persistent chat composer, not to a localized status label.
    composer_anchor = """                .desired_rows(2),
            );
"""
    composer_replacement = composer_anchor + """            if ui.button(if state.full_screen { "还原窗口" } else { "展开页面" }).clicked() {
                toggle_full_screen = true;
            }
"""
    source = replace_once(source, composer_anchor, composer_replacement, "AI assistant expanded-page control beside chat input")
    source = replace_once(
        source,
        "    state.open = window_open;\n",
        "    state.open = window_open;\n    if toggle_full_screen {\n        state.full_screen = !state.full_screen;\n    }\n",
        "AI assistant expanded-page transition",
    )

    source = source.replace(
        "pub(crate) fn show(app: &mut EffectcraftApp, root: &mut egui::Ui) {",
        "/// " + MARKER + "\npub(crate) fn show(app: &mut EffectcraftApp, root: &mut egui::Ui) {",
        1,
    )
    path.write_text(source, encoding="utf-8")
    final = path.read_text(encoding="utf-8")
    if MARKER not in final or '.movable(true)' not in final or "展开页面" not in final:
        raise SystemExit("Expanded draggable AI assistant verification failed.")
    print("Ae AI assistant now opens as a large page that remains draggable from its title bar.")
    print("The compact window's previous size and position are preserved when returning from the expanded page.")


if __name__ == "__main__":
    main()
