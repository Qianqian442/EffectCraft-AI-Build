#!/usr/bin/env python3
"""Add a separate AM portrait workspace and orientation-only Android bridge.

This patch intentionally changes only workspace presentation and the Android Activity
host bridge. It does not edit project import routing, archive staging, project serializers,
render/export commands, or project file formats.
"""
from __future__ import annotations

import os
from pathlib import Path


WORKSPACE = "AM 竖屏"
MARKER = "EFFECTCRAFT_ANDROID_AM_PORTRAIT_WORKSPACE_V1"
JAVA_MARKER = "EFFECTCRAFT_ANDROID_AM_ORIENTATION_ONLY_V2"


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
)

JAVA_BRIDGE = r'''
    // EFFECTCRAFT_ANDROID_AM_ORIENTATION_ONLY_V2
    private static volatile __CLASS__ workspaceOrientationActivity;

    public static void setWorkspacePortrait(boolean portrait) {
        __CLASS__ activity = workspaceOrientationActivity;
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            try {
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
        // Portrait AM workspace: keep the preview in the upper 42% and give the
        // native Timeline the lower 58%, directly below the viewer/transport.
        "{WORKSPACE}" => vsplit(
            Ratio(0.42),
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
    """Do not patch the shared Ae timeline: AM owns its own clip-edge handles."""
    print("AM clip-edge handles are implemented in the independent AM editor; shared Ae Timeline is untouched.")

def patch_workspace_selection(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/app/window.rs"
    source = path.read_text(encoding="utf-8")
    marker = f'        self.ui.workspace = name.to_string();\n'
    call = f'''        self.ui.workspace = name.to_string();
        // EFFECTCRAFT_ANDROID_AM_PORTRAIT_WORKSPACE_V2
        crate::android_layout::set_workspace_portrait(name == "{WORKSPACE}");
'''
    source = replace_once(source, marker, call, "workspace orientation and animated transition update")
    path.write_text(source, encoding="utf-8")


def patch_workspace_morph_transition(effectcraft: Path) -> None:
    """Retired: AM must not paint transition overlays over the Ae workspace."""
    print("No workspace-wide transition overlay is installed; Ae rendering remains unchanged.")

def patch_startup_restore(effectcraft: Path) -> None:
    """Retired: AM setup must not migrate or rewrite the user's saved Ae workspace."""
    print("Saved Ae workspace state is not migrated or rewritten by the AM patch.")

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
    if "EFFECTCRAFT_ANDROID_AM_ORIENTATION_ONLY_V2" not in source:
        imports = "".join(item + "\n" for item in JAVA_IMPORTS if item not in source)
        if imports:
            source = replace_once(source, "import android.content.pm.PackageManager;\n",
                                  "import android.content.pm.PackageManager;\n" + imports,
                                  "AM orientation-only Java import")
        class_anchor = "public final class __CLASS__ extends NativeActivity {\n"
        source = replace_once(source, class_anchor, class_anchor + JAVA_BRIDGE + "\n",
                              "AM orientation-only Java bridge")
        create_anchor = '''    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
'''
        create_patch = '''    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        workspaceOrientationActivity = this;
