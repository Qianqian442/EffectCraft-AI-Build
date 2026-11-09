#!/usr/bin/env python3
"""Keep every EffectCraft toolbar control reachable on narrow Android screens."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_RESPONSIVE_HEADER_SCROLL_V1"


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Responsive, horizontally scrollable Android toolbar is already installed.")
        return

    start = source.find("pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {")
    end = source.find("/// The brand mark (About) and the Home button;", start)
    if start < 0 or end < 0:
        raise SystemExit("Could not uniquely locate the EffectCraft header show() function.")

    old = source[start:end]
    required = [
        "brand_and_home(app, ui,",
        "plugin_import_button(app, ui,",
        "puppet_quick_button(app, ui,",
        "tool_slots(app, ui,",
        "tool_options_bar(app, ui,",
        "snapping_toggle(app, ui,",
        "right_side(app, ui,",
    ]
    missing = [item for item in required if item not in old]
    if missing:
        raise SystemExit("Header controls are not in the expected build state: " + ", ".join(missing))

    replacement = r'''/// EFFECTCRAFT_ANDROID_RESPONSIVE_HEADER_SCROLL_V1
/// On narrow screens the full toolbar becomes touch-scrollable instead of allowing controls
/// to overlap or be clipped. All original buttons remain in their original order and keep
/// their existing handlers, hit targets, shortcuts and accessibility names.
pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    ui.painter().rect_filled(rect, 0.0, t.header_bg);
    ui.painter().line_segment(
        [rect.left_bottom(), rect.right_bottom()],
        Stroke::new(1.0, t.app_bg),
    );

    // Keep a dedicated export hit target pinned at the right edge. The remaining tools scroll
    // horizontally in the space to its left, so Export is always visible on narrow phones.
    let export_rect = Rect::from_min_max(
        pos2(rect.max.x - 58.0, rect.min.y + 3.0),
        pos2(rect.max.x - 4.0, rect.max.y - 3.0),
    );
    let scroll_rect = Rect::from_min_max(rect.min, pos2(export_rect.min.x - 4.0, rect.max.y));

    // Constrain the scroll area to the available header rectangle.
    let mut header_ui = ui.new_child(
        egui::UiBuilder::new()
            .max_rect(scroll_rect)
            .layout(egui::Layout::left_to_right(egui::Align::Center)),
    );
    egui::ScrollArea::horizontal()
        .id_salt("effectcraft-android-header-horizontal-scroll")
        .auto_shrink([false, false])
        .scroll_bar_visibility(egui::scroll_area::ScrollBarVisibility::AlwaysVisible)
        .show(&mut header_ui, |scroll_ui| {
            let origin = scroll_ui.min_rect().min;
            let p = scroll_ui.painter().clone();
            let cy = origin.y + scroll_rect.height() * 0.5;
            let x = origin.x + if app.integrated_titlebar && !app.ui.show_menu_bar { 80.0 } else { 10.0 };
            let x = brand_and_home(app, scroll_ui, &p, x, cy);
            let x = plugin_import_button(app, scroll_ui, x, cy);
            let x = puppet_quick_button(app, scroll_ui, x, cy);
            let x = tool_slots(app, scroll_ui, &p, x, cy);
            let x = tool_options_bar(app, scroll_ui, &p, x + 10.0, cy);
            let x = snapping_toggle(app, scroll_ui, &p, x, cy);

            // Reserve enough trailing space for community, appearance and workspace controls.
            // On a phone this makes the whole toolbar swipeable; on a wide display the original
            // right-aligned layout is preserved without introducing unnecessary scrolling.
            let content_width = scroll_rect.width().max((x - origin.x + 250.0).max(360.0));
            scroll_ui.set_min_size(vec2(content_width, scroll_rect.height()));
            let content_rect = Rect::from_min_size(origin, vec2(content_width, scroll_rect.height()));
            right_side(app, scroll_ui, &p, content_rect, x, cy);
        });

    let export_response = widgets::text_button(
        ui,
        export_rect,
        crate::i18n::tr("导出"),
        true,
        &t,
        egui::Id::new("effectcraft-fixed-export-button"),
    ).on_hover_text("导出视频");
    app.auto.add_response("header.exportFixed", &export_response, "导出视频");
    if export_response.clicked() {
        ui.ctx().data_mut(|data| {
            data.insert_temp(egui::Id::new("effectcraft-export-dialog-open"), true);
        });
    }

    // Keep modal dialogs outside the horizontally clipped toolbar child. The export click
    // handler sets this state above; rendering the modal inside ScrollArea would clip it and
    // allow the scroll content to consume its touch events.
    export_dialog(app, ui);
    export_progress_dialog(app, ui);
}

'''
    source = source[:start] + replacement + source[end:]
    path.write_text(source, encoding="utf-8")
    print("Installed responsive horizontal scrolling for the Android toolbar.")
    print("All toolbar buttons remain enabled and reachable by horizontal swipe.")


if __name__ == "__main__":
    main()
