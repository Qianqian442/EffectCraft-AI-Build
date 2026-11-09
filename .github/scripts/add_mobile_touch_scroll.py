#!/usr/bin/env python3
"""Enable finger-drag scrolling across EffectCraft panels that use custom scrolling."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_TOUCH_SCROLL_EVERYWHERE_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_shared_panel_scroll(root: Path) -> None:
    path = root / "crates/ui-egui/src/widgets.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_PANEL_SCROLL_TOUCH_DRAG_V1"
    if marker in source:
        return

    old = '''        if ui.rect_contains_pointer(area) {
            offset -= ui.input(|i| i.smooth_scroll_delta.y);
        }
        let gutter: Gutter = ui.data(|d| d.get_temp(id.with("gutter"))).unwrap_or_default();
'''
    new = '''        if ui.rect_contains_pointer(area) {
            offset -= ui.input(|i| i.smooth_scroll_delta.y);
        }
        // EFFECTCRAFT_ANDROID_PANEL_SCROLL_TOUCH_DRAG_V1
        // On touch devices, a drag that begins on the panel background scrolls its rows.
        // Child controls are registered after begin() and keep their own tap/drag gestures;
        // the scrollbar remains available as a precise alternative.
        if ui.input(|i| i.has_touch_screen()) {
            let touch_pan = ui.interact(area, id.with("touch-pan"), Sense::drag());
            if touch_pan.dragged() {
                offset -= ui.input(|i| i.pointer.delta().y);
                ui.ctx().request_repaint();
            }
        }
        let gutter: Gutter = ui.data(|d| d.get_temp(id.with("gutter"))).unwrap_or_default();
'''
    source = replace_once(source, old, new, "Shared panel touch scrolling")
    path.write_text(source, encoding="utf-8")


def patch_project_panel(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/project.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_PROJECT_TOUCH_SCROLL_V1"
    if marker in source:
        return

    source = replace_once(
        source,
        "fn hscroll_wheel(app: &mut EffectcraftApp, ui: &egui::Ui, list: Rect, overflow: f32) {",
        "fn hscroll_wheel(app: &mut EffectcraftApp, ui: &egui::Ui, list: Rect, overflow: f32, empty: &egui::Response) {",
        "Project panel horizontal touch-scroll signature",
    )
    wheel_old = '''        app.ui.project_hscroll = (app.ui.project_hscroll - d).clamp(0.0, overflow);
    }
}
'''
    wheel_new = '''        app.ui.project_hscroll = (app.ui.project_hscroll - d).clamp(0.0, overflow);
        // EFFECTCRAFT_ANDROID_PROJECT_TOUCH_SCROLL_V1
        // In the blank list area, a predominantly horizontal finger drag pans optional columns.
        if ui.input(|i| i.has_touch_screen()) && empty.dragged() {
            let delta = ui.input(|i| i.pointer.delta());
            if delta.x.abs() > delta.y.abs() {
                app.ui.project_hscroll = (app.ui.project_hscroll - delta.x).clamp(0.0, overflow);
            }
        }
    }
}
'''
    source = replace_once(source, wheel_old, wheel_new, "Project horizontal finger scrolling")

    marquee_old = '''    if let (Some(start), Some(end)) = (ctx.input(|i| i.pointer.press_origin()), empty.interact_pointer_pos())
        && empty.dragged()
    {
'''
    marquee_new = '''    if let (Some(start), Some(end)) = (ctx.input(|i| i.pointer.press_origin()), empty.interact_pointer_pos())
        && empty.dragged()
        && !ctx.input(|i| i.has_touch_screen())
    {
'''
    source = replace_once(source, marquee_old, marquee_new, "Keep mouse marquee while touch swipes scroll")

    source = replace_once(
        source,
        "    hscroll_wheel(app, ui, wheel_area, overflow);",
        "    hscroll_wheel(app, ui, wheel_area, overflow, &empty);",
        "Project panel touch horizontal scroll call",
    )

    scroll_old = '''    let (scroll, max_scroll) = update_scroll(app, ui, &ctx, wheel_area, &rows, moved);
    if gutter != (max_scroll > 0.0) {
'''
    scroll_new = '''    let (mut scroll, max_scroll) = update_scroll(app, ui, &ctx, wheel_area, &rows, moved);
    // A vertical finger swipe in the list's blank/background area scrolls rows rather than
    // drawing a mouse-style marquee. Item rows retain their native drag/drop behaviour.
    if ui.input(|i| i.has_touch_screen()) && empty.dragged() {
        let delta = ui.input(|i| i.pointer.delta());
        if delta.y.abs() >= delta.x.abs() {
            scroll = (scroll - delta.y).clamp(0.0, max_scroll);
            app.ui.project_scroll = scroll;
        }
    }
    if gutter != (max_scroll > 0.0) {
'''
    source = replace_once(source, scroll_old, scroll_new, "Project vertical finger scrolling")
    path.write_text(source, encoding="utf-8")


def patch_timeline(root: Path) -> None:
    path = root / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_TIMELINE_TOUCH_SCROLL_V1"
    if marker in source:
        return

    helper_anchor = "/// Mouse wheel and pinch over the rows: zoom time or scroll.\n"
    helper = r'''// EFFECTCRAFT_ANDROID_TIMELINE_TOUCH_SCROLL_V1
/// Finger drags on unused timeline space scroll the layer list vertically and the time range
/// horizontally. Keyframe, layer, marker and handle widgets above this background keep priority.
fn android_timeline_touch_scroll(app: &mut EffectcraftApp, ui: &egui::Ui, g: &Rw, response: &egui::Response) {
    if !ui.input(|i| i.has_touch_screen()) || !response.dragged() {
        return;
    }
    let delta = ui.input(|i| i.pointer.delta());
    if delta.y.abs() >= delta.x.abs() {
        app.ui.timeline.scroll_y = (app.ui.timeline.scroll_y - delta.y).clamp(0.0, g.tl.max_scroll);
    } else {
        let pointer_x = ui.input(|i| i.pointer.interact_pos()).map(|p| p.x).unwrap_or(g.tl.graph_x0);
        if pointer_x < g.tl.graph_x0 && g.tl.overflow > 0.0 {
            app.ui.timeline.outline_scroll = (app.ui.timeline.outline_scroll - delta.x).clamp(0.0, g.tl.overflow);
        } else if app.ui.timeline.pps.is_some() {
            let start = app.ui.timeline.start;
            let pps = g.tl.pps;
            let last = (g.tl.comp.duration.seconds() - (g.tl.tm.t(g.tl.graph_x1) - g.tl.tm.start)).max(start).max(0.0);
            app.ui.timeline.start = (start - delta.x as f64 / pps).clamp(0.0, last);
        }
    }
    ui.ctx().request_repaint();
}

'''
    source = replace_once(source, helper_anchor, helper + helper_anchor, "Timeline finger pan helper")

    before_draw = '''    let mut rw = begin_rows(app, ui, tl);
    let g = &mut rw;
    draw_rows(app, ui, g, &ectx);
    ui.set_clip_rect(g.full_clip);
'''
    after_draw = '''    let mut rw = begin_rows(app, ui, tl);
    // Register the background first so the actual row/keyframe controls drawn below keep
    // their gestures; a finger drag on free timeline space pans the list/time range.
    let touch_pan = ui.input(|i| i.has_touch_screen()).then(|| {
        ui.interact(rw.tl.rows_rect, egui::Id::new("effectcraft-timeline-touch-pan"), Sense::drag())
    });
    let g = &mut rw;
    draw_rows(app, ui, g, &ectx);
    if let Some(response) = touch_pan.as_ref() {
        android_timeline_touch_scroll(app, ui, g, response);
    }
    ui.set_clip_rect(g.full_clip);
'''
    source = replace_once(source, before_draw, after_draw, "Timeline touch scroll response")
    path.write_text(source, encoding="utf-8")


def patch_preview_clock(root: Path) -> None:
    path = root / "crates/ui-egui/src/app/frame.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_PREVIEW_CONTINUOUS_TICK_V1"
    if marker in source:
        return
    old = '''            self.advance_playback(ctx, scale, now, active, cid);
        }
        self.drain_control(ctx, now);'''
    new = '''            self.advance_playback(ctx, scale, now, active, cid);
            // EFFECTCRAFT_ANDROID_PREVIEW_CONTINUOUS_TICK_V1
            // Keep the monotonic playback clock advancing on Android hosts that coalesce
            // immediate repaint requests while the preview viewer is already fully cached.
            if self.playback.playing {
                ctx.request_repaint_after(std::time::Duration::from_millis(16));
            }
        }
        self.drain_control(ctx, now);'''
    source = replace_once(source, old, new, "Continuous preview clock refresh")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "vendor/effectcraft"))
    patch_shared_panel_scroll(root)
    patch_project_panel(root)
    patch_timeline(root)
    patch_preview_clock(root)


if __name__ == "__main__":
    main()
