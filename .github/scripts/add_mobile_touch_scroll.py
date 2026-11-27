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
    # Never register the complete panel as a drag target: it can steal taps from
    # child buttons, sliders, file controls and other interactive widgets.
    marker = "EFFECTCRAFT_ANDROID_PANEL_SCROLL_TOUCH_DRAG_V1"
    if marker in source:
        old = '''        // EFFECTCRAFT_ANDROID_PANEL_SCROLL_TOUCH_DRAG_V1
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
'''
        if source.count(old) != 1:
            raise SystemExit("The old full-panel touch drag block changed; refusing an unsafe partial edit")
        source = source.replace(old, "", 1)
        path.write_text(source, encoding="utf-8")
    if 'id.with("touch-pan")' in source:
        raise SystemExit("Full-panel touch drag still intercepts child controls")
    print("Removed full-panel touch interception; kept dedicated blank-area Project/Timeline scrolling.")

def patch_effect_browser_inertia(root: Path) -> None:
    widgets_path = root / "crates/ui-egui/src/widgets.rs"
    widgets = widgets_path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_EFFECT_BROWSER_INERTIA_V1"
    if marker not in widgets:
        anchor = "    pub fn begin(ui: &mut Ui, id: egui::Id, area: Rect) -> Self {"
        method = r'''    /// Touch scrolling with a short velocity tail, used by Effects & Presets only.
    pub fn begin_with_inertia(ui: &mut Ui, id: egui::Id, area: Rect) -> Self {
        // Preserve the existing clipping, wheel and finger-follow behaviour.
        let mut scroll = Self::begin(ui, id, area);
        // EFFECTCRAFT_ANDROID_EFFECT_BROWSER_INERTIA_V1
        // Retain a small finger-release velocity so a long effects list does not stop
        // abruptly when the user lifts a finger. Active child drags keep their ownership.
        let state_id = id.with("touch-inertia-v1");
        let (mut velocity, was_active): (f32, bool) =
            ui.data(|d| d.get_temp(state_id)).unwrap_or((0.0, false));
        let touch_pan = ui.input(|i| {
            i.has_touch_screen()
                && i.pointer.primary_down()
                && i.pointer.press_origin().is_some_and(|origin| area.contains(origin))
        }) && ui.ctx().dragged_id().is_none();
        let dt = ui.input(|i| i.stable_dt.max(1.0 / 120.0));
        if touch_pan {
            let delta = ui.input(|i| i.pointer.delta());
            if delta.y.abs() >= delta.x.abs() && delta.y.abs() > 0.1 {
                // PanelScroll::begin has already applied this frame's finger displacement.
                velocity = (-delta.y / dt).clamp(-4200.0, 4200.0);
            } else {
                velocity = 0.0;
            }
        } else if !was_active && velocity.abs() > 24.0 {
            let (_, max): (f32, f32) = ui.data(|d| d.get_temp(scroll.id)).unwrap_or_default();
            let previous = scroll.offset;
            let next = (previous + velocity * dt).clamp(0.0, max.max(0.0));
            scroll.offset = next;
            if (next - previous).abs() > 0.01 {
                velocity *= (-8.5 * dt).exp();
                if velocity.abs() > 22.0 {
                    ui.ctx().request_repaint_after(std::time::Duration::from_millis(16));
                } else {
                    velocity = 0.0;
                }
            } else {
                // Stop at the top/bottom instead of fighting the scroll boundary.
                velocity = 0.0;
            }
        } else if !was_active {
            velocity = 0.0;
        }
        ui.data_mut(|d| d.insert_temp(state_id, (velocity, touch_pan)));
        scroll
    }

'''
        widgets = replace_once(widgets, anchor, method + anchor, "Effects browser inertial PanelScroll method")
        widgets_path.write_text(widgets, encoding="utf-8")
        print("Added optional inertial touch scrolling to PanelScroll.")
    elif "pub fn begin_with_inertia" not in widgets:
        raise SystemExit("Effects browser inertia marker exists but its method is missing.")

    effects_path = root / "crates/ui-egui/src/panels/effects_presets.rs"
    effects = effects_path.read_text(encoding="utf-8")
    call_old = 'widgets::PanelScroll::begin(ui, egui::Id::unique("fx-scroll"), list)'
    call_new = 'widgets::PanelScroll::begin_with_inertia(ui, egui::Id::unique("fx-scroll"), list)'
    if call_new not in effects:
        effects = replace_once(effects, call_old, call_new, "Use inertial touch scroll for Effects & Presets")
        effects_path.write_text(effects, encoding="utf-8")
    print("Effects & Presets now uses finger-release inertia; row heights and button geometry are unchanged.")


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
    patch_effect_browser_inertia(root)
    patch_project_panel(root)
    patch_timeline(root)
    patch_preview_clock(root)


if __name__ == "__main__":
    main()
