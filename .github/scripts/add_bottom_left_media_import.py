#!/usr/bin/env python3
"""Put media import inside the Project panel and auto-add imported media to the active composition."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_MARKER = "EFFECTCRAFT_ANDROID_PROJECT_HEADER_IMPORT_V7"
FINISH_MARKER = "EFFECTCRAFT_ANDROID_AUTO_ADD_IMPORTED_MEDIA_V4"
FIT_MARKER = "EFFECTCRAFT_ANDROID_FIT_IMPORTED_MEDIA_TO_COMP_V2"
PICKER_MARKER = "EFFECTCRAFT_ANDROID_PICTURE_VIDEO_PICKER_V2"
TRIM_MARKER = "EFFECTCRAFT_ANDROID_TOUCH_TRIM_HANDLES_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_project_panel_import_button(root: Path) -> None:
    """Keep the media shortcut in Project; project formats stay in File > Import."""
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_PROJECT_HEADER_IMPORT_V7"
    if marker in source:
        return
    old = '''    // Search.
    let sr = Rect::from_min_size(pos2(rect.min.x + 8.0, head.max.y + 2.0), vec2(rect.width() - 16.0, 22.0));
    let mut q = app.ui.project_search.clone();
    widgets::search_field(ui, sr, &mut q, crate::i18n::tr("Search project"), &t);
    app.ui.project_search = q;
    app.auto.add("project.search", sr, "Search");
'''
    new = r'''    // EFFECTCRAFT_ANDROID_PROJECT_HEADER_IMPORT_V7
    // The Project panel offers media import only. Project formats live in File > Import.
    let sr = Rect::from_min_size(
        pos2(rect.min.x + 8.0, head.max.y + 2.0),
        vec2((rect.width() - 16.0).max(40.0), 22.0),
    );
    let media_rect = Rect::from_min_size(
        pos2(rect.min.x + 8.0, sr.max.y + 3.0),
        vec2((rect.width() - 16.0).max(40.0), 24.0),
    );
    let mut q = app.ui.project_search.clone();
    widgets::search_field(ui, sr, &mut q, crate::i18n::tr("Search project"), &t);
    app.ui.project_search = q;
    app.auto.add("project.search", sr, "Search");

    let media_response = ui
        .put(media_rect, egui::Button::new("导入素材").min_size(media_rect.size()))
        .on_hover_text(crate::i18n::tr("Import pictures and videos only"));
    app.auto.add_response("project.importMedia", &media_response, "导入素材");
    if media_response.clicked()
        && let Err(error) = crate::menus::invoke(app, &ctx, "file.import", json!({"picturesAndVideos": true}))
    {
        app.ui.status = error;
    }

    // EFFECTCRAFT_ANDROID_NEW_COMP_FROM_SELECTED_MEDIA_V1
    // This action consumes the already-selected Project-panel footage. It must never
    // launch a document/file picker or re-import the media.
    let new_comp_rect = Rect::from_min_size(
        pos2(rect.min.x + 8.0, media_rect.max.y + 3.0),
        vec2((rect.width() - 16.0).max(40.0), 24.0),
    );
    let new_comp_response = ui
        .put(
            new_comp_rect,
            egui::Button::new("从素材新建合成").min_size(new_comp_rect.size()),
        )
        .on_hover_text("使用素材面板中已选中的图片或视频直接创建合成，不再打开文件选择器");
    app.auto.add_response("project.newCompFromSelectedMedia", &new_comp_response, "从素材新建合成");
    if new_comp_response.clicked()
        && let Err(error) = crate::menus::invoke(
            app,
            &ctx,
            "file.newCompFromSelection",
            json!({"single": true, "fitToComp": true}),
        )
    {
        app.ui.status = error;
    }
'''
    if old not in source:
        raise SystemExit("Could not find original Project search row")
    source = source.replace(old, new, 1)
    old_header = '    let hdr = Rect::from_min_size(pos2(rect.min.x, sr.max.y + 6.0), vec2(rect.width(), 20.0));'
    new_header = '    let hdr = Rect::from_min_size(pos2(rect.min.x, new_comp_rect.max.y + 6.0), vec2(rect.width(), 20.0));'
    if old_header not in source:
        raise SystemExit("Could not find Project content header anchor")
    source = source.replace(old_header, new_header, 1)
    path.write_text(source, encoding="utf-8")

def patch_file_import_auto_add(root: Path) -> None:
    """Auto-place only the dedicated picture/video import action; preserve generic File > Import."""
    path = root / "crates/engine/src/cmd/file.rs"
    source = path.read_text(encoding="utf-8")
    # The upstream file.rs imports b_p/str_p from its parent cmd module.
    # This patch also reads the optional numeric stillDuration, so import f_p there.
    required_import = "use super::{CommandSpec, always, b_p, bad, f_p, str_p};"
    original_import = "use super::{CommandSpec, always, b_p, bad, str_p};"
    # Always import f_p before any patch below inserts a stillDuration lookup.
    # The previous conditional checked for the lookup too early, so the later
    # insertion left file.rs calling f_p without importing it and Rust compilation failed.
    if required_import not in source:
        source = replace_once(source, original_import, required_import, "Import numeric parameter helper for still duration")
    if FINISH_MARKER not in source:
        old = '''fn finish_import(s: &mut Session, r: &mut Value, target: Option<ItemId>, p: &Value) {
    let errors = if b_p(p, "newComp").unwrap_or(false) { new_comp(s, r) } else { add_to_comp(s, r, target, p) };'''
        new = '''fn finish_import(s: &mut Session, r: &mut Value, target: Option<ItemId>, p: &Value) {
    // EFFECTCRAFT_ANDROID_AUTO_ADD_IMPORTED_MEDIA_V4
    // Only the dedicated Project-panel Media button adds pictures/videos to the comp.
    // Generic File > Import retains its original behavior and complete media-type support.
    // Still-layer duration continues to follow the user's original Import preferences.
    let picture_video_import = b_p(p, "picturesAndVideos").unwrap_or(false);
    let errors = if b_p(p, "newComp").unwrap_or(false) {
        new_comp(s, r, None, picture_video_import)
    } else if picture_video_import && target.is_none() {
        new_comp(s, r, None, true)
    } else if picture_video_import {
        let mut media_params = p.clone();
        media_params["addToComp"] = json!(true);
        media_params["fitToComp"] = json!(true);
        add_to_comp(s, r, target, &media_params)
    } else {
        add_to_comp(s, r, target, p)
    };'''
        source = replace_once(source, old, new, "Scope automatic composition insertion to picture/video shortcut")

        old_new_comp = '''fn new_comp(s: &mut Session, r: &Value) -> Vec<String> {'''
        new_new_comp = '''fn new_comp(s: &mut Session, r: &Value, still_duration: Option<f64>, fit_to_comp: bool) -> Vec<String> {'''
        source = replace_once(source, old_new_comp, new_new_comp, "Add optional still duration to imported-media composition")

        old_exec = '''    match s.execute("file.newCompFromSelection", json!({"single": true})) {
        Ok(_) => vec![],
        Err(e) => vec![e.to_string()],
    }'''
        new_exec = '''    let mut params = json!({"single": true});
    if let Some(duration) = still_duration {
        params["duration"] = json!(duration);
    }
    if fit_to_comp {
        params["fitToComp"] = json!(true);
    }
    match s.execute("file.newCompFromSelection", params) {
        Ok(_) => vec![],
        Err(e) => vec![e.to_string()],
    }'''
        source = replace_once(source, old_exec, new_exec, "Pass explicit still duration only for the Media shortcut")

        old_add_start = '''    let add = imported(s, r);
    let mut errors = vec![];
    for (k, item) in add.into_iter().enumerate() {
        let mut params = json!({"comp": cid.0, "item": item, "time": p.get("time"), "position": p.get("position")});
        if let Some(i) = p.get("index").and_then(Value::as_u64) {
            params["index"] = json!(i.saturating_add(k as u64));
        }
        if let Err(e) = s.execute("layer.addItem", params) {
            errors.push(e.to_string());
        }
    }'''
        new_add_start = '''    let add = imported(s, r);
    let picture_video_import = b_p(p, "picturesAndVideos").unwrap_or(false);
    let still_duration = f_p(p, "stillDuration").filter(|duration| duration.is_finite() && *duration > 0.0);
    let mut errors = vec![];
    let mut created_layers = Vec::new();
    for (k, item) in add.into_iter().enumerate() {
        let mut params = json!({"comp": cid.0, "item": item, "time": p.get("time"), "position": p.get("position")});
        if let Some(i) = p.get("index").and_then(Value::as_u64) {
            params["index"] = json!(i.saturating_add(k as u64));
        }
        if let Some(fit) = p.get("fitToComp") {
            params["fitToComp"] = fit.clone();
        }
        if picture_video_import {
            params["fitToComp"] = json!(true);
            let still = s.project.item(ItemId(item)).is_some_and(|it| {
                matches!(&it.kind, ItemKind::Footage(f) if f.kind == FootageKind::Still)
            });
            if still {
                // Do not force an import duration here. The engine uses the user's
                // existing Import > Still Footage preference; the timeline Out edge
                // remains freely draggable in either direction.
                if let Some(duration) = still_duration {
                    params["duration"] = json!(duration);
                }
            }
        }
        match s.execute("layer.addItem", params) {
            Ok(result) => {
                if let Some(layer_id) = result.get("layer").and_then(Value::as_u64) {
                    created_layers.push(layer_id);
                }
            }
            Err(error) => errors.push(error.to_string()),
        }
    }
    // A picture/video inserted by the Project-panel shortcut should be fully visible in
    // the timeline and render range. Extend the comp only for the newly inserted layers.
    if picture_video_import && !created_layers.is_empty() {
        let current_duration = s.project.comp(cid).map(|comp| comp.duration.seconds()).unwrap_or(0.0);
        let required_end = s.project.comp(cid).and_then(|comp| {
            comp.layers.iter()
                .filter(|layer| created_layers.contains(&layer.id.0))
                .map(|layer| layer.out_point.seconds())
                .reduce(f64::max)
        });
        if let Some(required_end) = required_end.filter(|end| *end > current_duration) {
            if let Err(error) = s.execute("comp.settings", json!({"comp": cid.0, "duration": required_end})) {
                errors.push(error.to_string());
            }
        }
    }'''
        source = replace_once(source, old_add_start, new_add_start, "Apply media-only duration and fit, then extend the comp")
        source = source.replace(
            'addToComp?: bool (also add them to the active comp, at time?, index?, position? as in layer.addItem)',
            'addToComp?: bool (also add them to the active comp), picturesAndVideos?: bool (Project-panel shortcut only), stillDuration?: seconds (default 10)'
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
    source = replace_once(source, old, new, "Project footer responsive control layout")
    path.write_text(source, encoding="utf-8")


def patch_picture_video_only_media_picker(root: Path) -> None:
    """Apply an image/video-only picker only when the Project-panel shortcut requests it."""
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    marker = PICKER_MARKER
    if marker in source:
        return

    media_anchor = '''    const MEDIA: &[&str] = &[
        "png", "jpg", "jpeg", "gif", "webp", "tif", "tiff", "bmp", "exr", "dpx", "cin", "wav", "aif", "aiff", "mp3", "flac", "ogg", "opus", "svg", "pdf", "ai",
        "eps", "psd", "psb", "tga", "hdr", "gltf", "glb", "obj", "stl", "fbx", "json", "csv", "tsv",
    ];
'''
    picture_video = '''    // EFFECTCRAFT_ANDROID_PICTURE_VIDEO_PICKER_V2
    // The standard File > Import picker keeps the full original MEDIA list.
    // Only the dedicated Project-panel button asks for this narrower image/video list.
    const PICTURE_VIDEO: &[&str] = &[
        "png", "jpg", "jpeg", "gif", "webp", "tif", "tiff", "bmp", "exr", "dpx", "cin",
        "svg", "psd", "psb", "tga", "hdr",
    ];
'''
    source = replace_once(source, media_anchor, media_anchor + picture_video, "Add a dedicated picture/video extension list")
    footage_anchor = '''    let footage = |more: &[&'static str]| effectcraft_project::VIDEO_EXTENSIONS.iter().chain(more).copied().collect::<Vec<_>>();
'''
    footage_new = footage_anchor + '''    let pictures_and_videos = params.get("picturesAndVideos").and_then(Value::as_bool) == Some(true);
    let import_extensions = if pictures_and_videos { footage(PICTURE_VIDEO) } else { footage(MEDIA) };
'''
    source = replace_once(source, footage_anchor, footage_new, "Select image/video extensions only for dedicated shortcut")
    source = source.replace(
        'Ask::Import => crate::FileDialog::Open { exts: footage(MEDIA).iter().map(|e| e.to_string()).collect(), many: key == "paths" },',
        'Ask::Import => crate::FileDialog::Open { exts: import_extensions.iter().map(|e| e.to_string()).collect(), many: key == "paths" },',
    )
    source = source.replace(
        'picked_value(key, f(&footage(MEDIA)))',
        'picked_value(key, f(&import_extensions))',
    )
    if "Ask::Import => crate::FileDialog::Open { exts: import_extensions.iter()" not in source:
        raise SystemExit("The async picture/video picker did not use the scoped extension list")
    if "picked_value(key, f(&import_extensions))" not in source:
        raise SystemExit("The synchronous picture/video picker did not use the scoped extension list")
    path.write_text(source, encoding="utf-8")




def patch_project_new_comp_from_selected_media(root: Path) -> None:
    """Intentionally preserve the original New Composition dialog; media import has its own action."""
    return




def patch_new_comp_layer_fit(root: Path) -> None:
    """Make New Comp from Selection's optional fitToComp parameter opt-in."""
    path = root / "crates/engine/src/cmd/file_more.rs"
    source = path.read_text(encoding="utf-8")
    old = 'layers.push(s.execute("layer.addItem", json!({"comp": cid.0, "item": item.0, "duration": still}))?["layer"].clone());'
    new = 'layers.push(s.execute("layer.addItem", json!({"comp": cid.0, "item": item.0, "duration": still, "fitToComp": b_p(p, "fitToComp").unwrap_or(false)}))?["layer"].clone());'
    source = replace_once(source, old, new, "Pass the explicit fitToComp option to new compositions")
    old_spec = '{duration? (s, for stills), single?: bool (one comp for all), dimensionsFrom?: index, sequence?: bool, overlap?: bool, overlapDuration? (s), transition?: off|dissolveFront|crossDissolve, addToRenderQueue?: bool} → {comps}'
    new_spec = '{duration? (s, for stills), single?: bool (one comp for all), dimensionsFrom?: index, sequence?: bool, overlap?: bool, overlapDuration? (s), transition?: off|dissolveFront|crossDissolve, addToRenderQueue?: bool, fitToComp?: bool} → {comps}'
    source = replace_once(source, old_spec, new_spec, "Document optional fitToComp on New Comp from Selection")
    path.write_text(source, encoding="utf-8")




