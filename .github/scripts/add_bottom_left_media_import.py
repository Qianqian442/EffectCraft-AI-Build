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



def patch_visual_media_picker(root: Path) -> None:
    """Give the quick entry a real multi-select picker restricted to images and videos."""
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    source = replace_once(source, "        Import,\n        OpenProject,", "        Import,\n        VisualMedia,\n        OpenProject,", "visual media picker Ask variant")
    source = replace_once(
        source,
        '        "file.import" | "file.importMultiple" => ("paths", Ask::Import),',
        '        "file.importVisualMedia" => ("paths", Ask::VisualMedia),\n        "file.import" | "file.importMultiple" => ("paths", Ask::Import),',
        "visual media picker command mapping",
    )
    source = replace_once(
        source,
        '    const MEDIA: &[&str] = &[\n',
        '    const VISUAL_MEDIA: &[&str] = &[\n        "png", "jpg", "jpeg", "gif", "webp", "tif", "tiff", "bmp", "exr", "dpx", "cin", "svg", "eps", "tga", "hdr",\n    ];\n    const MEDIA: &[&str] = &[\n',
        "visual media extension list",
    )
    source = replace_once(
        source,
        '            Ask::Import => crate::FileDialog::Open { exts: footage(MEDIA).iter().map(|e| e.to_string()).collect(), many: key == "paths" },',
        '            Ask::Import => crate::FileDialog::Open { exts: footage(MEDIA).iter().map(|e| e.to_string()).collect(), many: key == "paths" },\n            Ask::VisualMedia => crate::FileDialog::Open { exts: footage(VISUAL_MEDIA).iter().map(|e| e.to_string()).collect(), many: true },',
        "async visual media picker",
    )
    source = replace_once(
        source,
        '        Ask::Import => {\n            let Some(f) = app.hooks.pick_files.as_ref() else { return Some(Err("no file dialog available (pass `paths`)".into())) };\n            picked_value(key, f(&footage(MEDIA)))\n        }',
        '        Ask::Import => {\n            let Some(f) = app.hooks.pick_files.as_ref() else { return Some(Err("no file dialog available (pass paths)".into())) };\n            picked_value(key, f(&footage(MEDIA)))\n        }\n        Ask::VisualMedia => {\n            let Some(f) = app.hooks.pick_files.as_ref() else { return Some(Err("no file dialog available (pass paths)".into())) };\n            picked_value(key, f(&footage(VISUAL_MEDIA)))\n        }',
        "blocking visual media picker",
    )
    source = replace_once(
        source,
        '    let mut p = params.as_object().cloned().unwrap_or_default();\n    p.insert(key.to_string(), v);',
        '    let mut p = params.as_object().cloned().unwrap_or_default();\n    p.insert(key.to_string(), v);\n    let visual_only = id == "file.importVisualMedia";\n    let command = if visual_only { "file.import" } else { id };\n    if visual_only { p.insert("sequence".into(), Value::Bool(false)); }',
        "visual-only command normalization",
    )
    source = replace_once(
        source,
        '    if matches!(id, "file.import" | "file.importMultiple") {\n        p.insert("background".into(), Value::Bool(true));\n    }',
        '    if matches!(command, "file.import" | "file.importMultiple") {\n        p.insert("background".into(), Value::Bool(true));\n    }',
        "visual-only background import",
    )
    source = replace_once(
        source,
        '    if id == "file.import" && crate::panels::dialogs::open_form(app, id, &picked)\n        || matches!(id, "file.import" | "file.importMultiple") && crate::panels::forms::open_import_sequence(app, &picked)',
        '    if !visual_only && command == "file.import" && crate::panels::dialogs::open_form(app, command, &picked)\n        || !visual_only && matches!(command, "file.import" | "file.importMultiple") && crate::panels::forms::open_import_sequence(app, &picked)',
        "skip unrelated import dialogs for visual-only quick picker",
    )
    source = replace_once(
        source,
        '    match crate::panels::aep_losses::guard(app, id, &picked) {',
        '    match crate::panels::aep_losses::guard(app, command, &picked) {',
        "visual-only import guard",
    )
    source = replace_once(
        source,
        '    let id = if id == "file.save" { "file.saveAs" } else { id };\n    let r = app.session.execute(id, Value::Object(p)).map_err(|e| e.to_string());',
        '    let command = if command == "file.save" { "file.saveAs" } else { command };\n    let r = app.session.execute(command, Value::Object(p)).map_err(|e| e.to_string());',
        "execute visual-only import through engine file.import",
    )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    frame_path = root / "crates/ui-egui/src/app/frame.rs"
    media_path = root / "crates/ui-egui/src/panels/media_panels.rs"
    if not root.is_dir() or not frame_path.is_file() or not media_path.is_file():
        raise SystemExit("EFFECTCRAFT_DIR must point to EffectCraft source with app/frame.rs and panels/media_panels.rs")

    patch_visual_media_picker(root)

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
            && let Err(error) = crate::menus::invoke(self, ctx, "file.importVisualMedia", serde_json::json!({}))
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
    print("Installed a direct image/video-only multi-select shortcut; it bypasses the general Import Files dialog and imports in the background.")


if __name__ == "__main__":
    main()
