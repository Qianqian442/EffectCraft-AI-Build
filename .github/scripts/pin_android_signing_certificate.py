#!/usr/bin/env python3
"""Embed the public SHA-256 signer fingerprint for the persistent Android release key."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


PLACEHOLDER = "__EFFECTCRAFT_SIGNING_CERT_SHA256__"


def main() -> None:
    root = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    key = root / "keys" / "artcraft-builder.jks"
    password_file = root / "keys" / ".keystore-password"
    template = root / "templates" / "android" / "SafActivity.java"
    if not key.is_file() or not password_file.is_file() or not template.is_file():
        raise SystemExit("Persistent APK signing key, password, or SafActivity template is missing.")
    password = password_file.read_text(encoding="utf-8").strip()
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
    if len(fingerprint) != 64:
        raise SystemExit("Could not calculate the SHA-256 APK signing certificate fingerprint.")
    source = template.read_text(encoding="utf-8")
    if PLACEHOLDER in source:
        if source.count(PLACEHOLDER) != 1:
            raise SystemExit("Expected one release signer placeholder in SafActivity.java.")
        source = source.replace(PLACEHOLDER, fingerprint, 1)
        template.write_text(source, encoding="utf-8")
    elif fingerprint not in source:
        raise SystemExit("SafActivity.java has already been pinned to a different release certificate.")
    if fingerprint not in template.read_text(encoding="utf-8"):
        raise SystemExit("Release signing certificate fingerprint was not embedded.")
    print("Pinned Android startup integrity check to the existing release certificate (SHA-256).")
    print("Only the public certificate fingerprint is embedded; the keystore and password remain private.")


if __name__ == "__main__":
    main()
