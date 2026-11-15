#!/usr/bin/env python3
"""Add a fullscreen control and keep AI assistant content buttons tappable on touch screens."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_AI_FULLSCREEN_DRAG_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/ai_assistant.rs"
    if not path.is_file():
        raise SystemExit("The generated AI assistant source is missing")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("AI assistant fullscreen and touch-safe drag are already installed.")
        return

    source = replace_once(
        source,
        "    bubble_drag_origin: Option<egui::Pos2>,\n",
        "    bubble_drag_origin: Option<egui::Pos2>,\n    full_screen: bool,\n    restore_rect: Option<egui::Rect>,\n",
        "AI assistant fullscreen state",
    )
    source = replace_once(
        source,
        "            bubble_drag_origin: None,\n",
        "            bubble_drag_origin: None,\n            full_screen: false,\n            restore_rect: None,\n",
        "AI assistant fullscreen defaults",
    )
    source = replace_once(
        source,
        "    let mut manage_model = false;\n    let mut window_open = state.open;\n",
        """    let mut manage_model = false;
    let mut toggle_full_screen = false;
    let mut window_open = state.open;
    let window_id = Id::new("effectcraft-ai-chat-window");
    // Save the last normal window rectangle before changing to full-screen size.
    let normal_rect_before = ctx.memory(|memory| memory.area_rect(window_id)).or_else(|| {
        let size = vec2((screen.width() - 16.0).clamp(240.0, 520.0),
                        (screen.height() - 24.0).clamp(280.0, 860.0));
        Some(egui::Rect::from_min_size(
            pos2(screen.center().x - size.x * 0.5, screen.center().y - size.y * 0.5),
            size,
        ))
    });
    let restore_for_frame = state.restore_rect;
""",
        "AI assistant fullscreen pre-window state",
    )

    old_window = """    egui::Window::new("EffectCraft AI 助手")
        .id(Id::new("effectcraft-ai-chat-window"))
        .order(Order::Foreground)
        .movable(true)
        .default_pos(pos2(
            (screen.max.x - 350.0).max(screen.min.x + 8.0),
            (screen.max.y - 560.0).max(screen.min.y + 8.0),
        ))
        .default_size(vec2(330.0, 450.0))
        .min_size(vec2(280.0, 300.0))
        .resizable(true)
        .open(&mut window_open)
        .show(&ctx, |ui| {
            ui.label("DeepSeek 本地推理 · 已集成在当前 APK");
"""
    new_window = """    // Only the title bar moves the chat window. On touch screens this keeps buttons,
    // text input and scrolling inside the window from being interpreted as a window drag.
    let mut chat_window = egui::Window::new("EffectCraft AI 助手")
        .id(window_id)
        .order(Order::Foreground)
        .movable(true)
        .drag_area(egui::WindowDrag::TitleBar)
        .constrain_to(screen)
        .default_pos(pos2(
            (screen.max.x - 350.0).max(screen.min.x + 8.0),
            (screen.max.y - 560.0).max(screen.min.y + 8.0),
        ))
        .default_size(vec2((screen.width() - 16.0).clamp(240.0, 520.0),
                           (screen.height() - 24.0).clamp(280.0, 860.0)))
        .min_size(vec2(220.0, 260.0))
        .max_size(screen.size())
        .resizable(true);
    if state.full_screen {
        chat_window = chat_window.fixed_rect(screen).movable(false).resizable(false);
    } else if let Some(rect) = restore_for_frame {
        chat_window = chat_window.fixed_rect(rect).movable(true).resizable(true);
    }
    chat_window
        .open(&mut window_open)
        .show(&ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label("DeepSeek 本地推理 · 已集成在当前 APK");
                if ui.button(if state.full_screen { "还原窗口" } else { "全屏" }).clicked() {
                    toggle_full_screen = true;
                }
            });
"""
    source = replace_once(source, old_window, new_window, "AI assistant window builder")
    source = replace_once(
        source,
        """    state.open = window_open;
    if manage_model {""",
        """    state.open = window_open;
    if toggle_full_screen {
        if state.full_screen {
            state.full_screen = false;
        } else {
            state.restore_rect = normal_rect_before;
            state.full_screen = true;
        }
    } else if !state.full_screen && restore_for_frame.is_some() {
        state.restore_rect = None;
    }
    if manage_model {""",
        "AI assistant fullscreen transition",
    )
    source = source.replace(
        "pub(crate) fn show(app: &mut EffectcraftApp, root: &mut egui::Ui) {",
        "/// EFFECTCRAFT_ANDROID_AI_FULLSCREEN_DRAG_V1\npub(crate) fn show(app: &mut EffectcraftApp, root: &mut egui::Ui) {",
        1,
    )
    path.write_text(source, encoding="utf-8")
    print("Added full-screen/restore mode and title-bar-only chat-window dragging.")


if __name__ == "__main__":
    main()
