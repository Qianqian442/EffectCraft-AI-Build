#!/usr/bin/env python3
"""Add the AM portrait workspace and Android orientation / release-signer guard.

This patch intentionally changes only workspace presentation and the Android Activity
host bridge. It does not edit project import routing, archive staging, project serializers,
render/export commands, or project file formats.
"""
from __future__ import annotations

import os
from pathlib import Path


WORKSPACE = "AM 竖屏"
MARKER = "EFFECTCRAFT_ANDROID_AM_PORTRAIT_WORKSPACE_V1"
JAVA_MARKER = "EFFECTCRAFT_ANDROID_AM_ORIENTATION_AND_SIGNER_GUARD_V1"
SIGNER_PLACEHOLDER = "__EFFECTCRAFT_SIGNING_CERT_SHA256__"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


RUST_MODULE = r'''//! Android-only bridge for switching the native Activity between sensor and AM portrait mode.

pub(crate) fn set_workspace_portrait(portrait: bool) {
    #[cfg(target_os = "android")]
    {
        let result = (|| -> Result<(), String> {
            let vm = jni::vm::JavaVM::singleton().map_err(|error| error.to_string())?;
            vm.attach_current_thread(|env| -> jni::errors::Result<()> {
                env.call_static_method(
                    jni::jni_str!("com/artcraft/effectcraft/EffectCraftActivity"),
                    jni::jni_str!("setWorkspacePortrait"),
                    jni::jni_sig!("(Z)V"),
                    &[jni::objects::JValue::Bool(portrait)],
                )?;
                Ok(())
            }).map_err(|error| error.to_string())
        })();
        if let Err(error) = result {
            log::warn!("Could not apply EffectCraft workspace orientation: {error}");
        }
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = portrait;
    }
}
'''


JAVA_IMPORTS = (
    "import android.content.pm.ActivityInfo;",
    "import android.content.pm.Signature;",
    "import android.widget.Toast;",
    "import java.security.MessageDigest;",
)

JAVA_BRIDGE = r'''
    // EFFECTCRAFT_ANDROID_AM_ORIENTATION_AND_SIGNER_GUARD_V1
    private static volatile __CLASS__ workspaceOrientationActivity;
    // Replaced by the build after the persistent release keystore is available.
    private static final String EXPECTED_SIGNING_CERT_SHA256 = "__EFFECTCRAFT_SIGNING_CERT_SHA256__";

    private boolean verifyReleaseSigningCertificate() {
        if (EXPECTED_SIGNING_CERT_SHA256 == null
                || EXPECTED_SIGNING_CERT_SHA256.length() != 64
                || EXPECTED_SIGNING_CERT_SHA256.startsWith("__")) {
            Log.e(TAG, "Release signing certificate pin was not embedded.");
            return false;
        }
        try {
            android.content.pm.PackageInfo info;
            Signature[] signers;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                info = getPackageManager().getPackageInfo(
                    getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
                if (info.signingInfo == null) return false;
                signers = info.signingInfo.getApkContentsSigners();
            } else {
                // Compatibility for older supported Android versions.
                info = getPackageManager().getPackageInfo(
                    getPackageName(), PackageManager.GET_SIGNATURES);
                signers = info.signatures;
            }
            if (signers == null || signers.length == 0) return false;
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (Signature signer : signers) {
                byte[] bytes = digest.digest(signer.toByteArray());
                StringBuilder hex = new StringBuilder(bytes.length * 2);
                for (byte value : bytes) {
                    hex.append(String.format(java.util.Locale.ROOT, "%02X", value & 0xff));
                }
                if (EXPECTED_SIGNING_CERT_SHA256.equals(hex.toString())) return true;
            }
        } catch (Throwable error) {
            Log.e(TAG, "Could not verify the Ae release signing certificate.", error);
        }
        Log.e(TAG, "APK signer mismatch: the package may have been modified or re-signed.");
        return false;
    }

    public static void setWorkspacePortrait(boolean portrait) {
        __CLASS__ activity = workspaceOrientationActivity;
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            try {
                // Freeform/desktop windows must remain resizable and must not be forced upright.
                if (activity.isDesktopOrFreeform()) return;
                activity.setRequestedOrientation(
                    portrait ? ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                             : ActivityInfo.SCREEN_ORIENTATION_SENSOR);
            } catch (Throwable error) {
                Log.w(TAG, "Could not change workspace orientation.", error);
            }
        });
    }
'''


