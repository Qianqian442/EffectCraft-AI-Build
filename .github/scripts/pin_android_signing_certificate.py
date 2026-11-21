#!/usr/bin/env python3
"""Pin the Android startup integrity check to the persistent release signing key."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    key = root / "keys" / "artcraft-builder.jks"
    password_file = root / "keys" / ".keystore-password"
    template = root / "templates" / "android" / "SafActivity.java"
    if not key.is_file() or not password_file.is_file() or not template.is_file():
        raise SystemExit("Persistent APK signing key, password, or SafActivity template is missing.")

    password = password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise SystemExit("Persistent Android signing key password file is empty.")

    result = subprocess.run(
        [
            "keytool", "-exportcert", "-keystore", str(key),
            "-storepass", password, "-alias", "artcraftbuilder",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    fingerprint = hashlib.sha256(result.stdout).hexdigest().upper()
    if not re.fullmatch(r"[A-F0-9]{64}", fingerprint):
        raise SystemExit("Could not calculate the APK signing certificate SHA-256 fingerprint.")

    source = template.read_text(encoding="utf-8")
    declaration_pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)(?:(?:public|protected|private)[ \t]+)?'
        r'static[ \t]+final[ \t]+String[ \t]+EXPECTED_SIGNING_CERT_SHA256'
        r'[ \t]*=[ \t]*"(?P<value>[A-Fa-f0-9]{64}|__EFFECTCRAFT_SIGNING_CERT_SHA256__)"[ \t]*;[ \t]*$'
    )
    declarations = list(declaration_pattern.finditer(source))
    if len(declarations) > 1:
        raise SystemExit("SafActivity.java contains multiple signing fingerprint declarations; refusing to guess.")

    if not declarations:
        tag_pattern = re.compile(
            r'(?m)^(?P<indent>[ \t]*)private static final String TAG = "[^"\n]*";[ \t]*$'
        )
        tags = list(tag_pattern.finditer(source))
        if len(tags) != 1:
            raise SystemExit("SafActivity.java must contain exactly one TAG constant insertion point.")
        tag = tags[0]
        insertion = (
            tag.group(0)
            + "\n"
            + tag.group("indent")
            + 'private static final String EXPECTED_SIGNING_CERT_SHA256 = "'
            + fingerprint
            + '";'
        )
        source = source[:tag.start()] + insertion + source[tag.end():]
    else:
        match = declarations[0]
        if match.group("value").upper() != fingerprint:
            source = (
                source[:match.start("value")]
                + fingerprint
                + source[match.end("value"):]
            )

    template.write_text(source, encoding="utf-8")
    verified = template.read_text(encoding="utf-8")
    verified_declarations = list(declaration_pattern.finditer(verified))
    if len(verified_declarations) != 1 or verified_declarations[0].group("value").upper() != fingerprint:
        raise SystemExit("Release signing certificate fingerprint was not pinned to the persistent key.")

    print("Pinned Android startup integrity check to the existing persistent release certificate (SHA-256).")
    print("The private keystore and password were not changed.")
    print("The app-start signature verification remains enabled.")


if __name__ == "__main__":
    main()
