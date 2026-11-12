#!/usr/bin/env python3
"""Integrate the shared libp2p transport into the generated EffectCraft Android launcher."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

MARKER = "EFFECTCRAFT_PUBLIC_P2P_INTEGRATION_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    artcraft = Path(os.environ.get("ARTCRAFT_DIR", "artcraft")).resolve()
    effectcraft = Path(os.environ.get("EFFECTCRAFT_DIR", "artcraft/source/effectcraft")).resolve()
    assets = Path(os.environ.get("BUILD_ASSETS_DIR", "build-assets")).resolve()

    source_crate = assets / "p2p-bridge"
    target_crate = effectcraft / "p2p-bridge"
    builder_script = artcraft / "lib" / "build-common.sh"
    java_template = source_crate / "android" / "NativeP2P.java"

    if not (source_crate / "Cargo.toml").is_file():
        raise SystemExit(f"P2P Cargo manifest missing: {source_crate / 'Cargo.toml'}")
    if not java_template.is_file():
        raise SystemExit(f"Main-app NativeP2P.java missing: {java_template}")
    if not builder_script.is_file():
        raise SystemExit(f"Android builder script missing: {builder_script}")

    if target_crate.exists():
        shutil.rmtree(target_crate)
    shutil.copytree(source_crate, target_crate)

    source = builder_script.read_text(encoding="utf-8")
    if MARKER not in source:
        anchor = "# The shared update checker (templates/android/UpdateCheck.java) is installed next to every"
        block = r'''# EFFECTCRAFT_PUBLIC_P2P_INTEGRATION_V1
# Build and package the native encrypted peer transport after the Android launcher
# directory has been generated, before Gradle assembles the APK.
if [[ "$APP" == "effectcraft" ]]; then
    P2P_CRATE="$ROOT/$SRC/p2p-bridge"
    [[ -f "$P2P_CRATE/Cargo.toml" ]] || fail "EffectCraft P2P crate is missing at $P2P_CRATE"
    cargo ndk -V >/dev/null 2>&1 || fail "cargo-ndk is required for the P2P native library"
    say 3 "Building EffectCraft encrypted P2P transport (arm64-v8a)..."
    (cd "$P2P_CRATE" && cargo ndk -t arm64-v8a -o "$ANDROID_DIR/jniLibs" build --release)
    test -s "$ANDROID_DIR/jniLibs/arm64-v8a/libeffectcraft_p2p.so" || fail "P2P native library was not produced"

    python3 - "$ANDROID_DIR" "$P2P_CRATE/android/NativeP2P.java" <<'PY'
from pathlib import Path
import sys, tomllib

android_dir = Path(sys.argv[1])
helper_source = Path(sys.argv[2])
manifest = android_dir / "Cargo.toml"
data = tomllib.loads(manifest.read_text(encoding="utf-8"))
package_name = data["package"]["metadata"]["android"]["package"]
if package_name != "com.artcraft.effectcraft":
    raise SystemExit(f"Unexpected EffectCraft Android package for P2P JNI: {package_name}")

text = manifest.read_text(encoding="utf-8")
permission_block = '''
[[package.metadata.android.uses_permission]]
name = "android.permission.ACCESS_WIFI_STATE"

[[package.metadata.android.uses_permission]]
name = "android.permission.CHANGE_WIFI_MULTICAST_STATE"
'''
if "android.permission.CHANGE_WIFI_MULTICAST_STATE" not in text:
    anchor = "[package.metadata.android.application]"
    if text.count(anchor) != 1:
        raise SystemExit("Cannot add the P2P multicast permissions to the Android manifest")
    text = text.replace(anchor, permission_block + "\n" + anchor, 1)
    manifest.write_text(text, encoding="utf-8")

package_dir = android_dir / "java" / Path(*package_name.split("."))
package_dir.mkdir(parents=True, exist_ok=True)
(package_dir / "NativeP2P.java").write_text(helper_source.read_text(encoding="utf-8"), encoding="utf-8")

activities = list(package_dir.glob("*Activity.java"))
target = None
for candidate in activities:
    java = candidate.read_text(encoding="utf-8")
    if "extends NativeActivity" in java and "protected void onCreate(Bundle savedInstanceState)" in java:
        target = candidate
        break
if target is None:
    raise SystemExit("Generated EffectCraft NativeActivity not found; refusing to ship an unused P2P library")

java = target.read_text(encoding="utf-8")
if "NativeP2P.start(this)" not in java:
    anchor = "        super.onCreate(savedInstanceState);"
    if java.count(anchor) != 1:
        raise SystemExit("Could not locate EffectCraft Activity onCreate for P2P startup")
    java = java.replace(
        anchor,
        anchor + "\n        try { NativeP2P.start(this); } catch (Throwable error) { Log.e(\"EffectCraftP2P\", \"P2P startup failed; editor remains available\", error); }",
        1,
    )
    target.write_text(java, encoding="utf-8")

print(f"Bundled native P2P node in {target} and {package_dir / 'NativeP2P.java'}")
PY
fi

'''
        source = replace_once(source, anchor, block + anchor, "P2P build insertion point")
        builder_script.write_text(source, encoding="utf-8")

    print(f"Prepared shared P2P transport at {target_crate}")
    print(f"Patched Android build integration in {builder_script}")


if __name__ == "__main__":
    main()
