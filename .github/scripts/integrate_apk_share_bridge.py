#!/usr/bin/env python3
"""Install the QQ-only, admin-authorized APK share provider into the generated Android project."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

MARKER = "EFFECTCRAFT_APK_SHARE_BRIDGE_V1"
BUILDER_ANCHOR = 'python3 "$ROOT/lib/android_project.py" "$ROOT" "$ANDROID_DIR" "$APP" "$APP_VERSION"\n'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    artcraft = Path(os.environ.get("ARTCRAFT_DIR", "artcraft")).resolve()
    assets = Path(os.environ.get("BUILD_ASSETS_DIR", "build-assets")).resolve()
    provider_source = assets / "apk-share-bridge" / "ApkShareProvider.java"
    builder_script = artcraft / "lib" / "build-common.sh"
    provider_template = artcraft / "templates" / "android" / "ApkShareProvider.java"

    if not provider_source.is_file():
        raise SystemExit(f"APK share provider source is missing: {provider_source}")
    if not builder_script.is_file():
        raise SystemExit(f"Android builder script is missing: {builder_script}")

    provider_template.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(provider_source, provider_template)

    source = builder_script.read_text(encoding="utf-8")
    if MARKER not in source:
        block = r'''# EFFECTCRAFT_APK_SHARE_BRIDGE_V1
# Install the QQ-only APK content provider after the generated manifest exists.
if [[ "$APP" == "effectcraft" ]]; then
    python3 - "$ANDROID_DIR" "$ROOT/templates/android/ApkShareProvider.java" <<'PY'
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

android_dir = Path(sys.argv[1])
provider_source = Path(sys.argv[2])
package_dir = android_dir / "java" / "com" / "artcraft" / "effectcraft"
package_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(provider_source, package_dir / "ApkShareProvider.java")

manifest = android_dir / "AndroidManifest.xml"
if not manifest.is_file():
    raise SystemExit(f"Generated Android manifest is missing: {manifest}")

android_ns = "http://schemas.android.com/apk/res/android"
ET.register_namespace("android", android_ns)
root = ET.parse(manifest).getroot()
queries = root.find("queries")
if queries is None:
    queries = ET.Element("queries")
    root.insert(0, queries)

for package_name in ("com.qianqian.effectcraftadmin", "com.tencent.mobileqq"):
    found = any(
        item.get(f"{{{android_ns}}}name") == package_name
        for item in queries.findall("package")
    )
    if not found:
        ET.SubElement(queries, "package", {f"{{{android_ns}}}name": package_name})

application = root.find("application")
if application is None:
    raise SystemExit("Generated Android manifest has no application element")

provider = None
for candidate in application.findall("provider"):
    if candidate.get(f"{{{android_ns}}}name") in (
        ".ApkShareProvider", "com.artcraft.effectcraft.ApkShareProvider"
    ):
        provider = candidate
        break

if provider is None:
    provider = ET.SubElement(application, "provider")
provider.set(f"{{{android_ns}}}name", ".ApkShareProvider")
provider.set(f"{{{android_ns}}}authorities", "com.artcraft.effectcraft.apkshare")
provider.set(f"{{{android_ns}}}exported", "true")
provider.set(f"{{{android_ns}}}grantUriPermissions", "true")

ET.ElementTree(root).write(manifest, encoding="utf-8", xml_declaration=True)
print(f"Installed QQ-only APK provider and package visibility declarations in {manifest}")
PY
fi

'''
        source = replace_once(source, BUILDER_ANCHOR, BUILDER_ANCHOR + block, "generated manifest integration point")
        builder_script.write_text(source, encoding="utf-8")

    print(f"Prepared APK share provider at {provider_template}")
    print(f"Patched Android project generation in {builder_script}")


if __name__ == "__main__":
    main()
