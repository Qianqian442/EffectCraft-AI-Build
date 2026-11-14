#!/usr/bin/env python3
"""Add a Project-panel import button and create compositions from selected footage."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_PROJECT_IMPORT_BUTTON_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)



def patch_visual_media_picker(root: Path) -> None:
    """Add an image/video-only command and add picked media straight to the canvas."""
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
        '    const MEDIA: &[&str] = &[',
        '    const VISUAL_MEDIA: &[&str] = &[\n        "png", "jpg", "jpeg", "gif", "webp", "tif", "tiff", "bmp", "exr", "dpx", "cin", "svg", "eps", "tga", "hdr",\n    ];\n    const MEDIA: &[&str] = &[',
        "visual image extension list",
    )
    source = replace_once(
        source,
        '            Ask::Import => crate::FileDialog::Open { exts: footage(MEDIA).iter().map(|e| e.to_string()).collect(), many: key == "paths" },',
        '            Ask::Import => crate::FileDialog::Open { exts: footage(MEDIA).iter().map(|e| e.to_string()).collect(), many: key == "paths" },\n            Ask::VisualMedia => crate::FileDialog::Open { exts: footage(VISUAL_MEDIA).iter().map(|e| e.to_string()).collect(), many: true },',
        "visual media async picker mapping",
    )
    source = replace_once(
        source,
        '''        Ask::OpenProject => {
            let Some(f) = app.hooks.pick_open_project.as_ref() else { return Some(Err("no file dialog available (pass \`path\`)".into())) };
            f().map(|s| json!(s))
        }''',
        '''        Ask::VisualMedia => {
            let Some(f) = app.hooks.pick_files.as_ref() else { return Some(Err("no file dialog available (pass \`paths\`)".into())) };
            picked_value(key, f(&footage(VISUAL_MEDIA)))
        }
        Ask::OpenProject => {
            let Some(f) = app.hooks.pick_open_project.as_ref() else { return Some(Err("no file dialog available (pass \`path\`)".into())) };
            f().map(|s| json!(s))
        }''',
        "visual media fallback picker mapping",
    )

    old_run = '''    let mut p = params.as_object().cloned().unwrap_or_default();
    p.insert(key.to_string(), v);
    // Picked files import in the background, with the Importing card showing progress (#270).'''
    new_run = '''    let mut p = params.as_object().cloned().unwrap_or_default();
    p.insert(key.to_string(), v);
    let visual_only = id == "file.importVisualMedia";
    let command = if visual_only { "file.import" } else { id };
    if visual_only {
        // Import image/video files directly into the active comp; when there is no active
        // comp, create one from the imported footage so it is immediately visible on canvas.
        p.insert("sequence".into(), Value::Bool(false));
        if app.session.active_comp_id().is_some() {
            p.insert("addToComp".into(), Value::Bool(true));
        } else {
            p.insert("newComp".into(), Value::Bool(true));
        }
    }
    // Picked files import in the background, with the Importing card showing progress (#270).'''
    source = replace_once(source, old_run, new_run, "visual import target composition")
    source = replace_once(
        source,
        '    if matches!(id, "file.import" | "file.importMultiple") {',
        '    if matches!(command, "file.import" | "file.importMultiple") {',
        "visual import background command",
    )
    source = replace_once(
        source,
        '    if id == "file.import" && crate::panels::dialogs::open_form(app, id, &picked)\n        || matches!(id, "file.import" | "file.importMultiple") && crate::panels::forms::open_import_sequence(app, &picked)',
        '    if !visual_only && command == "file.import" && crate::panels::dialogs::open_form(app, command, &picked)\n        || !visual_only && matches!(command, "file.import" | "file.importMultiple") && crate::panels::forms::open_import_sequence(app, &picked)',
        "skip legacy dialogs for visual import",
    )
    source = replace_once(
        source,
        '    match crate::panels::aep_losses::guard(app, id, &picked) {',
        '    match crate::panels::aep_losses::guard(app, command, &picked) {',
        "visual import command guard",
    )
    source = replace_once(
        source,
        '    let id = if id == "file.save" { "file.saveAs" } else { id };\n    let r = app.session.execute(id, Value::Object(p)).map_err(|e| e.to_string());',
        '    let command = if command == "file.save" { "file.saveAs" } else { command };\n    let r = app.session.execute(command, Value::Object(p)).map_err(|e| e.to_string());',
        "execute normalized visual import",
    )
    if "file.importVisualMedia" not in source or 'p.insert("newComp"' not in source:
        raise SystemExit("Visual media import command verification failed")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "vendor/effectcraft")).resolve()
    path = root / "crates/ui-egui/src/panels/project.rs"
    if not path.is_file():
        raise SystemExit("EFFECTCRAFT_DIR must point to EffectCraft source with panels/project.rs")

    patch_visual_media_picker(root)

    source = path.read_text(encoding="utf-8")
    if MARKER not in source:
        old_search = '''    let sr = Rect::from_min_size(pos2(rect.min.x + 8.0, head.max.y + 2.0), vec2(rect.width() - 16.0, 22.0));
    let mut q = app.ui.project_search.clone();
    widgets::search_field(ui, sr, &mut q, crate::i18n::tr("Search project"), &t);
    app.ui.project_search = q;
    app.auto.add("project.search", sr, "Search");'''
        new_search = '''    // EFFECTCRAFT_ANDROID_PROJECT_IMPORT_BUTTON_V1
    // Keep Import beside Project search, not in a screen-corner overlay that can cover
    // the Timeline footer's keyframe button on small Android displays.
    let import_rect = Rect::from_min_size(pos2(rect.max.x - 68.0, head.max.y + 2.0), vec2(60.0, 22.0));
    let sr = Rect::from_min_size(
        pos2(rect.min.x + 8.0, head.max.y + 2.0),
        vec2((rect.width() - 84.0).max(72.0), 22.0),
    );
    let mut q = app.ui.project_search.clone();
    widgets::search_field(ui, sr, &mut q, crate::i18n::tr("Search project"), &t);
    app.ui.project_search = q;
    app.auto.add("project.search", sr, "Search");
    let import_response = ui.put(import_rect, egui::Button::new("＋ 导入"));
    app.auto.add_response("project.importMedia", &import_response, "导入素材");
    if import_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importVisualMedia", json!({}))
    {
        app.ui.status = error;
    }'''
        source = replace_once(source, old_search, new_search, "Project panel import button beside search")

        old_new_comp = '"newComp" => crate::panels::dialogs::open_new_comp(app),'
        new_new_comp = '''"newComp" => {
                    // With footage selected, create a composition from that source (the
                    // same command used by File > New Comp from Selection). With no usable
                    // selection, preserve the original blank New Composition dialog.
                    let selected = app.session.state.project_selection.clone();
                    let from_selection = !selected.is_empty()
                        && selected.iter().all(|id| app.session.project.item(*id).is_some_and(|item| {
                            match &item.kind {
                                ItemKind::Footage(footage) => footage.kind != effectcraft_engine::project::FootageKind::Data,
                                ItemKind::Solid(_) | ItemKind::Comp(_) => true,
                                ItemKind::Folder => false,
                            }
                        }));
                    if from_selection {
                        actions.push(("file.newCompFromSelection".into(), json!({})));
                    } else {
                        crate::panels::dialogs::open_new_comp(app);
                    }
                },'''
        source = replace_once(source, old_new_comp, new_new_comp, "New Composition from selected footage")

    if MARKER not in source:
        raise SystemExit("Project import button patch marker was not installed")
    path.write_text(source, encoding="utf-8")
    print("Added a Project-panel Import button beside Search; removed the screen-corner overlap. New Composition now creates from selected footage, otherwise opens the original blank composition dialog.")


if __name__ == "__main__":
    main()
