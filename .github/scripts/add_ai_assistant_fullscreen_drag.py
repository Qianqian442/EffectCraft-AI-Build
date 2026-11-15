#!/usr/bin/env python3
"""Add full-screen and reliable touch-drag controls to the AI assistant chat window."""
from __future__ import annotations

import os
import re
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_AI_FULLSCREEN_DRAG_V1"


def add_state_fields(source: str) -> str:
    match = re.search(r"(?:pub\(crate\)\s+)?struct State\s*\{", source)
    if not match:
        raise SystemExit("AI assistant State struct was not found.")
    end = source.find("\n}", match.end())
    if end < 0:
        raise SystemExit("AI assistant State struct closing brace was not found.")
    block = source[match.end():end]
    fields = (
        ("chat_fullscreen", "    chat_fullscreen: bool,"),
        ("chat_position", "    chat_position: Option<egui::Pos2>,"),
        ("chat_drag_origin", "    chat_drag_origin: Option<egui::Pos2>,"),
    )
    missing = [declaration for name, declaration in fields if not re.search(r"\b" + name + r"\s*:", block)]
    if missing:
        source = source[:end] + "\n" + "\n".join(missing) + source[end:]

    default_start = source.find("impl Default for State")
    show_start = source.find("pub(crate) fn show", default_start)
    if default_start < 0 or show_start < 0:
        raise SystemExit("AI assistant Default/show methods were not found.")
    default_block = source[default_start:show_start]
    init_fields = (
        ("chat_fullscreen", "            chat_fullscreen: false,"),
        ("chat_position", "            chat_position: None,"),
        ("chat_drag_origin", "            chat_drag_origin: None,"),
    )
    missing_init = [declaration for name, declaration in init_fields if not re.search(r"\b" + name + r"\s*:", default_block)]
    if missing_init:
        close = default_block.rfind("\n        }")
        if close < 0:
            raise SystemExit("Could not find the State default initializer closing brace.")
        absolute = default_start + close
        source = source[:absolute] + "\n" + "\n".join(missing_init) + source[absolute:]
    return source


def patch_avatar_fallback(source: str) -> str:
    # The embedded PNG is expected to be valid, but a decode failure should not panic the app.
    for variable, message in (
        ("AVATAR_PNG", "embedded Ae avatar PNG must decode"),
        ("AVATAR_PNG", "embedded AI avatar must decode"),
        ("AVATAR", "embedded AI avatar must decode"),
    ):
        pattern = r'(image::load_from_memory\(' + variable + r'\))\s*\.expect\("' + re.escape(message) + r'"\)'
        fallback = r'\1.unwrap_or_else(|_| image::DynamicImage::ImageRgba8(image::RgbaImage::from_pixel(48, 48, image::Rgba([42, 105, 210, 255]))))'
        source, count = re.subn(pattern, fallback, source, count=1)
        if count:
            break
    return source


