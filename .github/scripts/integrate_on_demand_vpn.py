#!/usr/bin/env python3
"""Integrate the short-lived Android VpnService and Hev tun2socks AAR."""
from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ET.register_namespace("android", ANDROID_NS)


def attr(name: str) -> str:
    return f"{{{ANDROID_NS}}}{name}"


def add_permission(root: ET.Element, name: str) -> None:
    for node in root.findall("uses-permission"):
        if node.get(attr("name")) == name:
            return
    ET.SubElement(root, "uses-permission", {attr("name"): name})


def integrate_manifest(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    for permission in (
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SYSTEM_EXEMPTED",
        "android.permission.POST_NOTIFICATIONS",
    ):
        add_permission(root, permission)

    app = root.find("application")
    if app is None:
        raise SystemExit("AndroidManifest.xml does not contain an application element")

    existing = [
        service for service in app.findall("service")
        if service.get(attr("name")) in (
            ".EffectCraftVpnService",
            "com.artcraft.effectcraft.EffectCraftVpnService",
        )
    ]
    service = existing[0] if existing else ET.SubElement(app, "service")
    service.set(attr("name"), "com.artcraft.effectcraft.EffectCraftVpnService")
    service.set(attr("permission"), "android.permission.BIND_VPN_SERVICE")
    service.set(attr("exported"), "true")
    service.set(attr("foregroundServiceType"), "systemExempted")

    intent_filter = service.find("intent-filter")
    if intent_filter is None:
        intent_filter = ET.SubElement(service, "intent-filter")
    if not any(a.get(attr("name")) == "android.net.VpnService" for a in intent_filter.findall("action")):
        ET.SubElement(intent_filter, "action", {attr("name"): "android.net.VpnService"})

    for prop in service.findall("property"):
        if prop.get(attr("name")) == "android.net.VpnService.SUPPORTS_ALWAYS_ON":
            service.remove(prop)
    ET.SubElement(service, "meta-data", {
        attr("name"): "android.net.VpnService.SUPPORTS_ALWAYS_ON",
        attr("value"): "false",
    })

    tree.write(path, encoding="utf-8", xml_declaration=True)


def add_aap_dependency(gradle_path: Path) -> None:
    text = gradle_path.read_text(encoding="utf-8")
    dependency = "implementation files('libs/hev-socks5-tunnel.aar')"
    if dependency in text:
        return
    anchor = "dependencies {"
    if text.count(anchor) != 1:
        raise SystemExit("Could not find exactly one Gradle dependencies block")
    text = text.replace(anchor, anchor + "\n    " + dependency, 1)
    gradle_path.write_text(text, encoding="utf-8")


def patch_activity(java_root: Path) -> Path:
    candidates = []
    for path in java_root.rglob("*Activity.java"):
        text = path.read_text(encoding="utf-8")
        if "extends NativeActivity" in text and "protected void onCreate(Bundle savedInstanceState)" in text:
            candidates.append((path, text))
    if len(candidates) != 1:
        raise SystemExit(f"Expected one generated NativeActivity, found {len(candidates)}")
    path, text = candidates[0]
    marker = "EFFECTCRAFT_VPN_PERMISSION_RESULT_V1"
    if marker not in text:
        override = """
    // EFFECTCRAFT_VPN_PERMISSION_RESULT_V1
    @Override
    protected void onActivityResult(int requestCode, int resultCode, android.content.Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == EffectCraftVpnService.PERMISSION_REQUEST_CODE) {
            NativeP2P.onVpnPermissionActivityResult(resultCode);
        }
    }
"""
        index = text.rfind("}")
        if index < 0:
            raise SystemExit("Generated NativeActivity has no closing brace")
        text = text[:index] + override + text[index:]
        path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    assets = Path(os.environ.get("BUILD_ASSETS_DIR", Path(__file__).resolve().parents[2])).resolve()
    android_dir = root / "apps/effectcraft-android"
    java_root = android_dir / "java"
    gradle_path = android_dir / "android/build.gradle"
    manifest_path = android_dir / "AndroidManifest.xml"

    source_service = assets / "p2p-bridge/android/EffectCraftVpnService.java"
    aar_source = Path(os.environ.get("HEV_AAR_PATH", "")).resolve()
    if not source_service.is_file():
        raise SystemExit(f"VPN service source missing: {source_service}")
    if not aar_source.is_file() or aar_source.stat().st_size < 100_000:
        raise SystemExit("Pinned Hev tun2socks AAR is missing or unexpectedly small")
    for path in (java_root, gradle_path, manifest_path):
        if not path.exists():
            raise SystemExit(f"Generated Android build output missing: {path}")

    package_dir = java_root / "com/artcraft/effectcraft"
    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_service, package_dir / "EffectCraftVpnService.java")

    aar_dir = android_dir / "android/libs"
    aar_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(aar_source, aar_dir / "hev-socks5-tunnel.aar")

    add_aap_dependency(gradle_path)
    integrate_manifest(manifest_path)
    activity = patch_activity(java_root)

    print(f"Installed EffectCraftVpnService: {package_dir / 'EffectCraftVpnService.java'}")
    print(f"Bundled Hev tun2socks: {aar_dir / 'hev-socks5-tunnel.aar'}")
    print(f"Registered Android VPN service and permission callback: {activity}")
    print("Only the EffectCraft package and explicitly configured Worker IP routes enter this task VPN.")


if __name__ == "__main__":
    main()
