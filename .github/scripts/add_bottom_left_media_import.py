#!/usr/bin/env python3
"""Add a fixed bottom-left shortcut to EffectCraft's existing media import command."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_BOTTOM_LEFT_MEDIA_IMPORT_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    frame_path = root / "crates/ui-egui/src/app/frame.rs"
    media_path = root / "crates/ui-egui/src/panels/media_panels.rs"
    if not root.is_dir() or not frame_path.is_file() or not media_path.is_file():
        raise SystemExit("EFFECTCRAFT_DIR must point to EffectCraft source with app/frame.rs and panels/media_panels.rs")

    frame = frame_path.read_text(encoding="utf-8")
    if MARKER not in frame:
        anchor = """        let lift = panels::media_panels::import_card(self, ui, full);
        self.draw_toast(ui, full, lift);"""
        replacement = """        let lift = panels::media_panels::import_card(self, ui, full);
        self.draw_material_import_quick_entry(&ctx, full);
        self.draw_toast(ui, full, lift + 48.0);"""
        frame = replace_once(frame, anchor, replacement, "root frame quick-entry call")

        method_anchor = "    fn draw_toast(&mut self, ui: &mut egui::Ui, full: egui::Rect, lift: f32) {"
        method = r'''    // EFFECTCRAFT_ANDROID_BOTTOM_LEFT_MEDIA_IMPORT_V1
    /// A persistent shortcut that opens the very same multi-file picker as File > Import.
    fn draw_material_import_quick_entry(&mut self, ctx: &egui::Context, full: egui::Rect) {
        let position = egui::pos2(full.min.x + 16.0, full.max.y - 52.0);
        let mut clicked = false;
        let mut button_rect = None;
        egui::Area::new(egui::Id::new("effectcraft-bottom-left-media-import"))
            .order(egui::Order::Foreground)
            .fixed_pos(position)
            .movable(false)
            .show(ctx, |ui| {
                let response = ui.add_sized(
                    egui::vec2(132.0, 36.0),
                    egui::Button::new("＋ 导入素材"),
                );
                clicked = response.clicked();
                button_rect = Some(response.rect);
            });
        if let Some(rect) = button_rect {
            self.auto.add("quick.importMedia", rect, "导入素材");
        }
        if clicked
            && let Err(error) = crate::menus::invoke(self, ctx, "file.import", serde_json::json!({}))
        {
            self.ui.status = error;
        }
    }

'''
        frame = replace_once(frame, method_anchor, method + method_anchor, "quick-entry drawing method")
        if MARKER not in frame:
            raise SystemExit("Quick-entry marker was not installed")
        frame_path.write_text(frame, encoding="utf-8")

    media = media_path.read_text(encoding="utf-8")
    old_bottom = "    let mut bottom = full.max.y - 16.0;"
    new_bottom = "    // Leave room below for the persistent bottom-left media-import shortcut.\n    let mut bottom = full.max.y - 64.0;"
    media = replace_once(media, old_bottom, new_bottom, "import progress-card bottom anchor")
    old_lift = "    full.max.y - 16.0 - bottom"
    new_lift = "    full.max.y - 64.0 - bottom"
    media = replace_once(media, old_lift, new_lift, "import progress-card reserved-height calculation")
    media_path.write_text(media, encoding="utf-8")

    # The AI bubble is draggable and may have been saved over the new bottom-left
    # import shortcut. Bump its Area ID once so egui discards the old saved position
    # and uses the existing safe bottom-right default. It remains draggable.
    assistant_path = root / "crates/ui-egui/src/ai_assistant.rs"
    if assistant_path.is_file():
        assistant = assistant_path.read_text(encoding="utf-8")
        old_bubble_id = 'egui::Area::new(Id::new("effectcraft-ai-bubble"))'
        new_bubble_id = 'egui::Area::new(Id::new("effectcraft-ai-bubble-v2"))'
        if new_bubble_id not in assistant:
            assistant = replace_once(
                assistant, old_bubble_id, new_bubble_id,
                "AI bubble saved-position reset",
            )
            assistant_path.write_text(assistant, encoding="utf-8")

    print("Installed the bottom-left Import Media shortcut, reserved room for progress cards/toasts, and reset the draggable AI bubble to its safe bottom-right default.")


if __name__ == "__main__":
    main()