def patch_window(source: str) -> str:
    if MARKER in source:
        return source
    old = re.compile(
        r'    let mut window_open = state\.open;\n'
        r'    egui::Window::new\("EffectCraft AI 助手"\)\n'
        r'        \.id\(Id::new\("effectcraft-ai-chat-window"\)\)\n'
        r'        \.order\(Order::Foreground\)\n'
        r'        \.movable\(true\)\n'
        r'        \.default_pos\(pos2\(\n'
        r'            \(screen\.max\.x - 350\.0\)\.max\(screen\.min\.x \+ 8\.0\),\n'
        r'            \(screen\.max\.y - 560\.0\)\.max\(screen\.min\.y \+ 8\.0\),\n'
        r'        \)\)\n'
        r'        \.default_size\(vec2\(330\.0, 450\.0\)\)\n'
        r'        \.min_size\(vec2\(280\.0, 300\.0\)\)\n'
        r'        \.resizable\(true\)\n'
        r'        \.open\(&mut window_open\)\n'
        r'        \.show\(&ctx, \|ui\| \{\n'
    )
    replacement = r'''    // EFFECTCRAFT_ANDROID_AI_FULLSCREEN_DRAG_V1
    let default_chat_position = pos2(
        (screen.max.x - 350.0).max(screen.min.x + 8.0),
        (screen.max.y - 560.0).max(screen.min.y + 8.0),
    );
    let chat_fullscreen = state.chat_fullscreen;
    let chat_window_position = if chat_fullscreen {
        screen.min
    } else {
        state.chat_position.unwrap_or(default_chat_position)
    };
    let chat_window_size = if chat_fullscreen {
        vec2((screen.width() - 8.0).max(240.0), (screen.height() - 48.0).max(200.0))
    } else {
        vec2(330.0, 450.0)
    };
    let mut dragged_chat_to = None;
    let mut next_fullscreen = None;
    let mut window_open = state.open;
    egui::Window::new("EffectCraft AI 助手")
        .id(Id::new("effectcraft-ai-chat-window"))
        .order(Order::Foreground)
        .movable(false)
        .default_pos(chat_window_position)
        .default_size(chat_window_size)
        .current_pos(chat_window_position)
        .current_size(chat_window_size)
        .min_size(if chat_fullscreen { vec2(200.0, 160.0) } else { vec2(280.0, 300.0) })
        .resizable(!chat_fullscreen)
        .open(&mut window_open)
        .show(&ctx, |ui| {
            ui.horizontal(|ui| {
                let drag_width = (ui.available_width() - 58.0).max(80.0);
                let handle = ui.add_sized(
                    vec2(drag_width, 30.0),
                    egui::Label::new("按住这里拖动 AI 助手").sense(egui::Sense::click_and_drag()),
                );
                if !chat_fullscreen && handle.drag_started() {
                    state.chat_drag_origin = Some(chat_window_position);
                }
                if !chat_fullscreen && handle.dragged() {
                    let origin = state.chat_drag_origin.unwrap_or(chat_window_position);
                    let delta = handle.drag_delta();
                    let max_x = (screen.max.x - 120.0).max(screen.min.x);
                    let max_y = (screen.max.y - 90.0).max(screen.min.y);
                    dragged_chat_to = Some(pos2(
                        (origin.x + delta.x).clamp(screen.min.x, max_x),
                        (origin.y + delta.y).clamp(screen.min.y, max_y),
                    ));
                }
                if handle.drag_stopped() {
                    state.chat_drag_origin = None;
                }
                if ui.button(if chat_fullscreen { "还原窗口" } else { "全屏" }).clicked() {
                    next_fullscreen = Some(!chat_fullscreen);
                }
            });
'''
    source, count = old.subn(replacement, source, count=1)
    if count != 1:
        raise SystemExit("Could not locate the expected AI assistant chat Window builder.")
    tail = "    state.open = window_open;\n    if import_plugin {"
    replacement_tail = """    state.open = window_open;
    if let Some(position) = dragged_chat_to {
        state.chat_position = Some(position);
    }
    if let Some(fullscreen) = next_fullscreen {
        state.chat_fullscreen = fullscreen;
        if !fullscreen {
            state.chat_position = Some(default_chat_position);
        }
    }
    if import_plugin {"""
    if tail not in source:
        raise SystemExit("Could not find the AI assistant window result handling.")
    source = source.replace(tail, replacement_tail, 1)
    return source


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/ai_assistant.rs"
    source = path.read_text(encoding="utf-8")
    source = add_state_fields(source)
    source = patch_avatar_fallback(source)
    source = patch_window(source)
    required = (MARKER, ".current_size(chat_window_size)", "按住这里拖动 AI 助手", "还原窗口", "chat_drag_origin")
    missing = [part for part in required if part not in source]
    if missing:
        raise SystemExit(f"AI assistant full-screen/drag patch is incomplete: {missing}")
    path.write_text(source, encoding="utf-8")
    print("Added AI assistant full-screen mode, touch drag handle and safe avatar decode fallback.")


if __name__ == "__main__":
    main()
