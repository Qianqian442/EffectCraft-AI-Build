#!/usr/bin/env python3
"""Create the data-only Ae DeepSeek model ZIP accepted by the Android model importer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

MODEL_FILE = "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf"
PACKAGE_FILE = "Ae-DeepSeek-AI-Model-Package.zip"
PACKAGE_FORMAT = "ae-ai-model-package"
PACKAGE_ID = "ae.deepseek.r1.distill.qwen.1.5b.iq4_xs"
MIN_MODEL_BYTES = 500 * 1024 * 1024
MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024
MODEL_SOURCE = (
    "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/"
    "resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_package(model_path: Path, output_path: Path) -> dict[str, object]:
    if not model_path.is_file():
        raise SystemExit(f"Model file not found: {model_path}")

    size_bytes = model_path.stat().st_size
    if not MIN_MODEL_BYTES <= size_bytes <= MAX_MODEL_BYTES:
        raise SystemExit(
            f"Model size is outside the supported 500 MiB–2 GiB range: {size_bytes} bytes"
        )

    with model_path.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise SystemExit("Downloaded model does not have the expected GGUF file signature.")

    model_hash = sha256_file(model_path)
    manifest = {
        "format": PACKAGE_FORMAT,
        "format_version": 1,
        "id": PACKAGE_ID,
        "model_file": MODEL_FILE,
        "size_bytes": size_bytes,
        "sha256": model_hash,
        "display_name": "Ae DeepSeek R1 Distill Qwen 1.5B IQ4_XS",
        "source_url": MODEL_SOURCE,
        "note": "Data-only offline model package. Import this ZIP from Ae; it is not an APK.",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    # GGUF is already quantized. Store it without another compression pass so
    # the ZIP can be imported with low CPU/memory overhead on Android.
    with zipfile.ZipFile(
        temporary_path,
        mode="w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True,
    ) as archive:
        archive.writestr(
            "ai-model.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            compress_type=zipfile.ZIP_STORED,
        )
        archive.write(model_path, arcname=MODEL_FILE, compress_type=zipfile.ZIP_STORED)

    with zipfile.ZipFile(temporary_path, mode="r") as archive:
        names = archive.namelist()
        if names != ["ai-model.json", MODEL_FILE]:
            raise SystemExit(f"Unexpected model package entries: {names!r}")
        parsed = json.loads(archive.read("ai-model.json").decode("utf-8"))
        if parsed != manifest:
            raise SystemExit("Model package manifest did not round-trip correctly.")
        bad_entry = archive.testzip()
        if bad_entry is not None:
            raise SystemExit(f"Model package CRC validation failed for {bad_entry}")

    os.replace(temporary_path, output_path)
    return {
        "package": str(output_path),
        "package_bytes": output_path.stat().st_size,
        "model_bytes": size_bytes,
        "sha256": model_hash,
        "entries": ["ai-model.json", MODEL_FILE],
        "is_apk": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL_FILE)
    parser.add_argument("--output", default=PACKAGE_FILE)
    args = parser.parse_args()
    result = build_package(Path(args.model), Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
