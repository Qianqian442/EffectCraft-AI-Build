#!/usr/bin/env python3
"""Apply the first native AbsentMotion external-navigation cleanup.

Pinned input: Comett1225/AbsentMotion v5.1.1. Only browser/web jump actions are
removed here. Local help WebView navigation, project/media URI handling, Android
permission/settings flows, and the in-app APK download/install flow are retained.
"""
from __future__ import annotations

import os
from pathlib import Path

PIN = "f350576485c42ff7aefa5c2f205b9f1b8ad873f7"
MARKER = "AE_AM_EXTERNAL_NAVIGATION_CLEANUP_V1"


def replace_exact(source: str, old: str, new: str, label: str) -> str:
    if new and new in source and old not in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def patch_help(root: Path) -> None:
    path = root / "android/src/main/kotlin/app/absentmotion/ui/home/HelpScreen.kt"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return
    source = replace_exact(
        source,
        "import androidx.compose.ui.platform.LocalUriHandler\n",
        "",
        "remove external URI handler import from HelpScreen",
    )
    source = replace_exact(
        source,
        "    val links = LocalUriHandler.current\n",
        "",
        "remove external URI handler from HelpScreen",
    )
    source = replace_exact(
        source,
        "    val client = remember { HelpClient(tag, context.applicationContext) { url -> runCatching { links.openUri(url) } } }",
        "    val client = remember { HelpClient(tag, context.applicationContext) }",
        "make HelpClient local-only",
    )
    source = replace_exact(
        source,
        "private class HelpClient(var tag: String, private val context: android.content.Context, private val openExternal: (String) -> Unit) : WebViewClient() {",
        "private class HelpClient(var tag: String, private val context: android.content.Context) : WebViewClient() {",
        "remove external callback from HelpClient",
    )
    source = replace_exact(
        source,
        "        if (request.url.scheme == \"https\") openExternal(url)\n",
        "",
        "block external HelpScreen navigation without launching browser",
    )
    source = source.replace(
        "private const val HELP_ROOT =",
        "// " + MARKER + "\nprivate const val HELP_ROOT =",
        1,
    )
    if "openExternal" in source or "links.openUri" in source:
        raise SystemExit("HelpScreen still contains an external navigation callback.")
    path.write_text(source, encoding="utf-8")
    print("Patched HelpScreen: bundled/local help remains; external browser jumps are blocked.")


def patch_update_dialog(root: Path) -> None:
    path = root / "android/src/main/kotlin/app/absentmotion/ui/home/UpdateDialog.kt"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return
    source = replace_exact(
        source,
        "import androidx.compose.ui.platform.LocalUriHandler\n",
        "",
        "remove external URI handler import from UpdateDialog",
    )
    source = replace_exact(
        source,
        "    val links = LocalUriHandler.current\n"
        "    fun open(link: String) = runCatching { links.openUri(link) }.onFailure {\n"
        "        android.widget.Toast.makeText(context, context.getString(R.string.update_open_failed), android.widget.Toast.LENGTH_LONG).show()\n"
        "    }\n",
        "",
        "remove browser opener from UpdateDialog",
    )
    source = replace_exact(
        source,
        "        if (available.external) Detail(stringResource(R.string.update_external))\n",
        "",
        "remove external-release browser prompt",
    )
    source = replace_exact(
        source,
        "            Secondary(stringResource(R.string.update_changelog)) { open(release.link) }\n",
        "",
        "remove external changelog link",
    )
    source = replace_exact(
        source,
        "            else if (!available.external) Primary(stringResource(R.string.update_download)) { close(); open(release.link) }\n",
        "",
        "remove external download-page fallback",
    )
    source = source.replace(
        "@Composable\ninternal fun UpdateDialog() {",
        "// " + MARKER + "\n@Composable\ninternal fun UpdateDialog() {",
        1,
    )
    if "LocalUriHandler" in source or "open(release.link)" in source or "links.openUri" in source:
        raise SystemExit("UpdateDialog still exposes an external browser jump.")
    if "Updater.start(context, release)" not in source:
        raise SystemExit("The safe in-app APK update/download flow was accidentally removed.")
    path.write_text(source, encoding="utf-8")
    print("Patched UpdateDialog: external changelog/download-page jumps removed; in-app APK flow retained.")


def audit(root: Path) -> None:
    patterns = ("openUri(", "ACTION_VIEW", "Intent.ACTION_VIEW", "LocalUriHandler")
    matches: list[str] = []
    for base in (root / "android/src/main", root / "shared/kotlin"):
        for path in base.rglob("*.kt"):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for number, line in enumerate(lines, 1):
                if any(token in line for token in patterns):
                    matches.append(f"{path.relative_to(root)}:{number}:{line.strip()}")
    print("External-navigation audit inventory (remaining candidates require classification):")
    for item in matches:
        print("  " + item)
    # Known user-facing web entry points patched above must not regress.
    for relative in (
        "android/src/main/kotlin/app/absentmotion/ui/home/HelpScreen.kt",
        "android/src/main/kotlin/app/absentmotion/ui/home/UpdateDialog.kt",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        if MARKER not in source:
            raise SystemExit(f"Missing external-navigation cleanup marker in {relative}")


def main() -> None:
    root_value = os.environ.get("ABSENTMOTION_DIR")
    if not root_value:
        raise SystemExit("ABSENTMOTION_DIR must point to the pinned AbsentMotion checkout.")
    root = Path(root_value).resolve()
    if not (root / "LICENSE").is_file() or not (root / "android/src/main/AndroidManifest.xml").is_file():
        raise SystemExit("AbsentMotion checkout is incomplete or missing its license/Android source.")
    patch_help(root)
    patch_update_dialog(root)
    audit(root)


if __name__ == "__main__":
    main()
