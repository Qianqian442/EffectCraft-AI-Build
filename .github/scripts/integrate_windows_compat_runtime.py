#!/usr/bin/env python3
"""Integrate the experimental Windows compatibility runtime into EffectCraft's generated APK.

The builder emits a single Android app module. Copy the audited Java runtime sources into that
generated source set, add only the dependencies used by its extractors/profile readers, initialize
the bridge from the generated Activity, and expose a Rust JNI API for a user-triggered installation.
No executable Windows plug-in is claimed to work until the runtime/host smoke tests pass.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_WINDOWS_COMPAT_RUNTIME_V1"


def replace_once(source: str, old: str, new: str, label: str, count: int = 1) -> str:
    found = source.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} occurrence(s), found {found}")
    return source.replace(old, new, count)


def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    build_assets = Path(__file__).resolve().parents[2]
    rust_helper = Path(__file__).with_name("windows_compat_android.rs")
    runtime_java = build_assets / "windows-compat/android-runtime/src/main/java"

    if not effectcraft.is_dir() or not builder.is_dir():
        raise SystemExit("EffectCraft source and Android builder must both be checked out.")
    if not rust_helper.is_file() or not runtime_java.is_dir():
        raise SystemExit("Windows compatibility Rust/Java runtime sources are missing.")

    # Add the Java runtime package to the crate's generated source set after the builder
    # generates the NativeActivity source. The builder calls build-common.sh before Gradle.
    build_common = builder / "lib/build-common.sh"
    common = build_common.read_text(encoding="utf-8")
    copy_anchor = '''    cp "$ROOT/templates/android/ArtCraftIme.java" "$IME_DIR/ArtCraftIme.java"
fi
'''
    copy_block = copy_anchor + '''
if [[ "$APP" == "effectcraft" ]]; then
    WINDOWS_COMPAT_JAVA_SOURCE="$ROOT/../build-assets/windows-compat/android-runtime/src/main/java"
    [[ -d "$WINDOWS_COMPAT_JAVA_SOURCE/com/effectcraft/windowscompat" ]] || fail "The Windows compatibility Java source tree is missing."
    mkdir -p "$ANDROID_DIR/java"
    cp -a "$WINDOWS_COMPAT_JAVA_SOURCE/." "$ANDROID_DIR/java/"
    echo "  -> installed the experimental Windows x86/x64 runtime Java bridge"
fi
'''
    if "WINDOWS_COMPAT_JAVA_SOURCE=" not in common:
        common = replace_once(common, copy_anchor, copy_block, "Android runtime Java copy hook")
        build_common.write_text(common, encoding="utf-8")

    # The generated Gradle app is single-module; include the runtime's ZIP/TAR, XZ, Zstandard
    # and profile JSON parsers directly rather than introducing a second Android library module.
    generator = builder / "lib/android_project.py"
    gradle_source = generator.read_text(encoding="utf-8")
    dependency_anchor = "    implementation 'androidx.games:games-activity:4.4.0'\n"
    extra_dependencies = dependency_anchor + """    // EffectCraft's optional Windows compatibility runtime (safe TAR/XZ/Zstandard extraction).
    implementation 'org.apache.commons:commons-compress:1.20'
    implementation 'org.tukaani:xz:1.7'
    implementation 'com.github.luben:zstd-jni:1.5.2-3@aar'
    implementation 'com.google.code.gson:gson:2.8.8'
"""
    if "commons-compress:1.20" not in gradle_source:
        gradle_source = replace_once(
            gradle_source, dependency_anchor, extra_dependencies,
            "Windows runtime Gradle dependencies"
        )
        generator.write_text(gradle_source, encoding="utf-8")

    # The generated EffectCraftActivity and the bridge share com.artcraft.effectcraft.
    activity_template = builder / "templates/android/SafActivity.java"
    activity = activity_template.read_text(encoding="utf-8")
    create_anchor = "        super.onCreate(savedInstanceState);\n"
    create_replacement = create_anchor + """        // EFFECTCRAFT_ANDROID_WINDOWS_COMPAT_RUNTIME_V1
        WindowsCompatAndroidBridge.initialize(getApplicationContext());
