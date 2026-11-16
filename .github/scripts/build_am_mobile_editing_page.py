#!/usr/bin/env python3
"""Build a dedicated Alight Motion-style portrait editing page without replacing Ae features."""
from __future__ import annotations

import os
from pathlib import Path


WORKSPACE = "AM 竖屏"
HEADER_MARKER = "EFFECTCRAFT_AM_MOBILE_EDITING_HEADER_V1"
TIMELINE_MARKER = "EFFECTCRAFT_AM_MOBILE_EDITING_TIMELINE_V1"
DOCK_MARKER = "EFFECTCRAFT_AM_MOBILE_EDITING_DOCK_V1"
STARTUP_MARKER = "EFFECTCRAFT_AM_CANONICAL_MOBILE_DOCK_RESTORE_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_dock(root: Path) -> None:
    path = root / "crates/ui-egui/src/dock.rs"
    source = path.read_text(encoding="utf-8")
    if DOCK_MARKER not in source:
        old = '''        // AM-style portrait workspace: viewer at the top; Timeline, the original
        // Effects & Presets browser, Effect Controls, Properties and Project share the
        // lower tab group so every built-in EffectCraft effect remains available.
        "AM 竖屏" => vsplit(
            Ratio(0.58),
            tabs(&[Composition, Layer], 0),
            tabs(&[Timeline, EffectsPresets, EffectControls, Properties, Project], 0),
        ),'''
        new = '''        // EFFECTCRAFT_AM_MOBILE_EDITING_DOCK_V1
        // A real portrait editing page: Composition preview stays above the multi-layer
        // Timeline. The remaining native panels stay available as tabs beside Timeline.
        "AM 竖屏" => vsplit(
            Ratio(0.43),
            tabs(&[Composition], 0),
            tabs(&[Timeline, EffectControls, EffectsPresets, Properties, Project, Layer], 0),
        ),'''
        source = replace_once(source, old, new, "replace the simplified AM dock with the mobile editor page")
        path.write_text(source, encoding="utf-8")
    if DOCK_MARKER not in path.read_text(encoding="utf-8"):
        raise SystemExit("The AM mobile editing dock was not installed.")


def patch_workspace_selection(root: Path) -> None:
    path = root / "crates/ui-egui/src/app/window.rs"
    source = path.read_text(encoding="utf-8")
    marker = '        self.ui.dock = if name == "AM 竖屏" {'
    if marker not in source:
        old = '        self.ui.dock = self.ui.saved_workspaces.get(name).cloned().unwrap_or_else(|| dock::Workspace::new(dock::workspace(name)));'
        new = '''        // EFFECTCRAFT_AM_CANONICAL_MOBILE_DOCK_RESTORE_V1
        // Do not revive a previously saved simplified AM layout after a mode switch.
        self.ui.dock = if name == "AM 竖屏" {
            dock::Workspace::new(dock::workspace(name))
        } else {
            self.ui.saved_workspaces.get(name).cloned().unwrap_or_else(|| dock::Workspace::new(dock::workspace(name)))
        };'''
        source = replace_once(source, old, new, "force the canonical AM page on mode switch")
        path.write_text(source, encoding="utf-8")
    if "EFFECTCRAFT_AM_CANONICAL_MOBILE_DOCK_RESTORE_V1" not in path.read_text(encoding="utf-8"):
        raise SystemExit("AM layout switching does not force the canonical mobile editing dock.")


def patch_startup(root: Path) -> None:
    path = root / "crates/ui-egui/src/app.rs"
    source = path.read_text(encoding="utf-8")
    if STARTUP_MARKER not in source:
        old = '''        let app = app.with_ui_commands();
        // Apply the orientation of the persisted workspace before the first editor frame.
        crate::android_layout::set_workspace_portrait(app.ui.workspace == "AM 竖屏");
        app'''
        new = '''        let mut app = app.with_ui_commands();
        // EFFECTCRAFT_AM_CANONICAL_MOBILE_DOCK_RESTORE_V1
        // Older builds saved only the simplified two-panel AM layout. Rebuild the complete
        // current mobile editing page before the first frame when AM was the saved workspace.
        if app.ui.workspace == "AM 竖屏" {
            app.ui.dock = crate::dock::Workspace::new(crate::dock::workspace("AM 竖屏"));
        }
        // Apply the orientation of the persisted workspace before the first editor frame.
        crate::android_layout::set_workspace_portrait(app.ui.workspace == "AM 竖屏");
        app'''
        source = replace_once(source, old, new, "restore the canonical AM page at startup")
        path.write_text(source, encoding="utf-8")
    if STARTUP_MARKER not in path.read_text(encoding="utf-8"):
        raise SystemExit("A previously saved simplified AM layout can still override the new page.")


