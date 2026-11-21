#!/usr/bin/env python3
"""Add the unified project-import shortcut only to the independent AM editor header."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1"


def main() -> None:
    # This script lives beside build_am_mobile_editing_page.py in build-assets/.github/scripts.
    # Patch the AM editor generator, not crates/ui-egui/src/header.rs: header.rs belongs to
    # the original Ae layout and must remain free of AM-only controls.
    generator = Path(__file__).resolve().with_name("build_am_mobile_editing_page.py")
    if not generator.is_file():
        raise SystemExit(f"AM editor generator was not found: {generator}")
    source = generator.read_text(encoding="utf-8")

    if MARKER in source:
        required = (
            'app.auto.add_response("am.header.importProject"',
            'invoke(app, ui.ctx(), "file.importProject", json!({}))',
            "let mut import_title_left",
        )
        missing = [token for token in required if token not in source]
        if missing:
            raise SystemExit("AM project-import marker exists but is incomplete: " + "; ".join(missing))
        print("AM-only unified project-import shortcut is already installed.")
        return

    anchor = '''    if let Some(choice) = crate::widgets::popup_menu(ui, layout_id, layout_rect.left_bottom(), &choices, Some(1)) {
        app.set_workspace(if choice == 0 { "Default" } else { WORKSPACE });
    }

    let export_rect = Rect::from_min_size'''
    if source.count(anchor) != 1:
        raise SystemExit("Could not uniquely locate the independent AM editor top-bar insertion point.")

    replacement = '''    if let Some(choice) = crate::widgets::popup_menu(ui, layout_id, layout_rect.left_bottom(), &choices, Some(1)) {
        app.set_workspace(if choice == 0 { "Default" } else { WORKSPACE });
    }

    // EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1
    // This control is drawn only by the independent AM editor. The original Ae header.rs
    // and its toolbar layout are deliberately not modified.
    let mut import_title_left = layout_rect.max.x + 7.0;
    let import_left = layout_rect.max.x + 7.0;
    let import_right = rect.max.x - 156.0;
    let import_width = (import_right - import_left).clamp(0.0, 76.0);
    if import_width >= 32.0 {
        let import_rect = Rect::from_min_size(
            pos2(import_left, rect.min.y + 7.0),
            vec2(import_width, 30.0),
        );
        let import_label = if import_width < 58.0 { "导入" } else { "导入工程" };
        let import_response = button(ui, import_rect, import_label, "am-project-import");
        app.auto.add_response("am.header.importProject", &import_response, "导入工程");
        if import_response.clicked() {
            invoke(app, ui.ctx(), "file.importProject", json!({}));
        }
        import_title_left = import_rect.max.x + 6.0;
    }

    let export_rect = Rect::from_min_size'''
    source = source.replace(anchor, replacement, 1)

    title_anchor = "    let title_left = layout_rect.max.x + 7.0;"
    if source.count(title_anchor) != 1:
        raise SystemExit("Could not uniquely locate the AM project-title layout anchor.")
    source = source.replace(title_anchor, "    let title_left = import_title_left;", 1)

    if source.count(MARKER) != 1:
        raise SystemExit("AM-only project-import marker must appear exactly once.")
    if 'invoke(app, ui.ctx(), "file.importProject", json!({}))' not in source:
        raise SystemExit("AM project-import shortcut is not connected to the native unified importer.")

    generator.write_text(source, encoding="utf-8")

    # Guard the original Ae toolbar against accidental cross-layout injection.
    effectcraft_dir = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    ae_header = effectcraft_dir / "crates/ui-egui/src/header.rs"
    if not ae_header.is_file():
        raise SystemExit(f"Original Ae header source was not found: {ae_header}")
    ae_header_source = ae_header.read_text(encoding="utf-8")
    if MARKER in ae_header_source or "project_import_button(app," in ae_header_source:
        raise SystemExit("AM project-import controls must not be injected into the original Ae toolbar.")

    print("Added the unified project-import shortcut to the independent AM editor top bar only.")
    print("Original Ae header.rs and the Ae toolbar arrangement remain unchanged.")
    print("The AM shortcut calls the existing file.importProject command; original import routes remain intact.")


if __name__ == "__main__":
    main()
