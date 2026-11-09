#!/usr/bin/env python3
"""Show a dismissible creator attribution notice on every EffectCraft app launch."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_STARTUP_ATTRIBUTION_NOTICE_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    path = root / "crates/ui-egui/src/app.rs"
    if not root.is_dir() or not path.is_file():
        raise SystemExit(f"EFFECTCRAFT_DIR must point to EffectCraft source; missing {path}")

    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Startup attribution notice is already installed.")
        return

    ui_anchor = """    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        self.draw(ui, frame);
    }"""
    ui_replacement = """    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        self.draw(ui, frame);
        effectcraft_startup_attribution_notice(ui.ctx());
    }"""
    source = replace_once(source, ui_anchor, ui_replacement, "app UI startup notice call")

    impl_anchor = "impl eframe::App for EffectcraftApp {"
    helper = r'''
// EFFECTCRAFT_ANDROID_STARTUP_ATTRIBUTION_NOTICE_V1
/// Show the creator attribution once per app process. Egui's temporary context state
/// resets on the next app launch, so the notice appears again after every reopen.
fn effectcraft_startup_attribution_notice(ctx: &egui::Context) {
    let dismissed_id = egui::Id::new("effectcraft-startup-attribution-dismissed");
    if ctx.data(|data| data.get_temp::<bool>(dismissed_id).unwrap_or(false)) {
        return;
    }

    let screen = ctx.content_rect();
    let mut dismissed = false;
    egui::Window::new("软件说明")
        .id(egui::Id::new("effectcraft-startup-attribution-window"))
        .order(egui::Order::Foreground)
        .fixed_pos(screen.center() - egui::vec2(164.0, 78.0))
        .fixed_size(328.0, 156.0)
        .movable(false)
        .collapsible(false)
        .resizable(false)
        .title_bar(false)
        .show(ctx, |ui| {
            ui.add_space(12.0);
            ui.vertical_centered(|ui| {
                ui.heading("软件说明");
                ui.add_space(14.0);
                ui.label("该Ae软件由千千改装与新增功能，QQ号：1939023875");
                ui.add_space(18.0);
                if ui.button("OK").clicked() {
                    dismissed = true;
                }
            });
        });

    if dismissed {
        ctx.data_mut(|data| data.insert_temp(dismissed_id, true));
    }
}

'''
    source = replace_once(source, impl_anchor, helper + impl_anchor, "startup attribution notice helper")
    path.write_text(source, encoding="utf-8")
    print("Installed a centered startup attribution page with an OK button; it appears on every new app launch.")


if __name__ == "__main__":
    main()
