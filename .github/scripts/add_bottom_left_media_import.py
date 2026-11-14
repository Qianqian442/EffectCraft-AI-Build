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


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "vendor/effectcraft")).resolve()
    path = root / "crates/ui-egui/src/panels/project.rs"
    if not path.is_file():
        raise SystemExit("EFFECTCRAFT_DIR must point to EffectCraft source with panels/project.rs")

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
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.import", json!({}))
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
