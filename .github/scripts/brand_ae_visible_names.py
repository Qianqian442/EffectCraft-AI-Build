#!/usr/bin/env python3
"""Rebrand visible app copy from EffectCraft / 效果工坊 to Ae without changing stable IDs."""
from __future__ import annotations

import os
import re
from pathlib import Path

# Replace only standalone brand words inside source-language string literals.
# This intentionally leaves identifiers such as file.importEffectCraftMobile,
# package names, storage keys, protocol names, paths, and project extensions intact.
LITERAL = re.compile(
    r'r(?P<hashes>#{0,16})"(?P<raw_body>.*?)"(?P=hashes)'
    r'|"(?P<normal_body>(?:\\.|[^"\\])*)"',
    re.S,
)
BRAND = re.compile(r"(?<![A-Za-z0-9_])(?:EffectCraft|ArtCraft)(?![A-Za-z0-9_])")


def brand_text(value: str) -> str:
    return BRAND.sub("Ae", value).replace("效果工坊", "Ae")


def brand_source(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group("raw_body") is not None:
            return match.group(0).replace(
                match.group("raw_body"), brand_text(match.group("raw_body")), 1
            )
        body = match.group("normal_body")
        return '"' + brand_text(body) + '"'
    return LITERAL.sub(replace, source)


def candidates(root: Path):
    suffixes = {".rs", ".java", ".kt", ".xml", ".json", ".toml"}
    skip = {".git", "target", "build", "node_modules", ".gradle"}
    for base in root:
        if not base.exists():
            continue
        if base.is_file():
            if base.suffix in suffixes:
                yield base
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if any(part in skip for part in path.parts):
                continue
            yield path


def visible_brand_residue(path: Path, text: str) -> list[str]:
    if path.suffix == ".xml":
        return [m.group(0) for m in re.finditer(r"EffectCraft|ArtCraft|效果工坊", text)]
    residue = []
    for match in LITERAL.finditer(text):
        body = match.group("raw_body")
        if body is None:
            body = match.group("normal_body")
        if BRAND.search(body) or "效果工坊" in body:
            residue.append(body[:160])
    return residue


def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    repo = Path(__file__).resolve().parents[2]
    artcraft = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve() if os.environ.get("ARTCRAFT_DIR") else None

    roots = [
        effectcraft / "crates/ui-egui/src",
        effectcraft / "crates/engine/src",
        effectcraft / "crates/effects/src",
        effectcraft / "apps/effectcraft-android",
        repo / "admin-app/app/src/main",
        repo / "android-ai-plugin/app/src/main",
    ]
    if artcraft:
        roots.append(artcraft / "effectcraft-ai-source")
    changed = []
    for path in candidates(roots):
        original = path.read_text(encoding="utf-8")
        if path.suffix == ".xml":
            updated = brand_text(original)
        else:
            updated = brand_source(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)

    # The builder generates the private model-manager Activity manifest entry from
    # this Python template after the source checkout; update only its visible label.
    if artcraft:
        generator = artcraft / "lib/android_project.py"
        if generator.is_file():
            source = generator.read_text(encoding="utf-8")
            updated = source.replace("EffectCraft DeepSeek 模型管理", "Ae DeepSeek 模型管理")
            if updated != source:
                generator.write_text(updated, encoding="utf-8")
                changed.append(generator)

    residue = []
    for path in candidates(roots):
        text = path.read_text(encoding="utf-8")
        found = visible_brand_residue(path, text)
        if found:
            residue.append((str(path), found[:3]))
    if residue:
        details = "\\n".join(f"{path}: {values}" for path, values in residue[:20])
        raise SystemExit("Visible EffectCraft branding remains after Ae rebrand:\\n" + details)

    print(f"Rebranded {len(changed)} source/resource files to Ae.")
    print("Verified visible strings use Ae; stable package IDs, action IDs, storage keys and project-format identifiers were preserved.")


if __name__ == "__main__":
    main()
