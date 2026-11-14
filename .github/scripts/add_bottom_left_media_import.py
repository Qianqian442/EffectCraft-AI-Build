#!/usr/bin/env python3
"""Put media import inside the Project panel and auto-add imported media to the active composition."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_MARKER = "EFFECTCRAFT_ANDROID_PROJECT_FOOTER_IMPORT_V2"
FINISH_MARKER = "EFFECTCRAFT_ANDROID_AUTO_ADD_IMPORTED_MEDIA_V2"
FIT_MARKER = "EFFECTCRAFT_ANDROID_FIT_IMPORTED_MEDIA_TO_COMP_V2"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_project_panel_import_button(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    if PROJECT_MARKER not in source:
        anchor = "    let depth = app.session.project.settings.bit_depth.label();\n"
        button = r'''    // EFFECTCRAFT_ANDROID_PROJECT_FOOTER_IMPORT_V2
    // Keep Import Media inside the Project panel: a floating screen-corner button
    // overlapped the Timeline's Add Keyframe control on narrow Android layouts.
    let import_rect = Rect::from_min_size(pos2(x + 2.0, foot.min.y + 3.0), vec2(24.0, 22.0));
    let import_response = ui
        .put(import_rect, egui::Button::new("＋"))
        .on_hover_text(crate::i18n::tr("Import Media"));
    app.auto.add_response("project.importMedia", &import_response, "导入素材");
    if import_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.import", json!({}))
    {
        app.ui.status = error;
    }
    x += 28.0;
'''
        source = replace_once(source, anchor, button + anchor, "Project panel media import button")
        if PROJECT_MARKER not in source:
            raise SystemExit("Project panel media import marker was not installed")
        path.write_text(source, encoding="utf-8")


def patch_file_import_auto_add(root: Path) -> None:
    path = root / "crates/engine/src/cmd/file.rs"
    source = path.read_text(encoding="utf-8")
    if FINISH_MARKER not in source:
        old = '''fn finish_import(s: &mut Session, r: &mut Value, target: Option<ItemId>, p: &Value) {
    let errors = if b_p(p, "newComp").unwrap_or(false) { new_comp(s, r) } else { add_to_comp(s, r, target, p) };'''
        new = '''fn finish_import(s: &mut Session, r: &mut Value, target: Option<ItemId>, p: &Value) {
    // EFFECTCRAFT_ANDROID_AUTO_ADD_IMPORTED_MEDIA_V2
    // A regular media import also creates a layer in the currently active composition.
    // Explicit addToComp=false remains an opt-out, and New Comp keeps its own workflow.
    let errors = if b_p(p, "newComp").unwrap_or(false) {
        new_comp(s, r)
    } else {
        let mut params = p.clone();
        if params.get("addToComp").is_none() && target.is_some() {
            params["addToComp"] = json!(true);
        }
        if params.get("addToComp").and_then(Value::as_bool) == Some(true)
            && params.get("fitToComp").is_none()
        {
            params["fitToComp"] = json!(true);
        }
        add_to_comp(s, r, target, &params)
    };'''
        source = replace_once(source, old, new, "Default add imported media to active comp")

        old_rest = '    let rest = ids("items").into_iter().filter(|i| !in_comps.contains(i) && !comps.contains(i) && !s.project.item(ItemId(*i)).is_some_and(|it| it.is_folder()));'
        new_rest = '''    // Data footage and folders are project assets, not visual/audio composition layers.
    let rest = ids("items").into_iter().filter(|i| {
        !in_comps.contains(i)
            && !comps.contains(i)
            && s.project.item(ItemId(*i)).is_some_and(|it| {
                !it.is_folder()
                    && !matches!(&it.kind, ItemKind::Footage(f) if f.kind == FootageKind::Data)
            })
    });'''
        source = replace_once(source, old_rest, new_rest, "Exclude data footage from automatic composition layers")

        source = source.replace(
            'addToComp?: bool (also add them to the active comp, at time?, index?, position? as in layer.addItem)',
            'addToComp?: bool (default true when a comp is active; also add them to the active comp), fitToComp?: bool (uniformly fit each new layer inside the comp frame)'
        )
        path.write_text(source, encoding="utf-8")


def patch_layer_add_item_fit(root: Path) -> None:
    path = root / "crates/engine/src/cmd/layer/create.rs"
    source = path.read_text(encoding="utf-8")
    if FIT_MARKER in source:
        return
    anchor = '        let mut l = build::layer(proj, &comp, &it.name, src, size, dur);\n'
    fit = r'''        // EFFECTCRAFT_ANDROID_FIT_IMPORTED_MEDIA_TO_COMP_V2
        // Preserve the source aspect ratio while enlarging small media or shrinking large
        // media so the complete image/video is visible inside the composition frame.
        if b_p(p, "fitToComp").unwrap_or(false) {
            let fit_scale = (comp.width as f64 / size.0.max(1) as f64)
                .min(comp.height as f64 / size.1.max(1) as f64);
            if let Some(scale) = l.props.prop_mut("transform/scale") {
                let z = match scale.value {
                    KV::Vec3(v) => v[2],
                    _ => 100.0,
                };
                scale.value = KV::Vec3([100.0 * fit_scale, 100.0 * fit_scale, z]);
            }
        }
'''
    source = replace_once(source, anchor, anchor + fit, "Fit imported media to composition frame")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_project_panel_import_button(root)
    patch_file_import_auto_add(root)
    patch_layer_add_item_fit(root)
    print("Moved the media import shortcut into the Project panel footer to avoid Timeline overlap.")
    print("Regular imports now create a layer in the active composition and fit it to the comp frame.")
    print("Imported files remain in the Project panel and their layers appear in the Timeline.")


if __name__ == "__main__":
    main()
