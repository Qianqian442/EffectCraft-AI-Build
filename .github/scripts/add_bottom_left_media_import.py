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
    // Import Media is a real Project-panel control, not a floating overlay on the Timeline.
    let import_rect = Rect::from_min_size(pos2(x, foot.min.y + 3.0), vec2(22.0, 22.0));
    let import_response = ui
        .put(import_rect, egui::Button::new("＋"))
        .on_hover_text(crate::i18n::tr("Import pictures and videos"));
    app.auto.add_response("project.importMedia", &import_response, "导入图片和视频");
    if import_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.importMultiple", json!({}))
    {
        app.ui.status = error;
    }
    x += 26.0;
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
    // A normal import creates a layer in the open composition. Without an open composition,
    // the imported pictures/videos become a new composition instead of staying invisible.
    let errors = if b_p(p, "newComp").unwrap_or(false) || target.is_none() {
        new_comp(s, r)
    } else {
        let mut params = p.clone();
        // The user-facing Import Media action always inserts the selected image/video.
        params["addToComp"] = json!(true);
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

        old_params = '        let mut params = json!({"comp": cid.0, "item": item, "time": p.get("time"), "position": p.get("position")});'
        new_params = '        let mut params = json!({"comp": cid.0, "item": item, "time": p.get("time"), "position": p.get("position"), "fitToComp": p.get("fitToComp").and_then(Value::as_bool).unwrap_or(false)});'
        source = replace_once(source, old_params, new_params, "Pass fitToComp through to layer.addItem")

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
        let can_fit_to_comp = match &it.kind {
            ItemKind::Footage(f) => matches!(
                f.kind,
                effectcraft_project::FootageKind::Still
                    | effectcraft_project::FootageKind::Sequence
                    | effectcraft_project::FootageKind::Video
            ) && f.width > 0 && f.height > 0,
            ItemKind::Comp(_) | ItemKind::Solid(_) => size.0 > 0 && size.1 > 0,
            ItemKind::Folder => false,
        };
        if b_p(p, "fitToComp").unwrap_or(false) && can_fit_to_comp {
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


def patch_layer_add_item_fit_spec(root: Path) -> None:
    path = root / "crates/engine/src/cmd/layer.rs"
    source = path.read_text(encoding="utf-8")
    old = "anchor? ([x, y] layer px; default the centre)}"
    new = "anchor? ([x, y] layer px; default the centre), fitToComp?: bool (uniformly fit the complete media inside the composition frame)}"
    source = replace_once(source, old, new, "Document layer.addItem fitToComp parameter")
    path.write_text(source, encoding="utf-8")


def patch_project_panel_footer_responsive(root: Path) -> None:
    """Keep the import, bit-depth and delete controls inside non-overlapping footer hit boxes."""
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    old = '''    let depth = app.session.project.settings.bit_depth.label();
    let dr = Rect::from_min_size(pos2(x + 4.0, foot.min.y + 5.0), vec2(48.0, 18.0));
    let dresp = ui.interact(dr, egui::Id::unique("bpc"), Sense::click());
    p.text(dr.center(), Align2::CENTER_CENTER, depth, Tokens::ui(11.5), if dresp.hovered() { t.text } else { t.text_dim });
    app.auto.add("project.bitDepth", dr, depth);
    dresp.widget_info(|| egui::WidgetInfo::labeled(egui::Role::Button, true, crate::i18n::tr_args("Project color depth: {}", &[&depth])));
    // Click cycles 8/16/32 bpc; Alt-click opens Project Settings (as in After Effects).
    if dresp.clicked() {
        if ui.input(|i| i.modifiers.alt) {
            actions.push(("file.projectSettings".into(), json!({})));
        } else {
            actions.push(("file.cycleBitDepth".into(), json!({})));
        }
    }
    dresp.on_hover_text(crate::i18n::tr("Project color depth: click to cycle 8/16/32 bpc, Alt-click for Project Settings"));
    let tr = Rect::from_min_size(pos2(foot.max.x - 30.0, foot.min.y + 3.0), vec2(22.0, 22.0));'''
    new = '''    let tr = Rect::from_min_size(pos2(foot.max.x - 30.0, foot.min.y + 3.0), vec2(22.0, 22.0));
    let depth = app.session.project.settings.bit_depth.label();
    let depth_min_x = x + 4.0;
    let depth_width = (tr.min.x - depth_min_x).max(0.0).min(48.0);
    // On narrow phones, shrink or hide the bit-depth label instead of letting it overlap
    // the Delete button or the Import Media hitbox.
    if depth_width >= 20.0 {
        let dr = Rect::from_min_size(pos2(depth_min_x, foot.min.y + 5.0), vec2(depth_width, 18.0));
        let dresp = ui.interact(dr, egui::Id::unique("bpc"), Sense::click());
        p.text(dr.center(), Align2::CENTER_CENTER, depth, Tokens::ui(11.5), if dresp.hovered() { t.text } else { t.text_dim });
        app.auto.add("project.bitDepth", dr, depth);
        dresp.widget_info(|| egui::WidgetInfo::labeled(egui::Role::Button, true, crate::i18n::tr_args("Project color depth: {}", &[&depth])));
        // Click cycles 8/16/32 bpc; Alt-click opens Project Settings (as in After Effects).
        if dresp.clicked() {
            if ui.input(|i| i.modifiers.alt) {
                actions.push(("file.projectSettings".into(), json!({})));
            } else {
                actions.push(("file.cycleBitDepth".into(), json!({})));
            }
        }
        dresp.on_hover_text(crate::i18n::tr("Project color depth: click to cycle 8/16/32 bpc, Alt-click for Project Settings"));
    }'''
    replace_once(source, old, new, "Project footer responsive control layout")
    path.write_text(source, encoding="utf-8")


def patch_picture_video_only_media_picker(root: Path) -> None:
    """Limit the normal Import Media command to still-image formats; video formats are appended upstream."""
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    old = '''    const MEDIA: &[&str] = &[
        "png", "jpg", "jpeg", "gif", "webp", "tif", "tiff", "bmp", "exr", "dpx", "cin", "wav", "aif", "aiff", "mp3", "flac", "ogg", "opus", "svg", "pdf", "ai",
        "eps", "psd", "psb", "tga", "hdr", "gltf", "glb", "obj", "stl", "fbx", "json", "csv", "tsv",
    ];'''
    new = '''    // EFFECTCRAFT_ANDROID_PICTURE_VIDEO_IMPORT_ONLY_V1
    // The ordinary Android Import Media button is for pictures and videos only.
    const MEDIA: &[&str] = &[
        "png", "jpg", "jpeg", "gif", "webp", "tif", "tiff", "bmp", "exr", "svg",
        "psd", "psb", "tga", "hdr", "dpx", "cin",
    ];'''
    replace_once(source, old, new, "Image-only import extension filter")
    path.write_text(source, encoding="utf-8")


def patch_project_new_comp_from_selected_media(root: Path) -> None:
    """Make the Project panel's New Composition button turn selected picture/video items into layers."""
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    old = '''                "newComp" => crate::panels::dialogs::open_new_comp(app),'''
    new = r'''                "newComp" => {
                    let selected_media = app.session.state.project_selection.iter().any(|id| {
                        app.session.project.item(*id).is_some_and(|item| {
                            matches!(&item.kind, ItemKind::Footage(f) if matches!(
                                f.kind,
                                effectcraft_engine::project::FootageKind::Still
                                    | effectcraft_engine::project::FootageKind::Sequence
                                    | effectcraft_engine::project::FootageKind::Video
                            ))
                        })
                    });
                    if selected_media {
                        actions.push(("file.newCompFromSelection".into(), json!({"single": true})));
                    } else {
                        crate::panels::dialogs::open_new_comp(app);
                    }
                },'''
    replace_once(source, old, new, "New Composition button selected-media routing")
    path.write_text(source, encoding="utf-8")


def patch_new_comp_layer_fit(root: Path) -> None:
    """Fit every imported media layer when creating a comp from selected Project-panel items."""
    path = root / "crates/engine/src/cmd/file_more.rs"
    source = path.read_text(encoding="utf-8")
    old = 'layers.push(s.execute("layer.addItem", json!({"comp": cid.0, "item": item.0, "duration": still}))?["layer"].clone());'
    new = 'layers.push(s.execute("layer.addItem", json!({"comp": cid.0, "item": item.0, "duration": still, "fitToComp": true}))?["layer"].clone());'
    replace_once(source, old, new, "Fit layers created from selected media")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_project_panel_import_button(root)
    patch_file_import_auto_add(root)
    patch_layer_add_item_fit(root)
    patch_layer_add_item_fit_spec(root)
    patch_picture_video_only_media_picker(root)
    patch_project_new_comp_from_selected_media(root)
    patch_new_comp_layer_fit(root)
    patch_project_panel_footer_responsive(root)
    print("Moved the media import shortcut into the Project panel footer to avoid Timeline overlap.")
    print("Regular imports now create a layer in the active composition and fit it to the comp frame.")
    print("Imported files remain in the Project panel and their layers appear in the Timeline.")


if __name__ == "__main__":
    main()
