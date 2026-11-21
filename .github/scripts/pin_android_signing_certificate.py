#!/usr/bin/env python3
"""Embed the public SHA-256 signer fingerprint for the persistent Android release key."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path


PLACEHOLDER = "__EFFECTCRAFT_SIGNING_CERT_SHA256__"
SIGNER_DECLARATION = re.compile(
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
        raise SystemExit("Could not calculate the SHA-256 APK signing certificate fingerprint.")

    source = template.read_text(encoding="utf-8")
    declarations = list(SIGNER_DECLARATION.finditer(source))
    if len(declarations) != 1:
        raise SystemExit(
            "SafActivity.java must contain exactly one EXPECTED_SIGNING_CERT_SHA256 declaration; "
            f"found {len(declarations)}. Refusing to weaken or guess the startup signature check."
        )

    current = declarations[0].group("value")
    if current != fingerprint:
        # The persistent JKS is the canonical signing identity for this app. Update only
        # the public fingerprint constant; never replace, regenerate, or modify the key.
        source = SIGNER_DECLARATION.sub(
            lambda match: match.group("prefix") + '"' + fingerprint + match.group("suffix"),
            source,
            count=1,
        )
        template.write_text(source, encoding="utf-8")

    verified = template.read_text(encoding="utf-8")
    verified_declarations = list(SIGNER_DECLARATION.finditer(verified))
    if len(verified_declarations) != 1 or verified_declarations[0].group("value") != fingerprint:
        raise SystemExit("Release signing certificate fingerprint was not pinned to the persistent key.")

    print("Pinned Android startup integrity check to the existing persistent release certificate (SHA-256).")
    print("Only the public fingerprint constant was synchronized; the private keystore and password were not changed.")
    print("The app-start signature verification remains enabled.")


if __name__ == "__main__":
    main()