def patch_header(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    if HEADER_MARKER in source:
        return

    helper_anchor = "/// The brand mark (About) and the Home button; returns the x after them."
    helper = r'''
// EFFECTCRAFT_AM_MOBILE_EDITING_HEADER_V1
// AM's editor top bar: back to projects, composition name, native Undo/Redo and Export.
// The separate Ae/AM chooser remains in its own second row below this bar.
fn am_mobile_editing_header(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let p = ui.painter().clone();
    let top = Rect::from_min_max(rect.min, pos2(rect.max.x, (rect.min.y + 40.0).min(rect.max.y)));
    p.rect_filled(top, 0.0, t.header_bg);
    p.line_segment([top.left_bottom(), top.right_bottom()], Stroke::new(1.0, t.separator));
    let cy = top.center().y;

    let back = Rect::from_center_size(pos2(top.min.x + 22.0, cy), vec2(30.0, 30.0));
    let back_response = ui.interact(back, egui::Id::new("am-editor-back-projects"), Sense::click());
    icons::paint(&p, back.shrink(5.0), Icon::ChevronLeft, if back_response.hovered() { t.text } else { t.text_dim });
    app.auto.add_response("header.amBack", &back_response, "返回项目");
    if back_response.clicked() {
        app.ui.start_screen = true;
    }

    let export_rect = Rect::from_min_max(
        pos2((top.max.x - 68.0).max(top.min.x + 190.0), cy - 14.0),
        pos2(top.max.x - 6.0, cy + 14.0),
    );
    let export_response = ui.interact(export_rect, egui::Id::new("am-editor-export"), Sense::click());
    p.rect_filled(export_rect, 6.0, if export_response.hovered() { t.accent } else { t.panel_bg });
    p.text(export_rect.center(), Align2::CENTER_CENTER, "导出", Tokens::semibold(12.0), t.text);
    app.auto.add_response("header.amExport", &export_response, "导出视频或工程");
    if export_response.clicked() {
        ui.ctx().data_mut(|d| d.insert_temp(egui::Id::new("effectcraft-export-dialog-open"), true));
    }

    let history_x = (export_rect.min.x - 62.0).max(top.min.x + 108.0);
    let history_end = history_buttons(app, ui, &p, history_x, cy);
    let title_rect = Rect::from_min_max(
        pos2(back.max.x + 5.0, top.min.y),
        pos2((history_x - 7.0).max(back.max.x + 5.0), top.max.y),
    );
    let project_name = app.session.active_comp_id()
        .and_then(|id| app.session.project.item(id))
        .map(|item| item.name.clone())
        .unwrap_or_else(|| "未命名工程".to_string());
    p.with_clip_rect(title_rect).text(
        title_rect.left_center(),
        Align2::LEFT_CENTER,
        project_name,
        Tokens::semibold(13.0),
        t.text,
    );
    let _ = history_end;
}

'''
    source = replace_once(source, helper_anchor, helper + helper_anchor, "insert AM editing header renderer")

    show_anchor = "pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {\n"
    show_branch = '''pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    if app.ui.workspace == "AM 竖屏" && !app.ui.start_screen {
        am_mobile_editing_header(app, ui, rect);
        // Keep the layout selector in its dedicated, non-overlapping second row.
        let layout_row = Rect::from_min_max(
            pos2(rect.min.x, rect.min.y + 40.0),
            rect.max,
        );
        layout_switch_row(app, ui, &ui.painter().clone(), layout_row);
        export_dialog(app, ui);
        export_progress_dialog(app, ui);
        return;
    }
'''
    source = replace_once(source, show_anchor, show_branch, "route AM mode to its dedicated top bar")
    path.write_text(source, encoding="utf-8")

    patched = path.read_text(encoding="utf-8")
    for token in (
        HEADER_MARKER,
        "am_mobile_editing_header(app, ui, rect);",
        "layout_switch_row(app, ui",
        "export_dialog(app, ui);",
        "export_progress_dialog(app, ui);",
    ):
        if token not in patched:
            raise SystemExit(f"AM header verification missing: {token}")


def patch_timeline(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    if TIMELINE_MARKER in source:
        return

    source = replace_once(
        source,
        "fn cols(x0: f32, width: f32, vis: Vis) -> Cols {",
        "fn cols(x0: f32, width: f32, vis: Vis, min_name_w: f32) -> Cols {",
        "make the layer-name column responsive",
    )
    source = replace_once(
        source,
        "    let name_w = (width - vis.fixed()).max(120.0);",
        "    let name_w = (width - vis.fixed()).max(min_name_w);",
        "allow narrow AM layer names",
    )

    old_geometry = '''    let header_h = 48.0;
    let ruler_h = 34.0;
    let colhdr_h = 22.0;
    let footer_h = 24.0;
    let vis = Vis::of(&app.ui.timeline);
    let left_w = (vis.fixed() + 190.0).clamp(420.0, (rect.width() * 0.72).max(420.0));'''
    new_geometry = '''    // EFFECTCRAFT_AM_MOBILE_EDITING_TIMELINE_V1
    // On a portrait phone, keep the visibility switch and layer name only. Desktop
    // switch/parent/time columns are hidden so the clip tracks retain real width.
    let am_mobile = app.ui.workspace == "AM 竖屏";
    let header_h = 48.0;
    let ruler_h = 34.0;
    let colhdr_h = 20.0;
    let footer_h = 24.0;
    let vis = if am_mobile {
        Vis {
            av: true, keys: false, label: false, num: false, comment: false,
            switches: false, modes: false, parent: false, in_: false, out: false,
            duration: false, stretch: false,
        }
    } else {
        Vis::of(&app.ui.timeline)
    };
    let min_name_w = if am_mobile { 72.0 } else { 120.0 };
    let natural_w = vis.fixed() + if am_mobile { min_name_w } else { 190.0 };
    let left_w = if am_mobile {
        natural_w
    } else {
        natural_w.clamp(420.0, (rect.width() * 0.72).max(420.0))
    };'''
    source = replace_once(source, old_geometry, new_geometry, "install compact portrait geometry")
    source = replace_once(
        source,
        "    let natural_w = vis.fixed() + 190.0;",
        "    let natural_w = vis.fixed() + if am_mobile { min_name_w } else { 190.0 };",
        "use mobile layer-list width",
    )
    source = replace_once(
        source,
        "    let cw = cols(rect.min.x - oscroll, left_w + overflow, vis);",
        "    let cw = cols(rect.min.x - oscroll, left_w + overflow, vis, min_name_w);",
        "pass compact layer column width",
    )
    source = replace_once(
        source,
        "        rh: t.row_h,",
        "        rh: if am_mobile { 30.0 } else { t.row_h },",
        "enlarge touch layer rows in AM mode",
    )

    header_anchor = "fn header_search_and_switches(app: &mut EffectcraftApp, ui: &mut egui::Ui, g: &Tl) {\n"
    transport = r'''fn header_search_and_switches(app: &mut EffectcraftApp, ui: &mut egui::Ui, g: &Tl) {
    if app.ui.workspace == "AM 竖屏" {
        let t = g.t;
        let rect = g.rect;
        let top = g.top;
        let tc_rect = g.tc_rect;
        let ctx = ui.ctx().clone();
        // AM-style transport controls: start, previous frame, play/pause, next frame, end.
        let buttons = [
            (Icon::First, "time.start", "Go to Start"),
            (Icon::StepBack, "time.previousFrame", "Previous Frame"),
            (Icon::Play, "playback.toggle", "Play / Pause"),
            (Icon::StepFwd, "time.nextFrame", "Next Frame"),
            (Icon::Last, "time.end", "Go to End"),
        ];
        let start_x = tc_rect.max.x + 8.0;
        for (index, (base_icon, command, tip)) in buttons.into_iter().enumerate() {
            let r = Rect::from_min_size(
                pos2(start_x + index as f32 * 29.0, top + 9.0),
                vec2(24.0, 24.0),
            );
            let icon = if command == "playback.toggle" && app.playback.playing {
                Icon::Pause
            } else {
                base_icon
            };
            let response = widgets::icon_button(
                ui,
                r,
                icon,
                command == "playback.toggle" && app.playback.playing,
                &t,
                egui::Id::unique(("timeline.amMobileTransport", command)),
            ).on_hover_text(crate::i18n::tr(tip));
            app.auto.add_response(&format!("timeline.amMobileTransport.{command}"), &response, tip);
            if response.clicked()
                && let Err(error) = crate::menus::invoke(app, &ctx, command, json!({}))
            {
                app.ui.status = error;
            }
        }
        return;
    }
'''
    source = replace_once(source, header_anchor, transport, "put AM transport above the clip tracks")

    source = replace_once(
        source,
        "fn time_navigator(app: &mut EffectcraftApp, ui: &mut egui::Ui, g: &Tl) {\n",
        '''fn time_navigator(app: &mut EffectcraftApp, ui: &mut egui::Ui, g: &Tl) {
    // The AM transport row occupies the desktop navigator's area.
    if app.ui.workspace == "AM 竖屏" {
        return;
    }
''',
        "remove the desktop mini navigator from the AM transport row",
    )

    old_footer = '''    let tgl = Rect::from_min_size(pos2(footer.min.x + 10.0, footer.min.y + 3.0), vec2(150.0, 18.0));
    let tresp = ui.interact(tgl, egui::Id::unique("tl-toggle-modes"), Sense::click());
    p.text(
        tgl.left_center(),
        Align2::LEFT_CENTER,
        crate::i18n::tr("Toggle Switches / Modes"),
        Tokens::ui(11.0),
        if tresp.hovered() { t.text } else { t.text_dim },
    );
    app.auto.add("timeline.toggleSwitchesModes", tgl, "Toggle Switches / Modes");
    if tresp.clicked() {
        app.ui.timeline.show_modes = !app.ui.timeline.show_modes;
    }'''
    new_footer = r'''    if app.ui.workspace == "AM 竖屏" {
        let buttons = [
            ("＋素材", "media"),
            ("效果", "effects"),
            ("属性", "properties"),
            ("项目", "project"),
        ];
        for (index, (label, kind)) in buttons.into_iter().enumerate() {
            let r = Rect::from_min_size(
                pos2(footer.min.x + 5.0 + index as f32 * 42.0, footer.min.y + 3.0),
                vec2(39.0, 18.0),
            );
            let response = ui.interact(r, egui::Id::new(("timeline.amMobileAction", kind)), Sense::click());
            p.rect_filled(r, 4.0, if response.hovered() { t.hover } else { t.field_bg });
            p.text(r.center(), Align2::CENTER_CENTER, label, Tokens::ui(9.5), if response.hovered() { t.text } else { t.text_dim });
            app.auto.add_response(&format!("timeline.amMobileAction.{kind}"), &response, label);
            if response.clicked() {
                match kind {
                    "media" => {
                        if let Err(error) = crate::menus::invoke(app, ui.ctx(), "file.import", json!({"picturesAndVideos": true})) {
                            app.ui.status = error;
                        }
                    }
                    "effects" => app.show_panel(crate::dock::PanelKind::EffectsPresets),
                    "properties" => app.show_panel(crate::dock::PanelKind::Properties),
                    "project" => app.show_panel(crate::dock::PanelKind::Project),
                    _ => {}
                }
            }
        }
    } else {
        let tgl = Rect::from_min_size(pos2(footer.min.x + 10.0, footer.min.y + 3.0), vec2(150.0, 18.0));
        let tresp = ui.interact(tgl, egui::Id::unique("tl-toggle-modes"), Sense::click());
        p.text(
            tgl.left_center(),
            Align2::LEFT_CENTER,
            crate::i18n::tr("Toggle Switches / Modes"),
            Tokens::ui(11.0),
            if tresp.hovered() { t.text } else { t.text_dim },
        );
        app.auto.add("timeline.toggleSwitchesModes", tgl, "Toggle Switches / Modes");
        if tresp.clicked() {
            app.ui.timeline.show_modes = !app.ui.timeline.show_modes;
        }
    }'''
    source = replace_once(source, old_footer, new_footer, "add AM media/effects/properties/project controls")

    path.write_text(source, encoding="utf-8")
    patched = path.read_text(encoding="utf-8")
    for token in (
        TIMELINE_MARKER,
        "timeline.amMobileTransport.",
        "timeline.amMobileAction.",
        'command == "playback.toggle"',
        "let cw = cols(rect.min.x - oscroll, left_w + overflow, vis, min_name_w);",
    ):
        if token not in patched:
            raise SystemExit(f"AM mobile Timeline verification missing: {token}")


def verify(root: Path) -> None:
    dock = (root / "crates/ui-egui/src/dock.rs").read_text(encoding="utf-8")
    header = (root / "crates/ui-egui/src/header.rs").read_text(encoding="utf-8")
    timeline = (root / "crates/ui-egui/src/panels/timeline.rs").read_text(encoding="utf-8")
    window = (root / "crates/ui-egui/src/app/window.rs").read_text(encoding="utf-8")
    app = (root / "crates/ui-egui/src/app.rs").read_text(encoding="utf-8")
    required = (
        (dock, DOCK_MARKER),
        (header, HEADER_MARKER),
        (timeline, TIMELINE_MARKER),
        (timeline, "timeline.amMobileTransport."),
        (timeline, "timeline.amMobileAction."),
        (window, "EFFECTCRAFT_AM_CANONICAL_MOBILE_DOCK_RESTORE_V1"),
        (app, STARTUP_MARKER),
        (header, "export_dialog(app, ui);"),
        (header, "export_progress_dialog(app, ui);"),
    )
    missing = [marker for content, marker in required if marker not in content]
    if missing:
        raise SystemExit("AM mobile editing page verification failed: " + ", ".join(missing))
    print("Verified the AM portrait editing page: custom top bar, persistent viewer, phone timeline, transport and bottom actions.")
    print("Ae mode, import router, project format handlers and existing export code remain in place.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source.")
    patch_dock(root)
    patch_workspace_selection(root)
    patch_startup(root)
    patch_header(root)
    patch_timeline(root)
    verify(root)


if __name__ == "__main__":
    main()