'''
        source = replace_once(source, create_anchor, create_patch, "AM orientation Activity registration")
        destroy_anchor = "    protected void onDestroy() {\n"
        destroy_patch = '''    protected void onDestroy() {
        if (workspaceOrientationActivity == this) workspaceOrientationActivity = null;
'''
        source = replace_once(source, destroy_anchor, destroy_patch, "AM orientation Activity cleanup")
    path.write_text(source, encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_AM_ORIENTATION_ONLY_V2" not in source:
        raise SystemExit("AM orientation-only bridge was not installed.")
    if "verifyReleaseSigningCertificate" in source or "EXPECTED_SIGNING_CERT_SHA256" in source:
        raise SystemExit("The AM patch must not add an app-launch signing gate that changes Ae startup.")

def patch_native_effect_touch_behavior(effectcraft: Path) -> None:
    """Retired: the native Ae effect list and rows are not altered by AM layout."""
    print("AM uses its own effect browser; the native Ae Effects & Presets panel is untouched.")

def patch_am_scoped_panel_touch_scroll(effectcraft: Path) -> None:
    """Enable finger scrolling only while an AM-owned drawer is being rendered."""
    widgets_path = effectcraft / "crates/ui-egui/src/widgets.rs"
    source = widgets_path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"
    if marker not in source:
        old = """        if ui.rect_contains_pointer(area) {
            offset -= ui.input(|i| i.smooth_scroll_delta.y);
        }
        let gutter: Gutter = ui.data(|d| d.get_temp(id.with("gutter"))).unwrap_or_default();"""
        new = """        if ui.rect_contains_pointer(area) {
            offset -= ui.input(|i| i.smooth_scroll_delta.y);
        }
        // EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1
        let am_touch_draw_context = ui.ctx().data(|d| {
            d.get_temp::<bool>(egui::Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1")).unwrap_or(false)
        });
        let touch_pan = am_touch_draw_context && ui.input(|i| {
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
        source = replace_once(source, old, new, "AM-scoped PanelScroll finger gesture")
        widgets_path.write_text(source, encoding="utf-8")
    print("Installed touch scrolling scoped to the AM drawer context; Ae panels do not enable it.")

def patch_project_import_shortcut(effectcraft: Path) -> None:
    """Retired: project import is exposed on the AM Home, not injected into Ae's toolbar."""
    print("The AM patch does not add, resize, or rearrange any Ae toolbar button.")

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

    // A layout switch belongs to the AM Home itself; never reuse the Ae toolbar here.
    let layout_rect = Rect::from_min_size(pos2(rect.max.x - 104.0, rect.min.y + 10.0), vec2(90.0, 32.0));
    let layout = ui.put(layout_rect, egui::Button::new("切回 Ae 布局").min_size(layout_rect.size()));
    app.auto.add_response("am.home.layout", &layout, "切回 Ae 布局");
    if layout.clicked() {
        app.set_workspace("Default");
    }

    let pad = 14.0;
    let gap = 9.0;
    let card_top = rect.min.y + 78.0;
    let card_w = ((rect.width() - pad * 2.0 - gap) / 2.0).max(76.0);
    let card_h = 50.0;
    let actions: [(&str, &str); 4] = [
        ("新建合成", "app.newComp"),
        ("打开工程", "file.open"),
        ("导入工程", "file.importProject"),
        ("导入素材", "file.import"),
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
                "file.import" => commands.push(("file.import", json!({"picturesAndVideos": true}))),
                "app.newComp" | "file.open" | "file.importProject" => {
                    commands.push((*command, json!({})));
                }
                _ => {}
            }
        }
    }

    let edit_rect = Rect::from_min_size(
        pos2(rect.min.x + pad, card_top + 2.0 * (card_h + gap) + 2.0),
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
    widgets = (effectcraft / "crates/ui-egui/src/widgets.rs").read_text(encoding="utf-8")
    frame = (effectcraft / "crates/ui-egui/src/app/frame.rs").read_text(encoding="utf-8")
    home = (effectcraft / "crates/ui-egui/src/panels/home.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1" not in widgets:
        raise SystemExit("AM drawers must have AM-scoped finger scrolling.")
    native_effects = (effectcraft / "crates/ui-egui/src/panels/effects_presets.rs").read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_TAP_TO_APPLY_EFFECT_V1" in native_effects:
        raise SystemExit("AM patch must not change the native Ae effect-row behavior.")
    if "let header_h = 40.0;" not in frame or "let header_h = 64.0;" in frame:
        raise SystemExit("The editor must retain the original single-row 40px toolbar.")
    dock = (effectcraft / "crates/ui-egui/src/dock.rs").read_text(encoding="utf-8")
    if "FixedSecond(300.0)" not in dock or "FixedFirst(300.0)" not in dock:
        raise SystemExit("The original Ae fixed-width left/right panel arrangement was changed.")
    if '"AM 竖屏"' not in dock:
        raise SystemExit("AM 竖屏 must remain selectable in the original workspace menu.")
    if "file.importProject" not in (effectcraft / "crates/ui-egui/src/panels/home.rs").read_text(encoding="utf-8"):
        raise SystemExit("AM Home must retain the local unified project-import action.")
    am_home_start = home.find("// EFFECTCRAFT_AM_PORTRAIT_HOME_V1")
    am_home_end = home.find("pub fn show(app:", am_home_start)
    if am_home_start < 0 or am_home_end < 0:
        raise SystemExit("Could not isolate the AM Home surface for local-only validation.")
    am_home = home[am_home_start:am_home_end]
    if any(token in am_home for token in ("模板", "教程", "云端", "cloud", "server", "https://")):
        raise SystemExit("AM Home must not expose cloud, server-backed, or network-dependent features.")
    if "workspace_transition" in frame:
        raise SystemExit("AM patch must not add a workspace transition overlay to the Ae frame.")
    print("Verified the AM Home uses local project/media actions only and the Ae toolbar remains unchanged.")


def main() -> None:
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to checked-out source trees.")
    patch_dock(effectcraft)
    patch_workspace_selection(effectcraft)
    patch_workspace_tabs(effectcraft)
    patch_am_scoped_panel_touch_scroll(effectcraft)
    patch_home_surface(effectcraft)
    patch_android_layout_module(effectcraft)
    patch_activity(builder)
    verify_import_export_unchanged(effectcraft)
    print("Restored the original Ae toolbar and responsive three-column workspace.")
    print("AM remains a separate portrait workspace, selectable from the original workspace menu; Ae saved layouts are not migrated.")
    print("Project import/share/export routes and project formats were not changed.")
    print("Added only the AM portrait orientation bridge; no app-startup signer gate is added by AM.")
    

if __name__ == "__main__":
    main()