def patch_dock(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/dock.rs"
    source = path.read_text(encoding="utf-8")
    if WORKSPACE not in source:
        source = replace_once(
            source,
            '    "Small Screen",\n',
            f'    "Small Screen",\n    "{WORKSPACE}",\n',
            "AM workspace menu entry",
        )
        source = replace_once(
            source,
            '        "Small Screen" => vsplit(\n',
            f'''        // AM-style portrait workspace: viewer at the top; Timeline, the original
        // Effects & Presets browser, Effect Controls, Properties and Project share the
        // lower tab group so every built-in EffectCraft effect remains available.
        "{WORKSPACE}" => vsplit(
            Ratio(0.58),
            tabs(&[Composition, Layer], 0),
            tabs(&[Timeline, EffectsPresets, EffectControls, Properties, Project], 0),
        ),
        "Small Screen" => vsplit(
''',
            "AM portrait workspace dock tree",
        )
        path.write_text(source, encoding="utf-8")
    if f'"{WORKSPACE}"' not in path.read_text(encoding="utf-8"):
        raise SystemExit("AM portrait workspace was not registered.")


def patch_touch_trim_handles(effectcraft: Path) -> None:
    """Reuse an existing phone-sized In/Out handle patch, or add one if absent."""
    path = effectcraft / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_AM_TOUCH_TRIM_HANDLES_V1"
    existing_marker = "EFFECTCRAFT_ANDROID_TOUCH_TRIM_HANDLES_V1"
    if marker in source:
        return
    # add_bottom_left_media_import.py runs earlier in this same build and already
    # widens the In/Out hit zones and paints a visible Out-edge grip. Reuse that
    # implementation instead of trying to replace the upstream 4/5-point constants
    # a second time. This preserves the existing duration-drag interaction.
    if existing_marker in source:
        required = (
            "const TRIM_OUTSIDE: f32 = 18.0;",
            "const TRIM_INSIDE: f32 = 12.0;",
            "let grip = Rect::from_center_size(bar.right_center(), vec2(4.0, grip_height));",
        )
        missing = [item for item in required if item not in source]
        if missing:
            raise SystemExit("Existing AM timeline trim-handle patch is incomplete: " + "; ".join(missing))
        # The final source verifier checks this AM-specific marker to make sure the
        # AM workspace retains the same touch-ready duration handle. Add a Rust comment
        # beside the shared implementation; do not duplicate or alter its hit zones.
        source = source.replace(
            existing_marker,
            existing_marker + "\n// EFFECTCRAFT_ANDROID_AM_TOUCH_TRIM_HANDLES_V1",
            1,
        )
        path.write_text(source, encoding="utf-8")
        print("Reusing the existing enlarged In/Out hit zones and visible right-edge handle.")
        return
    old = """const TRIM_OUTSIDE: f32 = 4.0;
const TRIM_INSIDE: f32 = 5.0;"""
    new = """// EFFECTCRAFT_ANDROID_AM_TOUCH_TRIM_HANDLES_V1
// Keep desktop hit targets unchanged; expand the existing In/Out trim zones for touch.
#[cfg(target_os = "android")]
const TRIM_OUTSIDE: f32 = 12.0;
#[cfg(not(target_os = "android"))]
const TRIM_OUTSIDE: f32 = 4.0;
#[cfg(target_os = "android")]
const TRIM_INSIDE: f32 = 14.0;
#[cfg(not(target_os = "android"))]
const TRIM_INSIDE: f32 = 5.0;"""
    source = replace_once(source, old, new, "AM touch-friendly layer trim handles")
    path.write_text(source, encoding="utf-8")



def patch_am_native_effect_browser(effectcraft: Path) -> None:
    """Render the existing Ae effect registry in an AM-style category/effect browser."""
    path = effectcraft / "crates/ui-egui/src/panels/effects_presets.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_NATIVE_EFFECT_BROWSER_V1"
    if marker in source:
        return
    anchor = "pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {"
    code = r'''
// EFFECTCRAFT_AM_NATIVE_EFFECT_BROWSER_V1
// AM presentation only: every item comes from the native Ae effect registry and is
// applied through the same effect.apply command as the standard Effects & Presets panel.
fn show_am_native(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let ctx = ui.ctx().clone();
    let painter = ui.painter().with_clip_rect(rect);
    let search_rect = Rect::from_min_size(rect.min + vec2(10.0, 8.0), vec2((rect.width() - 20.0).max(80.0), 30.0));
    let mut query = app.ui.effects_search.clone();
    let search_hint = tr("Search effects");
    let search = widgets::search_field(ui, search_rect, &mut query, search_hint, &t);
    a11y::text_input(&search, search_hint, &query);
    app.ui.effects_search = query.clone();
    let query_lower = query.trim().to_lowercase();
    let category_id = egui::Id::new("am-native-effect-browser-category");
    let selected_category: Option<String> = ctx.data(|d| d.get_temp(category_id));
    let mut y = search_rect.max.y + 10.0;
    let reg = effectcraft_engine::effects::all();
    let categories = effectcraft_engine::effects::categories();

    if let Some(category) = selected_category.clone() {
        let back_rect = Rect::from_min_size(pos2(rect.min.x + 8.0, y), vec2(64.0, 32.0));
        let back = ui.put(back_rect, egui::Button::new("‹"));
        if back.clicked() {
            ctx.data_mut(|d| d.remove::<String>(category_id));
        }
        let title_rect = Rect::from_min_size(pos2(back_rect.max.x + 8.0, y), vec2((rect.width() - 92.0).max(60.0), 32.0));
        painter.text(title_rect.center(), Align2::LEFT_CENTER, crate::i18n::effects::category(&category), Tokens::ui(14.0), t.text);
        y += 40.0;
        let matching: Vec<_> = reg.iter().filter(|e| e.category == category.as_str())
            .filter(|e| query_lower.is_empty() || effectcraft_engine::effects::name_matches(e, &query_lower) || crate::i18n::effects::matches(e.id, e.name, &query_lower))
            .collect();
        let gap = 8.0;
        let col_w = ((rect.width() - 24.0 - gap) / 2.0).max(90.0);
        let row_h = 66.0;
        let mut apply_id: Option<String> = None;
        for (i, effect) in matching.iter().enumerate() {
            let col = i % 2;
            let row = i / 2;
            let r = Rect::from_min_size(pos2(rect.min.x + 8.0 + col as f32 * (col_w + gap), y + row as f32 * (row_h + gap)), vec2(col_w, row_h));
            let response = ui.put(r, egui::Button::new(crate::i18n::effects::name(effect.id, effect.name)));
            if response.clicked() {
                apply_id = Some(effect.id.to_string());
            }
        }
        if let Some(id) = apply_id {
            if app.session.state.selected_layers.is_empty() {
                app.ui.status = "Select a layer to apply to".into();
            } else {
                match app.session.execute("effect.apply", serde_json::json!({"effect": id})) {
                    Err(e) => app.ui.status = e.to_string(),
                    Ok(applied) => {
                        push_recent(&mut app.ui.effects_recent, &id);
                        app.show_panel(crate::dock::PanelKind::EffectControls);
                        app.ui.focused = crate::dock::PanelKind::EffectsPresets;
                        crate::panels::effect_controls::choose_files_after_apply(app, &applied);
                    }
                }
            }
        }
    } else {
        let mut visible: Vec<&str> = categories.into_iter().filter(|cat| {
            reg.iter().any(|e| e.category == *cat &&
                (query_lower.is_empty() || effectcraft_engine::effects::name_matches(e, &query_lower) ||
                 crate::i18n::effects::matches(e.id, e.name, &query_lower)))
        }).collect();
        visible.sort_by_key(|c| c.to_lowercase());
        let gap = 8.0;
        let col_w = ((rect.width() - 24.0 - gap) / 2.0).max(90.0);
        let row_h = 82.0;
        for (i, category) in visible.iter().enumerate() {
            let col = i % 2;
            let row = i / 2;
            let r = Rect::from_min_size(pos2(rect.min.x + 8.0 + col as f32 * (col_w + gap), y + row as f32 * (row_h + gap)), vec2(col_w, row_h));
            let count = reg.iter().filter(|e| e.category == *category).count();
            let label = format!("{}\n{} effects", crate::i18n::effects::category(category), count);
            let response = ui.put(r, egui::Button::new(label));
            if response.clicked() {
                ctx.data_mut(|d| d.insert_temp(category_id, (*category).to_string()));
            }
        }
        if visible.is_empty() {
            painter.text(pos2(rect.center().x, y + 28.0), Align2::CENTER_CENTER, tr("No matching effects"), Tokens::ui(12.0), t.text_faint);
        }
    }
}

'''
    if anchor not in source:
        raise SystemExit("AM native effect browser insertion point was not found.")
    source = source.replace(anchor, code + anchor, 1)
    source = source.replace(
        anchor,
        anchor + '\n    if app.ui.workspace == "AM 竖屏" {\n        show_am_native(app, ui, rect);\n        return;\n    }',
        1,
    )
    path.write_text(source, encoding="utf-8")


def patch_workspace_tabs(effectcraft: Path) -> None:
    """Put the two-mode layout chooser on its own editing-only toolbar row."""
    path = effectcraft / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1"
    if marker not in source:
        source = replace_once(
            source,
            "    let cy = rect.center().y;\n",
            "    let cy = rect.min.y + 20.0;\n",
            "keep the original tools in the first 40px toolbar row",
        )
        source = replace_once(
            source,
            "    right_side(app, ui, &p, rect, x, cy);\n",
            """    right_side(app, ui, &p, rect, x, cy);
    // EFFECTCRAFT_NOVA_LAYOUT_MENU_V2
    // EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1
    // The layout selector owns a separate row; it never shares hit targets with tool buttons.
    if !app.ui.start_screen {
        let layout_row = Rect::from_min_max(
            pos2(rect.min.x, rect.min.y + 40.0),
            rect.max,
        );
        layout_switch_row(app, ui, &p, layout_row);
    }
""",
            "editing-only reserved layout-switch row",
        )
        source = replace_once(
            source,
            """    let rx = workspace_menu(app, ui, p, rx, cy);
    workspace_tabs(app, ui, p, rx, left, cy);""",
            """    // Existing workspace tabs remain available; the Ae/AM mode switch is on row two.
    workspace_tabs(app, ui, p, rx, left, cy);""",
            "keep legacy workspace tabs separate from the new layout chooser",
        )
        anchor = "/// The Discord pill and the GitHub and website buttons, right to left from rx; returns the new rx."
        code = r'''
// Show the active Ae/AM mode in a dedicated row below the original tool controls.
fn workspace_label(workspace: &str) -> &'static str {
    if workspace == "AM 竖屏" { "AM 竖屏布局" } else { "Ae 原布局" }
}

fn layout_switch_row(app: &mut EffectcraftApp, ui: &mut egui::Ui, p: &egui::Painter, rect: Rect) {
    let t = app.tokens;
    let cy = rect.center().y;
    p.line_segment(
        [rect.left_top(), rect.right_top()],
        Stroke::new(1.0, t.separator),
    );
    p.text(
        pos2(rect.min.x + 12.0, cy),
        Align2::LEFT_CENTER,
        "编辑布局",
        Tokens::ui(11.0),
        t.text_dim,
    );

    let layout_label = format!("{} ▾", workspace_label(&app.ui.workspace));
    let label_galley = p.layout_no_wrap(layout_label, Tokens::ui(12.0), t.text_dim);
    let menu_width = (label_galley.size().x + 24.0).clamp(104.0, 148.0);
    let more = Rect::from_min_max(
        pos2(rect.max.x - menu_width - 10.0, cy - 11.0),
        pos2(rect.max.x - 10.0, cy + 11.0),
    );
    let mresp = ui.interact(more, egui::Id::new("ae-layout-switch"), Sense::click());
    p.rect_filled(more, 5.0, if mresp.hovered() { t.hover } else { t.panel_bg });
    p.galley_with_override_text_color(
        pos2(
            more.center().x - label_galley.size().x / 2.0,
            cy - label_galley.size().y / 2.0,
        ),
        label_galley,
        if mresp.hovered() { t.text } else { t.text_dim },
    );
    app.auto.add("header.layoutSwitch", more, "Switch between Ae and AM layouts");

    let current = app.ui.workspace.clone();
    crate::widgets::context_menu(&mresp, |ui| ws_menu(app, ui, &current));
    let popup_id = egui::Id::new("ae-layout-switch-popup");
    if mresp.clicked() {
        widgets::open_popup(ui, popup_id);
    }
    let names = ["Ae 原布局".to_string(), "AM 竖屏布局".to_string()];
    let selected = if app.ui.workspace == "AM 竖屏" { 1 } else { 0 };
    if let Some(index) = widgets::popup_menu(
        ui,
        popup_id,
        more.left_bottom() - vec2(140.0, 0.0),
        &names,
        Some(selected),
    ) {
        app.set_workspace(if index == 1 { "AM 竖屏" } else { "Default" });
    }
}

'''
        if anchor not in source:
            raise SystemExit("Could not find the header insertion point for the reserved layout row.")
        source = source.replace(anchor, code + anchor, 1)
        path.write_text(source, encoding="utf-8")

    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit("The dedicated editing-only Ae/AM layout row was not installed.")

    frame = effectcraft / "crates/ui-egui/src/app/frame.rs"
    frame_source = frame.read_text(encoding="utf-8")
    frame_marker = "EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1"
    if frame_marker not in frame_source:
        frame_source = replace_once(
            frame_source,
            "        let header_h = 40.0;\n",
            "        let header_h = if self.ui.start_screen { 40.0 } else { 64.0 }; // EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1\n",
            "reserve 24px for the separate editor-only layout row",
        )
        frame.write_text(frame_source, encoding="utf-8")
    if frame_marker not in frame.read_text(encoding="utf-8"):
        raise SystemExit("The editor header did not reserve space for the layout-switch row.")
    print("Added a separate Ae/AM layout row below the editor tools; Home remains unchanged.")

def patch_workspace_selection(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/app/window.rs"
    source = path.read_text(encoding="utf-8")
    marker = f'        self.ui.workspace = name.to_string();\n'
    call = f'''        let previous_workspace = self.ui.workspace.clone();
        // Only animate transitions to or from the AM editing workspace.
        self.workspace_transition = if previous_workspace != name
            && (previous_workspace == "{WORKSPACE}" || name == "{WORKSPACE}") {{
            Some((self.now, if name == "{WORKSPACE}" {{ 1.0 }} else {{ -1.0 }}))
        }} else {{
            None
        }};
        self.ui.workspace = name.to_string();
        // EFFECTCRAFT_ANDROID_AM_PORTRAIT_WORKSPACE_V1
        crate::android_layout::set_workspace_portrait(name == "{WORKSPACE}");
'''
    source = replace_once(source, marker, call, "workspace orientation and animated transition update")
    path.write_text(source, encoding="utf-8")


def patch_workspace_morph_transition(effectcraft: Path) -> None:
    """Keep the native workspace switch; tint the live panel/control edges blue during it."""
    lib = effectcraft / "crates/ui-egui/src/lib.rs"
    source = lib.read_text(encoding="utf-8")
    field_anchor = "pub struct EffectcraftApp {\n    pub session: Session,\n"
    field_patch = "pub struct EffectcraftApp {\n    pub(crate) workspace_transition: Option<(f64, f32)>,\n    pub session: Session,\n"
    if "workspace_transition: Option<(f64, f32)>" not in source:
        source = replace_once(source, field_anchor, field_patch, "AM workspace color-transition state field")
        lib.write_text(source, encoding="utf-8")

    app = effectcraft / "crates/ui-egui/src/app.rs"
    source = app.read_text(encoding="utf-8")
    app_anchor = "        EffectcraftApp {\n            session,\n"
    app_patch = "        EffectcraftApp {\n            workspace_transition: None,\n            session,\n"
    if "workspace_transition: None" not in source:
        source = replace_once(source, app_anchor, app_patch, "AM workspace color-transition state initialization")
        app.write_text(source, encoding="utf-8")

    frame = effectcraft / "crates/ui-egui/src/app/frame.rs"
    source = frame.read_text(encoding="utf-8")
    # The dock switches to the selected layout normally. No added slide, scale, detached
    # animation layer, or replacement transition is applied to the editor page.
    draw_marker = "EFFECTCRAFT_AM_WORKSPACE_MORPH_TRANSITION_V1"
    if draw_marker in source:
        begin = source.index("        // " + draw_marker)
        end = source.index("        #[cfg(not(target_arch = \"wasm32\"))]\n        prefs_live::dropped_files", begin)
        source = source[:begin] + "        self.dock_area(ui, body);\n" + source[end:]
    else:
        if "        self.dock_area(ui, body);\n" not in source:
            raise SystemExit("Original dock render call for AM workspace was not found.")

    end_anchor = "        self.draw_toast(ui, full, lift);\n"
    edge_patch = r'''        self.draw_toast(ui, full, lift);
        // EFFECTCRAFT_AM_NOVA_LAYOUT_TRACE_V2
        // Preserve the native dock reflow. Trace the real panel and control borders in
        // sequence, as Nova's "building layout" transition does; do not slide/scale pages.
        if let Some((started, _direction)) = self.workspace_transition {
            let progress = (((self.now - started).max(0.0) as f32) / 0.72).clamp(0.0, 1.0);
            if progress < 1.0 {
                let blue = egui::Color32::from_rgba_unmultiplied(42, 150, 255, 235);
                let painter = ui.painter();
                let mut rects: Vec<egui::Rect> = self.dock_rects.iter().map(|(_, rect)| *rect).collect();
                for element in &self.auto.elements {
                    let [x, y, w, h] = element.rect;
                    let rect = egui::Rect::from_min_size(egui::pos2(x, y), egui::vec2(w, h));
                    if rect.intersects(full) && w > 8.0 && h > 8.0 {
                        rects.push(rect);
                    }
                }
                let count = rects.len().max(1);
                for (index, rect) in rects.iter().enumerate() {
                    if !rect.intersects(full) {
                        continue;
                    }
                    // Stagger each real panel slightly so the layout appears to assemble.
                    let local = (progress * 1.28 - index as f32 / count as f32 * 0.28).clamp(0.0, 1.0);
                    let mut remaining = (rect.width() * 2.0 + rect.height() * 2.0) * local;
                    let edges = [
                        (rect.left_top(), rect.right_top()),
                        (rect.right_top(), rect.right_bottom()),
                        (rect.right_bottom(), rect.left_bottom()),
                        (rect.left_bottom(), rect.left_top()),
                    ];
                    for (from, to) in edges {
                        let length = (to - from).length();
                        if remaining <= 0.0 || length <= 0.0 {
                            break;
                        }
                        let fraction = (remaining / length).clamp(0.0, 1.0);
                        painter.line_segment(
                            [from, from + (to - from) * fraction],
                            egui::Stroke::new(1.8, blue),
                        );
                        remaining -= length;
                    }
                }
                painter.text(
                    full.center_top() + egui::vec2(0.0, 18.0),
                    egui::Align2::CENTER_CENTER,
                    "正在切换布局…",
                    egui::FontId::proportional(12.0),
                    blue,
                );
                ctx.request_repaint_after(std::time::Duration::from_millis(16));
            } else {
                self.workspace_transition = None;
            }
        }
'''
    if "EFFECTCRAFT_AM_BLUE_WORKSPACE_SWITCH_EDGES_V1" not in source:
        source = replace_once(source, end_anchor, edge_patch, "blue edges during native AM workspace switch")
    frame.write_text(source, encoding="utf-8")


def patch_startup_restore(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/app.rs"
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "        EffectcraftApp {\n",
        "        let app = EffectcraftApp {\n",
        "workspace restore startup binding",
    )
    tail = '''        }
        .with_ui_commands()
    }

    /// Offer the frontend's commands'''
    replacement = f'''        }};
        let app = app.with_ui_commands();
        // Apply the orientation of the persisted workspace before the first editor frame.
        crate::android_layout::set_workspace_portrait(app.ui.workspace == "{WORKSPACE}");
        app
    }}

    /// Offer the frontend's commands'''
    source = replace_once(source, tail, replacement, "restored workspace orientation")
    path.write_text(source, encoding="utf-8")


def patch_android_layout_module(effectcraft: Path) -> None:
    ui = effectcraft / "crates/ui-egui/src"
    lib = ui / "lib.rs"
    source = lib.read_text(encoding="utf-8")
    if "pub mod android_layout;" not in source:
        source = replace_once(
            source,
            "pub mod audio;\n",
            "pub mod audio;\npub mod android_layout;\n",
            "Android layout module declaration",
        )
    lib.write_text(source, encoding="utf-8")
    module = ui / "android_layout.rs"
    if module.exists() and module.read_text(encoding="utf-8") != RUST_MODULE:
        raise SystemExit(f"Unexpected existing Android layout bridge: {module}")
    module.write_text(RUST_MODULE, encoding="utf-8")

    cargo = ui.parent / "Cargo.toml"
    manifest = cargo.read_text(encoding="utf-8")
    target = '[target.\'cfg(not(target_arch = "wasm32"))\'.dependencies]\n'
    if 'jni = "0.22"' not in manifest:
        manifest = replace_once(manifest, target, target + 'jni = "0.22"\n', "Android JNI dependency")
        cargo.write_text(manifest, encoding="utf-8")
    if 'jni = "0.22"' not in cargo.read_text(encoding="utf-8"):
        raise SystemExit("Android orientation bridge requires the existing JNI 0.22 dependency.")


def patch_activity(builder: Path) -> None:
    path = builder / "templates/android/SafActivity.java"
    source = path.read_text(encoding="utf-8")
    if JAVA_MARKER not in source:
        imports = "".join(item + "\n" for item in JAVA_IMPORTS if item not in source)
        if imports:
            source = replace_once(
                source,
                "import android.content.pm.PackageManager;\n",
                "import android.content.pm.PackageManager;\n" + imports,
                "AM orientation and signer Java imports",
            )
        class_anchor = "public final class __CLASS__ extends NativeActivity {\n"
        source = replace_once(
            source,
            class_anchor,
            class_anchor + JAVA_BRIDGE + "\n",
            "AM orientation and signer Java bridge",
        )
        create_anchor = '''    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
'''
        create_patch = '''    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        workspaceOrientationActivity = this;
        if (!verifyReleaseSigningCertificate()) {
            Toast.makeText(this,
                "Ae 安装包签名验证失败，可能已被篡改或重新打包，请重新获取官方安装包。",
                Toast.LENGTH_LONG).show();
            finish();
            android.os.Process.killProcess(android.os.Process.myPid());
            return;
        }
'''
        source = replace_once(source, create_anchor, create_patch, "Android startup signer verification")
        destroy_anchor = "    protected void onDestroy() {\n"
        destroy_patch = '''    protected void onDestroy() {
        if (workspaceOrientationActivity == this) workspaceOrientationActivity = null;
'''
        source = replace_once(source, destroy_anchor, destroy_patch, "Android orientation Activity cleanup")
    path.write_text(source, encoding="utf-8")
    if JAVA_MARKER not in source or SIGNER_PLACEHOLDER not in source:
        raise SystemExit("Android portrait/signer Activity bridge was not fully installed.")


def verify_import_export_unchanged(effectcraft: Path) -> None:
    # This patch must not take ownership of any file-open, share, serialization, or export route.
    router = (effectcraft / "crates/ui-egui/src/menus.rs").read_text(encoding="utf-8")
    frontend = (effectcraft / "crates/ui-egui/src/menus/frontend.rs").read_text(encoding="utf-8")
    required = (
        '"zip" | "rar"',
        '"file.extractProjectArchive"',
        'return import_incoming_project(app, &inner);',
    )
    if any(token not in router for token in required):
        raise SystemExit("AM layout patch detected a missing original ZIP/RAR automatic-import route.")
    for token in (
        '"file.importAepDesktop"',
        '"file.importAepMobilePackage"',
        '"file.importAlightMotionProject"',
        '"file.importNodeVideoProject"',
        '"file.importCapCutProject"',
        '"file.importEffectCraftMobile"',
    ):
        if token not in frontend and token not in router:
            raise SystemExit(f"AM layout patch detected a missing existing importer: {token}")
    header = (effectcraft / "crates/ui-egui/src/header.rs").read_text(encoding="utf-8")
    if "export_progress_dialog(app, ui);" not in header:
        raise SystemExit("AM layout patch detected a missing original export UI.")
    if "EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1" not in header:
        raise SystemExit("The dedicated Ae/AM layout selector row is missing.")
    if "if !app.ui.start_screen" not in header:
        raise SystemExit("The layout selector must remain hidden on the Home screen.")
    frame = (effectcraft / "crates/ui-egui/src/app/frame.rs").read_text(encoding="utf-8")
    if "let header_h = if self.ui.start_screen { 40.0 } else { 64.0 };" not in frame:
        raise SystemExit("The editor header did not reserve a separate row for the layout selector.")
    print("Verified AM layout leaves the existing import router/export UI intact and reserves a non-overlapping editing-only selector row.")


def main() -> None:
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to checked-out source trees.")
    patch_dock(effectcraft)
    patch_touch_trim_handles(effectcraft)
    patch_am_native_effect_browser(effectcraft)
    patch_workspace_selection(effectcraft)
    patch_workspace_morph_transition(effectcraft)
    patch_workspace_tabs(effectcraft)
    patch_startup_restore(effectcraft)
    patch_android_layout_module(effectcraft)
    patch_activity(builder)
    verify_import_export_unchanged(effectcraft)
    print("Added the AM portrait workspace; the selected workspace is restored from workspaces.json on relaunch.")
    print("AM uses the original Effects & Presets and Effect Controls panels, preserving all loaded EffectCraft effects.")
    print("Project import/share/export routes and project formats were not changed.")
    print("Added release-certificate pin verification and sensor/AM portrait switching for Android.")
    

if __name__ == "__main__":
    main()
