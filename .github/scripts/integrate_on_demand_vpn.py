#!/usr/bin/env python3
"""Install the Cloudflare MASQUE Android engine into the generated main APK."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

MARKER = "EFFECTCRAFT_CLOUDFLARE_MASQUE_VPN_INTEGRATION_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    artcraft = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    aar_source = Path(os.environ["WARP_AAR_PATH"]).resolve()
    target_crate = effectcraft / "p2p-bridge"
    builder_script = artcraft / "lib/build-common.sh"
    aar_target = target_crate / "android/effectcraft-warp-masque.aar"

    if not (target_crate / "Cargo.toml").is_file():
        raise SystemExit("P2P JNI/command bridge must be integrated before the task-scoped VPN patch")
    if not (target_crate / "android/NativeP2P.java").is_file():
        raise SystemExit("Main APK NativeP2P.java is missing")
    if not (target_crate / "android/EffectCraftVpnService.java").is_file():
        raise SystemExit("Cloudflare MASQUE EffectCraftVpnService.java is missing")
    if not aar_source.is_file() or aar_source.stat().st_size < 100_000:
        raise SystemExit("Cloudflare MASQUE Android AAR is missing or unexpectedly small")
    if not builder_script.is_file():
        raise SystemExit(f"Android builder script missing: {builder_script}")

    import zipfile
    with zipfile.ZipFile(aar_source) as archive:
        names = set(archive.namelist())
        if "classes.jar" not in names:
            raise SystemExit("Cloudflare MASQUE AAR has no classes.jar")
        if not any(name.startswith("jni/arm64-v8a/") and name.endswith(".so") for name in names):
            raise SystemExit("Cloudflare MASQUE AAR has no ARM64 native library")
    shutil.copy2(aar_source, aar_target)

    source = builder_script.read_text(encoding="utf-8")
    if MARKER not in source:
        anchor = 'python3 "$ROOT/lib/android_project.py" "$ROOT" "$ANDROID_DIR" "$APP" "$APP_VERSION"\n# MIN_SDK feeds cargo-ndk'
        block = r'''# EFFECTCRAFT_CLOUDFLARE_MASQUE_VPN_INTEGRATION_V1
# Inject the native Cloudflare MASQUE bridge after the Android project has been
# generated, but before the launcher is compiled and packaged.
if [[ "$APP" == "effectcraft" ]]; then
    P2P_CRATE="$ROOT/$SRC/p2p-bridge"
    python3 - "$ANDROID_DIR" "$P2P_CRATE/android/EffectCraftVpnService.java" "$P2P_CRATE/android/effectcraft-warp-masque.aar" <<'PY'
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

android_dir = Path(sys.argv[1])
service_source = Path(sys.argv[2])
aar_source = Path(sys.argv[3])
java_root = android_dir / "java"
manifest_path = android_dir / "AndroidManifest.xml"
gradle_path = android_dir / "android" / "build.gradle"

if not java_root.is_dir():
    raise SystemExit(f"Cloudflare MASQUE Android Java directory missing: {java_root}")
for path in (manifest_path, gradle_path, service_source, aar_source):
    if not path.is_file():
        raise SystemExit(f"Cloudflare MASQUE Android build input missing: {path}")

package_dir = java_root / "com" / "artcraft" / "effectcraft"
package_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(service_source, package_dir / "EffectCraftVpnService.java")

aar_dir = android_dir / "android" / "libs"
aar_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(aar_source, aar_dir / "effectcraft-warp-masque.aar")

gradle = gradle_path.read_text(encoding="utf-8")
dependency = "implementation files('libs/effectcraft-warp-masque.aar')"
if dependency not in gradle:
    anchor = "dependencies {"
    if gradle.count(anchor) != 1:
        raise SystemExit("Could not locate the generated Gradle dependencies block")
    gradle = gradle.replace(anchor, anchor + "\n    " + dependency, 1)
    gradle_path.write_text(gradle, encoding="utf-8")

android_ns = "http://schemas.android.com/apk/res/android"
ET.register_namespace("android", android_ns)
def a(name):
    return "{" + android_ns + "}" + name

tree = ET.parse(manifest_path)
root = tree.getroot()
for permission in (
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_SYSTEM_EXEMPTED",
    "android.permission.POST_NOTIFICATIONS",
):
    if not any(p.get(a("name")) == permission for p in root.findall("uses-permission")):
        ET.SubElement(root, "uses-permission", {a("name"): permission})

application = root.find("application")
if application is None:
    raise SystemExit("Generated Android manifest has no application element")
services = [
    item for item in application.findall("service")
    if item.get(a("name")) in (".EffectCraftVpnService", "com.artcraft.effectcraft.EffectCraftVpnService")
]
service = services[0] if services else ET.SubElement(application, "service")
service.set(a("name"), "com.artcraft.effectcraft.EffectCraftVpnService")
service.set(a("permission"), "android.permission.BIND_VPN_SERVICE")
service.set(a("exported"), "true")
service.set(a("foregroundServiceType"), "systemExempted")
intent_filter = service.find("intent-filter")
if intent_filter is None:
    intent_filter = ET.SubElement(service, "intent-filter")
if not any(action.get(a("name")) == "android.net.VpnService" for action in intent_filter.findall("action")):
    ET.SubElement(intent_filter, "action", {a("name"): "android.net.VpnService"})
for meta in list(service.findall("meta-data")):
    if meta.get(a("name")) == "android.net.VpnService.SUPPORTS_ALWAYS_ON":
        service.remove(meta)
ET.SubElement(service, "meta-data", {
    a("name"): "android.net.VpnService.SUPPORTS_ALWAYS_ON",
    a("value"): "false",
})
tree.write(manifest_path, encoding="utf-8", xml_declaration=True)

activities = []
for candidate in java_root.rglob("*Activity.java"):
    java = candidate.read_text(encoding="utf-8")
    if "extends NativeActivity" in java and "protected void onCreate(Bundle savedInstanceState)" in java:
        activities.append((candidate, java))
if len(activities) != 1:
    raise SystemExit(f"Expected one generated NativeActivity, found {len(activities)}")
activity_path, activity = activities[0]
if "EFFECTCRAFT_VPN_PERMISSION_RESULT_V1" not in activity:
    callback = """
    // EFFECTCRAFT_VPN_PERMISSION_RESULT_V1
    @Override
    protected void onActivityResult(int requestCode, int resultCode, android.content.Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == EffectCraftVpnService.PERMISSION_REQUEST_CODE) {
            NativeP2P.onVpnPermissionActivityResult(resultCode);
        }
    }
"""
    end = activity.rfind("}")
    if end < 0:
        raise SystemExit("Generated NativeActivity has no closing brace")
    activity = activity[:end] + callback + activity[end:]
    activity_path.write_text(activity, encoding="utf-8")

print("Registered main-APK Cloudflare MASQUE VpnService, ARM64 engine AAR and Android permission callback.")
PY
fi

'''
        source = replace_once(source, anchor, anchor + "\n" + block, "Android Cloudflare MASQUE post-generation injection point")
        builder_script.write_text(source, encoding="utf-8")

    print(f"Installed Cloudflare MASQUE AAR at {aar_target}")
    print(f"Patched Android build integration in {builder_script}")


if __name__ == "__main__":
    main()