def patch_timeline_touch_trim_handles(root: Path) -> None:
    """Provide a larger touch target and visible Out-edge handle on Android."""
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    if TRIM_MARKER in source:
        return
    old_constants = '''const TRIM_OUTSIDE: f32 = 4.0;
const TRIM_INSIDE: f32 = 5.0;'''
    new_constants = '''// EFFECTCRAFT_ANDROID_TOUCH_TRIM_HANDLES_V1
// Wider hit areas make the In/Out handles usable with a finger on a phone.
const TRIM_OUTSIDE: f32 = 18.0;
const TRIM_INSIDE: f32 = 12.0;'''
    source = replace_once(source, old_constants, new_constants, "Increase finger-sized layer trim zones")
    old_paint = '''    if is_sel {
        gp.rect_stroke(bar, 0.0, Stroke::new(1.0, Color32::from_white_alpha(90)), StrokeKind::Inside);
    }
    (bar, lc)'''
    new_paint = '''    if is_sel {
        gp.rect_stroke(bar, 0.0, Stroke::new(1.0, Color32::from_white_alpha(90)), StrokeKind::Inside);
        // A visible grip at the right edge is the Out-point handle; dragging it extends
        // both the layer and, when needed, the composition's time range.
        let grip_height = (bar.height() - 4.0).max(8.0).min(18.0);
        let grip = Rect::from_center_size(bar.right_center(), vec2(4.0, grip_height));
        gp.rect_filled(grip, 2.0, Color32::from_white_alpha(230));
    }
    (bar, lc)'''
    source = replace_once(source, old_paint, new_paint, "Draw the selected layer Out-edge handle")
    path.write_text(source, encoding="utf-8")


