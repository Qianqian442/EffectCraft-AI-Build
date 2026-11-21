#!/usr/bin/env python3
"""Pin the Android startup signer check to the persistent release certificate."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

DECLARATION = re.compile(
    r'(?m)^(?P<prefix>[ \t]*(?:(?:public|protected|private)[ \t]+)?static[ \t]+final[ \t]+String[ \t]+EXPECTED_SIGNING_CERT_SHA256[ \t]*=[ \t]*)"'
    r'(?P<value>[A-Fa-f0-9]{64}|__EFFECTCRAFT_SIGNING_CERT_SHA256__)'
    r'(?P<suffix>"[ \t]*;[ \t]*)$'
)


def main() -> None:
    root = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    key = root / "keys" / "artcraft-builder.jks"
    password_file = root / "keys" / ".keystore-password"
    template = root / "templates" / "android" / "SafActivity.java"
    if not key.is_file() or not password_file.is_file() or not template.is_file():
        raise SystemExit("Persistent APK signing key, password, or SafActivity template is missing.")

    password = password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise SystemExit("Persistent APK signing key password file is empty.")

    result = subprocess.run(
        ["keytool", "-exportcert", "-keystore", str(key),
         "-storepass", password, "-alias", "artcraftbuilder"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    fingerprint = hashlib.sha256(result.stdout).hexdigest().upper()
    if not re.fullmatch(r"[A-F0-9]{64}", fingerprint):
        raise SystemExit("Could not calculate the SHA-256 APK signing certificate fingerprint.")

    source = template.read_text(encoding="utf-8")
    declarations = list(DECLARATION.finditer(source))
    if len(declarations) > 1:
        raise SystemExit("SafActivity.java contains multiple signing fingerprint declarations.")

    if not declarations:
        tag = re.search(
            r'(?m)^(?P<indent>[ \t]*)private static final String TAG = "[^"\n]*";[ \t]*$',
            source,
        )
        if not tag:
            raise SystemExit("SafActivity.java has no unique TAG constant insertion point.")
        insertion = (
            tag.group(0) + "\n" + tag.group("indent")
            + 'private static final String EXPECTED_SIGNING_CERT_SHA256 = "'
            + fingerprint + '";'
        )
        source = source[:tag.start()] + insertion + source[tag.end():]
    else:
        match = declarations[0]
        if match.group("value") != fingerprint:
            source = source[:match.start()] + (
                match.group("prefix") + '"' + fingerprint + match.group("suffix")
            ) + source[match.end():]

    template.write_text(source, encoding="utf-8")
    verified = list(DECLARATION.finditer(template.read_text(encoding="utf-8")))
    if len(verified) != 1 or verified[0].group("value") != fingerprint:
        raise SystemExit("Release signing certificate fingerprint was not pinned to the persistent key.")

    print("Pinned Android startup integrity check to the existing persistent release certificate (SHA-256).")
    print("The private keystore and password were not changed; signature verification remains enabled.")


if __name__ == "__main__":
    main()
