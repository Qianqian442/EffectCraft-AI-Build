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
            log::warn!("Could not apply EffectCraft workspace orientation: {{error}}");
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
    let search_rect = Rect::from_min_size(rect.min + vec2(10.0, 8.0), vec2((rect.width() - 20.0).max(80.0), 30.0));
    let mut query = app.ui.effects_search.clone();
    let search_hint = tr("Search effects");
    let search = widgets::search_field(ui, search_rect, &mut query, search_hint, &t);
    a11y::text_input(&search, search_hint, &query);
    app.ui.effects_search = query.clone();
    let query_lower = query.trim().to_lowercase();
    let category_id = egui::Id::new("am-native-effect-browser-category");
    let selected_category: Option<String> = ctx.data(|d| d.get_temp(category_id));
    // EFFECTCRAFT_AM_IMPORTED_PLUGIN_EFFECTS_V1
    // effects::all() includes both built-in Ae effects and all successfully registered
    // API-v1 plug-ins. Keep a dedicated shortcut for imported runnable plug-ins as well.
    const IMPORTED_PLUGINS_CATEGORY: &str = "__EFFECTCRAFT_IMPORTED_PLUGINS__";
    let registry = effectcraft_engine::effects::all();
    let plugin_effects = effectcraft_engine::effects::plugin::plugins();
    let categories = effectcraft_engine::effects::categories();
    let list_rect = Rect::from_min_max(
        pos2(rect.min.x + 6.0, search_rect.max.y + 6.0),
        pos2(rect.max.x - 6.0, rect.max.y - 6.0),
    );
    let mut apply_id: Option<String> = None;

    // The search box stays fixed while the category/effect list scrolls vertically.
    // drag_to_scroll makes a finger swipe work on Android as well as a mouse wheel.
    ui.allocate_ui_at_rect(list_rect, |list_host| {
        egui::ScrollArea::vertical()
            .id_salt("am-native-effect-browser-scroll")
            .auto_shrink([false, false])
            .drag_to_scroll(true)
            .show(list_host, |list_ui| {
                list_ui.set_width(list_rect.width());
                if selected_category.is_none() && !plugin_effects.is_empty() {
                    let label = format!("已导入插件效果\\n{} 个可用效果", plugin_effects.len());
                    if list_ui.add_sized(
                        vec2(list_rect.width(), 44.0),
                        egui::Button::new(label),
                    ).clicked() {
                        ctx.data_mut(|d| d.insert_temp(category_id, IMPORTED_PLUGINS_CATEGORY.to_string()));
                    }
                    list_ui.add_space(8.0);
                }
                if let Some(category) = selected_category.as_deref() {
                    list_ui.horizontal(|row| {
                        if row.add_sized(vec2(44.0, 34.0), egui::Button::new("‹")).clicked() {
                            ctx.data_mut(|d| d.remove::<String>(category_id));
                        }
                        if category == IMPORTED_PLUGINS_CATEGORY {
                            row.label("已导入插件效果");
                        } else {
                            row.label(crate::i18n::effects::category(category));
                        }
                    });
                    list_ui.add_space(8.0);
                    let matching: Vec<_> = if category == IMPORTED_PLUGINS_CATEGORY {
                        plugin_effects.iter().copied()
                            .filter(|effect| {
                                query_lower.is_empty()
                                    || effectcraft_engine::effects::name_matches(effect, &query_lower)
                                    || crate::i18n::effects::matches(effect.id, effect.name, &query_lower)
                            })
                            .collect()
                    } else {
                        registry.iter()
                            .filter(|effect| effect.category == category)
                            .filter(|effect| {
                                query_lower.is_empty()
                                    || effectcraft_engine::effects::name_matches(effect, &query_lower)
                                    || crate::i18n::effects::matches(effect.id, effect.name, &query_lower)
                            })
                            .collect()
                    };
                    let gap = 8.0;
                    let col_w = ((list_ui.available_width() - gap) / 2.0).max(90.0);
                    list_ui.columns(2, |columns| {
                        for (index, effect) in matching.iter().enumerate() {
                            let column = index % 2;
                            let response = columns[column].add_sized(
                                vec2(col_w, 66.0),
                                egui::Button::new(crate::i18n::effects::name(effect.id, effect.name)),
                            );
                            if response.clicked() {
                                apply_id = Some(effect.id.to_string());
                            }
                            columns[column].add_space(gap);
                        }
                    });
                    if matching.is_empty() {
                        list_ui.label(tr("No matching effects"));
                    }
                } else {
                    let mut visible: Vec<&str> = categories.into_iter().filter(|category| {
                        registry.iter().any(|effect| effect.category == *category
                            && (query_lower.is_empty()
                                || effectcraft_engine::effects::name_matches(effect, &query_lower)
                                || crate::i18n::effects::matches(effect.id, effect.name, &query_lower)))
                    }).collect();
                    visible.sort_by_key(|category| category.to_lowercase());
                    let gap = 8.0;
                    let col_w = ((list_ui.available_width() - gap) / 2.0).max(90.0);
                    list_ui.columns(2, |columns| {
                        for (index, category) in visible.iter().enumerate() {
                            let column = index % 2;
                            let count = registry.iter().filter(|effect| effect.category == *category).count();
                            let label = format!("{}\n{} effects", crate::i18n::effects::category(category), count);
                            if columns[column].add_sized(vec2(col_w, 82.0), egui::Button::new(label)).clicked() {
                                ctx.data_mut(|d| d.insert_temp(category_id, (*category).to_string()));
                            }
                            columns[column].add_space(gap);
                        }
                    });
                    if visible.is_empty() {
                        list_ui.label(tr("No matching effects"));
                    }
                }
            });
    });

    if let Some(id) = apply_id {
        if app.session.state.selected_layers.is_empty() {
            app.ui.status = "Select a layer to apply to".into();
        } else {
            match app.session.execute("effect.apply", serde_json::json!({"effect": id})) {
                Err(error) => app.ui.status = error.to_string(),
                Ok(applied) => {
                    push_recent(&mut app.ui.effects_recent, &id);
                    // Switch to the parameter panel after the effect has really been added.
                    // Do not reset focus back to the browser in the same frame.
                    app.show_panel(crate::dock::PanelKind::EffectControls);
                    crate::panels::effect_controls::choose_files_after_apply(app, &applied);
                }
            }
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
    """Use the original workspace menu; do not add a second toolbar row."""
    header = (effectcraft / "crates/ui-egui/src/header.rs").read_text(encoding="utf-8")
    frame = (effectcraft / "crates/ui-egui/src/app/frame.rs").read_text(encoding="utf-8")
    dock = (effectcraft / "crates/ui-egui/src/dock.rs").read_text(encoding="utf-8")

    # The existing » workspace menu already enumerates dock::WORKSPACES.
    # patch_dock adds AM 竖屏 there, so no extra toolbar control is needed.
    if "let rx = workspace_menu(app, ui, p, rx, cy);" not in header:
        raise SystemExit("The original workspace menu is missing from the Ae toolbar.")
    if "workspace_tabs(app, ui, p, rx, left, cy);" not in header:
        raise SystemExit("The original workspace tabs are missing from the Ae toolbar.")
    if '"AM 竖屏"' not in dock:
        raise SystemExit("AM 竖屏 is not registered in the original workspace menu.")
    if "EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1" in header or "layout_switch_row(" in header:
        raise SystemExit("The extra Ae/AM toolbar row must not be present.")
    if "let header_h = 40.0;" not in frame or "let header_h = 64.0;" in frame:
        raise SystemExit("The original 40px single-row editor toolbar was not restored.")
    print("Restored the original single-row Ae toolbar; Ae/AM switching uses the existing workspace menu.")


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
        let mut app = app.with_ui_commands();

        // One-time layout migration: discard stale built-in Ae/AM layout overrides and
        // retain renamed copies so users can still inspect their former custom arrangements.
        const AE_LAYOUT_MIGRATION_KEY: &str = "ae_workspace_layout_restore_v1";
        let already_migrated = app.session.config.as_deref()
            .and_then(|config| config.read(AE_LAYOUT_MIGRATION_KEY))
            .as_deref() == Some("done");
        if !already_migrated {{
            if let Some(old_default) = app.ui.saved_workspaces.remove("Default") {{
                let archive = "Default (before Ae layout restore)";
                if !app.ui.saved_workspaces.contains_key(archive) {{
                    app.ui.saved_workspaces.insert(archive.to_string(), old_default);
                }}
            }}
            if app.ui.workspace == "Default" {{
                app.ui.dock = crate::dock::Workspace::new(crate::dock::workspace("Default"));
            }}
        // The AM portrait workspace is intentionally left untouched: preserve its saved layout.
            if let Some(config) = app.session.config.as_deref() {{
                match app.workspace_store.save(Some(config), &app.ui) {{
                    Ok(_) => {{
                        if let Err(error) = config.write(AE_LAYOUT_MIGRATION_KEY, "done") {{
                            log::warn!("Could not save Ae layout migration marker: {{error}}");
                        }}
                    }}
                    Err(error) => log::warn!("Could not persist restored Ae/AM workspaces: {{error}}"),
                }}
            }}
        }}

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


def patch_native_effect_touch_behavior(effectcraft: Path) -> None:
    """Make the original Effects & Presets panel usable with phone touch gestures."""
    panel = effectcraft / "crates/ui-egui/src/panels/effects_presets.rs"
    source = panel.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_TAP_TO_APPLY_EFFECT_V1"
    if marker not in source:
        begin = source.find("fn effect_row(")
        end = source.find("fn preset_row(", begin)
        if begin < 0 or end < 0:
            raise SystemExit("Could not locate the native Effects & Presets effect-row handler.")
        section = source[begin:end]
        old_sense = "    let resp = ui.interact(r.intersect(list), id, if tab { Sense::click_and_drag() } else { Sense::CLICK | Sense::DRAG });"
        new_sense = """    // EFFECTCRAFT_ANDROID_TAP_TO_APPLY_EFFECT_V1
    // Android effect rows are click-only so vertical gestures belong to the panel scroller.
    // Use the Android target instead of has_touch_screen(): some Android input backends
    // expose touch as a primary pointer and report has_touch_screen() == false.
    let row_sense = if cfg!(target_os = "android") {
        Sense::click()
    } else if tab {
        Sense::click_and_drag()
    } else {
        Sense::CLICK | Sense::DRAG
    };
    let resp = ui.interact(r.intersect(list), id, row_sense);"""
        if old_sense not in section:
            raise SystemExit("Native effect rows changed; refusing to patch the wrong gesture handler.")
        section = section.replace(old_sense, new_sense, 1)
        old_click = """    if resp.clicked() {
        nav_click(&ctx, app, id);
    }
    if resp.double_clicked() {
        *apply = Some(Apply::Effect(e.id.to_string()));
    }"""
        new_click = """    if resp.clicked() {
        if cfg!(target_os = "android") {
            *apply = Some(Apply::Effect(e.id.to_string()));
        } else {
            nav_click(&ctx, app, id);
        }
    }
    if resp.double_clicked() {
        *apply = Some(Apply::Effect(e.id.to_string()));
    }"""
        if old_click not in section:
            raise SystemExit("Native effect-row tap handler changed; refusing an unsafe partial patch.")
        section = section.replace(old_click, new_click, 1)
        source = source[:begin] + section + source[end:]
        panel.write_text(source, encoding="utf-8")

    widgets_path = effectcraft / "crates/ui-egui/src/widgets.rs"
    widgets = widgets_path.read_text(encoding="utf-8")
    scroll_marker = "EFFECTCRAFT_ANDROID_TOUCH_SCROLL_PANEL_V2"
    if scroll_marker not in widgets:
        old_scroll = """        if ui.rect_contains_pointer(area) {
            offset -= ui.input(|i| i.smooth_scroll_delta.y);
        }
        let gutter: Gutter = ui.data(|d| d.get_temp(id.with("gutter"))).unwrap_or_default();"""
        new_scroll = """        if ui.rect_contains_pointer(area) {
            offset -= ui.input(|i| i.smooth_scroll_delta.y);
        }
        // EFFECTCRAFT_ANDROID_TOUCH_SCROLL_PANEL_V1
        // EFFECTCRAFT_ANDROID_TOUCH_SCROLL_PANEL_V2
        // Android touch is delivered as a primary pointer on some backends. Do not gate
        // this on has_touch_screen(), or a real finger swipe can be mistaken for a row drag.
        // Click-only Android effect rows leave vertical movement to this panel scroller.
        // Active sliders/curve handles still own gestures through dragged_id().
        let touch_pan = ui.input(|i| {
            i.pointer.primary_down()
                && i.pointer.press_origin().is_some_and(|origin| area.contains(origin))
        });
        if touch_pan && ui.ctx().dragged_id().is_none() {
            let delta = ui.input(|i| i.pointer.delta());
            if delta.y.abs() >= delta.x.abs() && delta.y.abs() > 0.1 {
                offset = (offset - delta.y).clamp(0.0, max.max(0.0));
                ui.ctx().request_repaint();
            }
        }
        let gutter: Gutter = ui.data(|d| d.get_temp(id.with("gutter"))).unwrap_or_default();"""
        widgets = replace_once(widgets, old_scroll, new_scroll, "native PanelScroll finger gesture")
        widgets_path.write_text(widgets, encoding="utf-8")


def patch_project_import_shortcut(effectcraft: Path) -> None:
    """Expose the unified project importer beside the existing plug-in import entry."""
    path = effectcraft / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1"
    if marker in source:
        return
    # The plug-in shortcut may be injected by a different validation/build path.
    # Reuse the UI variable of the exact toolbar row: scroll_ui in the mobile scroller,
    # ui in the desktop/validation header before the responsive wrapper is installed.
    lines = source.splitlines(keepends=True)
    insert_at = None
    ui_var = "ui"
    indent = "    "
    anchors = (
        ("let x = plugin_import_button(app, scroll_ui,", "scroll_ui", "            "),
        ("let x = brand_and_home(app, scroll_ui,", "scroll_ui", "            "),
        ("let x = plugin_import_button(app, ui,", "ui", "    "),
        ("let x = brand_and_home(app, ui,", "ui", "    "),
    )
    for wanted, selected_ui, selected_indent in anchors:
        offset = 0
        for line in lines:
            if wanted in line:
                insert_at = offset + len(line)
                ui_var = selected_ui
                indent = selected_indent
                break
            offset += len(line)
        if insert_at is not None:
            break
    if insert_at is None:
        raise SystemExit("Could not locate a toolbar anchor for the unified project-import shortcut.")
    source = source[:insert_at] + indent + f"let x = project_import_button(app, {ui_var}, x, cy);\n" + source[insert_at:]
    helper_anchor = "/// The tool slots (with group separators after camera tools and pan-behind); returns the x after them.\n"
    button = r'''
// EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1
/// A single-tap shortcut to the original unified project importer.
fn project_import_button(app: &mut EffectcraftApp, ui: &mut egui::Ui, x: f32, cy: f32) -> f32 {
    let rect = Rect::from_min_size(pos2(x, cy - 13.0), vec2(76.0, 26.0));
    let response = ui
        .put(rect, egui::Button::new("导入工程"))
        .on_hover_text("导入 Ae、AM、NV、CapCut 或 Ae 自有工程");
    app.auto.add_response("header.importProject", &response, "导入工程");
    widgets::focus_outline(ui, &response, &app.tokens);
    if response.clicked()
        && let Err(error) = crate::menus::invoke(app, ui.ctx(), "file.importProject", json!({}))
    {
        app.ui.status = error;
    }
    x + 82.0
}

'''
    if helper_anchor not in source:
        raise SystemExit("Could not locate the toolbar helper insertion point for the project-import shortcut.")
    source = source.replace(helper_anchor, button + helper_anchor, 1)
    path.write_text(source, encoding="utf-8")


def patch_home_surface(effectcraft: Path) -> None:
    """Give AM mode a portrait Home while keeping the same native Ae project actions."""
    path = effectcraft / "crates/ui-egui/src/panels/home.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_PORTRAIT_HOME_V1"
    if marker in source:
        return
    show_anchor = "pub fn show(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {"
    helper_code = r'''
// EFFECTCRAFT_AM_PORTRAIT_HOME_V1
/// Compact portrait Home for Ae×am. It uses the same native project commands and
/// recent-project records as Ae; only the Home presentation changes.
fn show_am_portrait_home(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let t = app.tokens;
    let ctx = ui.ctx().clone();
    let painter = ui.painter().with_clip_rect(rect);
    painter.rect_filled(rect, 0.0, t.app_bg);

    painter.text(
        pos2(rect.min.x + 18.0, rect.min.y + 26.0),
        Align2::LEFT_CENTER,
        "Ae×am",
        Tokens::semibold(25.0),
        t.tab_text_active,
    );
    painter.text(
        pos2(rect.min.x + 18.0, rect.min.y + 54.0),
        Align2::LEFT_CENTER,
        "移动创作工作区",
        Tokens::ui(12.0),
        t.text_dim,
    );

    let pad = 14.0;
    let gap = 9.0;
    let card_top = rect.min.y + 78.0;
    let card_w = ((rect.width() - pad * 2.0 - gap) / 2.0).max(76.0);
    let card_h = 46.0;
    let actions: [(&str, &str); 6] = [
        ("新建合成", "app.newComp"),
        ("打开工程", "file.open"),
        ("导入工程", "file.importProject"),
        ("导入素材", "file.import"),
        ("模板", "am.home.templates"),
        ("教程", "am.home.learn"),
    ];
    let mut commands: Vec<(&'static str, serde_json::Value)> = Vec::new();
    for (index, (label, command)) in actions.iter().enumerate() {
        let row = index / 2;
        let col = index % 2;
        let r = Rect::from_min_size(
            pos2(rect.min.x + pad + col as f32 * (card_w + gap), card_top + row as f32 * (card_h + gap)),
            vec2(card_w, card_h),
        );
        let response = ui.put(
            r,
            egui::Button::new(*label)
                .fill(t.panel_bg)
                .stroke(egui::Stroke::new(1.0, t.separator))
                .min_size(r.size()),
        );
        app.auto.add_response(&format!("am.home.{}", command), &response, label);
        if response.clicked() {
            match *command {
                "am.home.templates" => {
                    app.ui.home_templates = true;
                    app.ui.home_learn = false;
                }
                "am.home.learn" => {
                    app.ui.home_learn = true;
                    app.ui.home_templates = false;
                }
                "file.import" => commands.push(("file.import", json!({"picturesAndVideos": true}))),
                "app.newComp" | "file.open" | "file.importProject" => {
                    commands.push((*command, json!({})));
                }
                _ => {}
            }
        }
    }

    let edit_rect = Rect::from_min_size(
        pos2(rect.min.x + pad, card_top + 3.0 * (card_h + gap) + 2.0),
        vec2((rect.width() - pad * 2.0).max(60.0), 38.0),
    );
    let edit = ui.put(
        edit_rect,
        egui::Button::new("进入编辑")
            .fill(t.accent.gamma_multiply(0.20))
            .stroke(egui::Stroke::new(1.0, t.accent))
            .min_size(edit_rect.size()),
    );
    app.auto.add_response("am.home.enterEditor", &edit, "进入编辑");
    if edit.clicked() {
        app.ui.start_screen = false;
        app.ui.home_learn = false;
        app.ui.home_templates = false;
    }

    let recent_top = edit_rect.max.y + 14.0;
    painter.text(
        pos2(rect.min.x + pad, recent_top + 9.0),
        Align2::LEFT_CENTER,
        "最近工程",
        Tokens::semibold(15.0),
        t.tab_text_active,
    );
    let recent_rect = Rect::from_min_max(
        pos2(rect.min.x + pad, recent_top + 24.0),
        pos2(rect.max.x - pad, rect.max.y - 8.0),
    );
    let entries = recent_entries(&app.session.prefs);
    let mut recent_ui = ui.new_child(egui::UiBuilder::new().max_rect(recent_rect));
    egui::ScrollArea::vertical()
        .id_salt("effectcraft-am-home-recent")
        .auto_shrink([false, false])
        .show(&mut recent_ui, |scroll_ui| {
            for entry in entries {
                let title = if entry.exists { entry.name.clone() } else { format!("{}（文件不存在）", entry.name) };
                let response = scroll_ui.add_sized(
                    [scroll_ui.available_width(), 42.0],
                    egui::Button::new(title).fill(t.panel_bg),
                );
                app.auto.add_response(&format!("am.home.recent.{}", entry.index), &response, &entry.path);
                if response.clicked() {
                    commands.push(("file.openRecent", json!({"index": entry.index})));
                }
            }
            if app.session.prefs.recent_projects.is_empty() {
                scroll_ui.label("最近打开的工程会显示在这里");
            }
        });
    run_actions(app, &ctx, commands);
}

'''
    if show_anchor not in source:
        raise SystemExit("Could not locate the Home panel entry point for the Ae×am portrait Home.")
    source = source.replace(show_anchor, helper_code + show_anchor, 1)
    dispatch = show_anchor + '''
    if app.ui.workspace == "AM 竖屏" {
        show_am_portrait_home(app, ui, rect);
        return;
    }
'''
    if "show_am_portrait_home(app, ui, rect);" not in source:
        source = source.replace(show_anchor, dispatch, 1)
    path.write_text(source, encoding="utf-8")


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
    if "EFFECTCRAFT_LAYOUT_SWITCH_RESERVED_ROW_V1" in header or "layout_switch_row(" in header:
        raise SystemExit("The extra Ae/AM toolbar row must remain removed.")
    if "let rx = workspace_menu(app, ui, p, rx, cy);" not in header:
        raise SystemExit("The original workspace menu must remain available for Ae/AM switching.")
    if "workspace_tabs(app, ui, p, rx, left, cy);" not in header:
        raise SystemExit("The original workspace tabs must remain unchanged.")
    effects = (effectcraft / "crates/ui-egui/src/panels/effects_presets.rs").read_text(encoding="utf-8")
    widgets = (effectcraft / "crates/ui-egui/src/widgets.rs").read_text(encoding="utf-8")
    frame = (effectcraft / "crates/ui-egui/src/app/frame.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_TAP_TO_APPLY_EFFECT_V1" not in effects:
        raise SystemExit("AM portrait Effects & Presets must apply an effect on a single tap.")
    if "EFFECTCRAFT_ANDROID_TOUCH_SCROLL_PANEL_V1" not in widgets:
        raise SystemExit("AM portrait effect/parameter panels must support finger-drag vertical scrolling.")
    if "let header_h = 40.0;" not in frame or "let header_h = 64.0;" in frame:
        raise SystemExit("The editor must retain the original single-row 40px toolbar.")
    dock = (effectcraft / "crates/ui-egui/src/dock.rs").read_text(encoding="utf-8")
    if "FixedSecond(300.0)" not in dock or "FixedFirst(300.0)" not in dock:
        raise SystemExit("The original Ae fixed-width left/right panel arrangement was changed.")
    if '"AM 竖屏"' not in dock:
        raise SystemExit("AM 竖屏 must remain selectable in the original workspace menu.")
    if "EFFECTCRAFT_AM_PROJECT_IMPORT_SHORTCUT_V1" not in header or "file.importProject" not in header:
        raise SystemExit("The original toolbar must retain the unified project-import shortcut and plugin-import button.")
    print("Verified the original Ae toolbar and responsive three-column workspace are restored; AM remains in the workspace menu.")


def main() -> None:
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to checked-out source trees.")
    patch_dock(effectcraft)
    patch_touch_trim_handles(effectcraft)
    patch_workspace_selection(effectcraft)
    patch_workspace_morph_transition(effectcraft)
    patch_workspace_tabs(effectcraft)
    patch_native_effect_touch_behavior(effectcraft)
    patch_project_import_shortcut(effectcraft)
    patch_startup_restore(effectcraft)
    patch_home_surface(effectcraft)
    patch_android_layout_module(effectcraft)
    patch_activity(builder)
    verify_import_export_unchanged(effectcraft)
    print("Restored the original Ae toolbar and responsive three-column workspace.")
    print("AM remains a separate portrait workspace, selectable from the original workspace menu; stale built-in layouts are migrated once.")
    print("Project import/share/export routes and project formats were not changed.")
    print("Added release-certificate pin verification and sensor/AM portrait switching for Android.")
    

if __name__ == "__main__":
    main()
