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
                    &[jni::objects::JValue::Bool(if portrait { 1 } else { 0 })],
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
    """Make the existing layer In/Out drag zones reliably touchable on Android."""
    path = effectcraft / "crates/ui-egui/src/panels/timeline.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_AM_TOUCH_TRIM_HANDLES_V1"
    if marker in source:
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


def patch_am_effect_browser_button(effectcraft: Path) -> None:
    """Expose the complete native Ae effect browser directly from AM Effect Controls."""
    path = effectcraft / "crates/ui-egui/src/panels/effect_controls/panel.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AM_NATIVE_EFFECT_BROWSER_BUTTON_V1"
    if marker in source:
        return
    old = """    if fx.is_empty() {
        bp.text(
            pos2(body.center().x, body.min.y + 40.0),
            Align2::CENTER_CENTER,
            crate::i18n::tr("No effects. Drag one from Effects & Presets."),
            Tokens::ui(12.0),
            t.text_faint,
        );
    }"""
    new = """    if fx.is_empty() {
        // EFFECTCRAFT_AM_NATIVE_EFFECT_BROWSER_BUTTON_V1
        bp.text(
            pos2(body.center().x, body.min.y + 24.0),
            Align2::CENTER_CENTER,
            crate::i18n::tr("No effects added"),
            Tokens::ui(12.0),
            t.text_faint,
        );
        let add_rect = Rect::from_center_size(
            pos2(body.center().x, body.min.y + 70.0),
            vec2((body.width() - 24.0).max(120.0), 42.0),
        );
        let add = ui.put(add_rect, egui::Button::new(format!("＋ {}", crate::i18n::tr("Add Effect"))));
        app.auto.add_response("effectControls.addEffect", &add, "Add Effect");
        if add.clicked() {
            app.show_panel(crate::dock::PanelKind::EffectsPresets);
        }
    }"""
    source = replace_once(source, old, new, "AM direct access to the native Ae effect browser")
    path.write_text(source, encoding="utf-8")


def patch_workspace_selection(effectcraft: Path) -> None:
    path = effectcraft / "crates/ui-egui/src/app/window.rs"
    source = path.read_text(encoding="utf-8")
    marker = f'        self.ui.workspace = name.to_string();\n'
    call = f'''        self.ui.workspace = name.to_string();
        // EFFECTCRAFT_ANDROID_AM_PORTRAIT_WORKSPACE_V1
        crate::android_layout::set_workspace_portrait(name == "{WORKSPACE}");
'''
    source = replace_once(source, marker, call, "workspace orientation update")
    path.write_text(source, encoding="utf-8")


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
    print("Verified AM layout leaves the existing import router and original export UI connected.")


def main() -> None:
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR and ARTCRAFT_DIR must point to checked-out source trees.")
    patch_dock(effectcraft)
    patch_touch_trim_handles(effectcraft)
    patch_am_effect_browser_button(effectcraft)
    patch_workspace_selection(effectcraft)
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