"""
    if MARKER not in activity:
        activity = replace_once(activity, create_anchor, create_replacement,
                                 "Windows runtime Activity initialization")
        activity_template.write_text(activity, encoding="utf-8")

    # Store the JNI façade in ui-egui; the app's existing Android bridge already depends on jni 0.22,
    # but keep this integration independently correct if that prior patch changes.
    ui = effectcraft / "crates/ui-egui"
    source_dir = ui / "src"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "windows_compat_android.rs").write_text(
        rust_helper.read_text(encoding="utf-8"), encoding="utf-8"
    )

    cargo = ui / "Cargo.toml"
    cargo_source = cargo.read_text(encoding="utf-8")
    if 'jni = "0.22"' not in cargo_source:
        cargo_source = replace_once(
            cargo_source,
            "[dev-dependencies]\\n",
            "[target.'cfg(target_os = \\"android\\")'.dependencies]\\njni = \\"0.22\\"\\n\\n[dev-dependencies]\\n",
            "Android JNI dependency"
        )
        cargo.write_text(cargo_source, encoding="utf-8")

    lib = source_dir / "lib.rs"
    lib_source = lib.read_text(encoding="utf-8")
    if "mod windows_compat_android;" not in lib_source:
        if "pub(crate) mod plugin_migration;\\n" in lib_source:
            lib_source = replace_once(
                lib_source,
                "pub(crate) mod plugin_migration;\\n",
                "pub(crate) mod plugin_migration;\\nmod windows_compat_android;\\n",
                "Windows runtime Rust module"
            )
        else:
            # Fallback location is after the public module block; keep inner crate docs first.
            anchor = "pub(crate) mod a11y;\\n"
            lib_source = replace_once(
                lib_source, anchor, "mod windows_compat_android;\\n" + anchor,
                "Windows runtime Rust module"
            )

    if "init_android_windows_compat_bridge" not in lib_source:
        lib_source += """
#[cfg(target_os = "android")]
pub fn init_android_windows_compat_bridge(vm_ptr: *mut std::ffi::c_void) {
    windows_compat_android::init_android_vm(vm_ptr);
}

#[cfg(not(target_os = "android"))]
pub fn init_android_windows_compat_bridge(_vm_ptr: *mut std::ffi::c_void) {}

pub(crate) fn start_windows_compat_runtime_install() -> Result<String, String> {
    windows_compat_android::start_runtime_install()
}

pub(crate) fn poll_windows_compat_runtime_install(request_id: &str) -> Result<Option<String>, String> {
    windows_compat_android::poll_runtime_install(request_id)
}

pub(crate) fn start_windows_compat_aex_test(source_path: &str) -> Result<String, String> {
    windows_compat_android::start_aex_plugin_test(source_path)
}
"""
    lib.write_text(lib_source, encoding="utf-8")

    # Set the JVM pointer after android-activity/egui-winit installs its VM. The builder has
    # two code paths (generated NativeActivity and adapter); patch both to keep them consistent.
    if "init_android_windows_compat_bridge" not in common:
        vm_anchor = "egui_winit::android_activity::set_vm(android_app.vm_as_ptr());"
        common = replace_once(
            common, vm_anchor,
            vm_anchor + "\n    effectcraft_ui_egui::init_android_windows_compat_bridge(android_app.vm_as_ptr());",
            "Windows runtime JNI VM initialization", count=2
        )
        build_common.write_text(common, encoding="utf-8")

    print("Integrated the experimental Windows runtime Java sources and Android dependencies.")
    print("Added app-private runtime installation APIs and initialized the JNI bridge.")
    print("The runtime installer downloads pinned Wine/Proton assets and installs the embedded, SHA-256-pinned BOX32 binary.")
    print("No claim of actual Windows PE/AEX execution is made by this integration step.")


if __name__ == "__main__":
    main()