def patch_timeline_right_edge_extends_composition(root: Path) -> None:
    """Dragging a layer's right edge may extend the composition instead of stopping at its end."""
    timing_path = root / "crates/engine/src/cmd/layer/timing.rs"
    source = timing_path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_EXTEND_COMP_ON_LAYER_OUT_DRAG_V1"
    if marker not in source:
        old_flag = '    let (in_delta, out_delta) = (snap("inDelta"), snap("outDelta"));\n'
        new_flag = old_flag + '    let extend_comp = b_p(p, "extendComp").unwrap_or(false);\n'
        source = replace_once(source, old_flag, new_flag, "Enable composition extension for timeline Out-edge drags")

        old_out = '''                    if let Some(d) = out_delta {
                        l.out_point = (l.out_point + d).min(comp_dur.max(l.out_point)).max(l.in_point + fd);
                    }
'''
        new_out = '''                    if let Some(d) = out_delta {
                        let requested_out = l.out_point + d;
                        l.out_point = if extend_comp {
                            requested_out.max(l.in_point + fd)
                        } else {
                            requested_out.min(comp_dur.max(l.out_point)).max(l.in_point + fd)
                        };
                    }
'''
        source = replace_once(source, old_out, new_out, "Allow right-edge drag to pass the current composition end")

        old_end = '''        }
        Ok(())
    })?;
    Ok(Value::Null)
}'''
        new_end = '''        }
        // EFFECTCRAFT_ANDROID_EXTEND_COMP_ON_LAYER_OUT_DRAG_V1
        // When the user pulls a layer's Out edge past the composition end, grow the
        // composition and (when it previously followed the comp end) its work area too.
        // This keeps the newly visible clip duration, ruler and export range in sync.
        if extend_comp {
            let old_duration = comp_dur;
            let required_end = comp.layers.iter().fold(old_duration, |end, layer| end.max(layer.out_point));
            if required_end > old_duration {
                comp.duration = required_end;
                if comp.work_area.1 == old_duration {
                    comp.work_area.1 = required_end;
                }
            }
        }
        Ok(())
    })?;
    Ok(Value::Null)
}'''
        timing_start = source.find("pub(super) fn timing(")
        timing_end = source.find("\npub(super) fn move_frames", timing_start)
        if timing_start < 0 or timing_end < 0:
            raise SystemExit("Could not isolate the layer timing command for the composition-extension patch")
        timing_fn = source[timing_start:timing_end]
        timing_fn = replace_once(timing_fn, old_end, new_end, "Extend composition after an Out-edge drag")
        source = source[:timing_start] + timing_fn + source[timing_end:]
        timing_path.write_text(source, encoding="utf-8")

    timeline_path = root / "crates/ui-egui/src/panels/timeline.rs"
    timeline = timeline_path.read_text(encoding="utf-8")
    ui_marker = "EFFECTCRAFT_ANDROID_LAYER_OUT_DRAG_EXTENDS_COMP_V1"
    if ui_marker not in timeline:
        old_match = '''                let params = match kind {
                    "move" => json!({"layers": targets, "delta": d, "merge": drag_key}),
                    "in" => json!({"layers": targets, "inDelta": d, "merge": drag_key}),
                    _ => json!({"layers": targets, "outDelta": d, "merge": drag_key}),
                };
'''
        new_match = '''                // EFFECTCRAFT_ANDROID_LAYER_OUT_DRAG_EXTENDS_COMP_V1
                // Right-edge trimming may extend the comp itself; left-edge trimming and
                // layer movement retain their original behavior.
                let params = match kind {
                    "move" => json!({"layers": targets, "delta": d, "merge": drag_key}),
                    "in" => json!({"layers": targets, "inDelta": d, "merge": drag_key}),
                    _ => json!({"layers": targets, "outDelta": d, "extendComp": true, "merge": drag_key}),
                };
'''
        timeline = replace_once(timeline, old_match, new_match, "Enable composition extension from the layer Out-edge handle")
        timeline_path.write_text(timeline, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_project_panel_import_button(root)
    patch_file_import_auto_add(root)
    patch_layer_add_item_fit(root)
    patch_layer_add_item_fit_spec(root)
    patch_picture_video_only_media_picker(root)
    # Keep the original New Composition menu/dialog unchanged; fitToComp is opt-in.
    patch_new_comp_layer_fit(root)
    patch_project_panel_footer_responsive(root)
    patch_timeline_touch_trim_handles(root)
    patch_timeline_right_edge_extends_composition(root)
    print("Added separate Project-panel buttons for image/video import and project import.")
    print("Only the dedicated Media button filters to pictures/videos and auto-adds them to the comp.")
    print("Still-image duration follows the user's Import preferences and has no artificial duration ceiling; Out edge remains freely adjustable.")
    print("All generic File > Import and New Composition behavior remains unchanged.")


if __name__ == "__main__":
    main()
