#!/usr/bin/env python3
"""List likely untranslated, direct UI literals and engine messages for manual zh-Hans review.

This is a candidate scanner, not a translator and not a proof of complete coverage:
cataloged strings are checked by EffectCraft's own missing_translations_report test.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOTS = (Path("crates/ui-egui/src"), Path("crates/engine/src"))
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("direct-ui", re.compile(
        r'\b(?:ui|menu_ui|sub_ui)\.(?:label|small|heading|button|hyperlink|checkbox|radio|selectable_label)\s*\([^ )]*?"((?:\\.|[^"\\])*)"',
        re.DOTALL,
    )),
    ("window-or-widget-title", re.compile(
        r'\b(?:egui::)?(?:Window|CollapsingHeader|ComboBox)::(?:new|from_label)\s*\(\s*"((?:\\.|[^"\\])*)"',
    )),
    ("engine-bad-error", re.compile(
        r'\bbad\s*\([^,\n]+,\s*(?:format!\s*\(\s*)?"((?:\\.|[^"\\])*)"',
        re.DOTALL,
    )),
    ("engine-error-other", re.compile(
        r'\bEngineError::Other\s*\(\s*(?:format!\s*\(\s*)?"((?:\\.|[^"\\])*)"',
        re.DOTALL,
    )),
    ("engine-err-literal", re.compile(
        r'\bErr\s*\(\s*"((?:\\.|[^"\\])*)"\s*\)',
    )),
    ("toast-or-status", re.compile(
        r'\b(?:s|session|app)\.(?:toast|ui\.status)\s*(?:=\s*|\()\s*(?:format!\s*\(\s*)?"((?:\\.|[^"\\])*)"',
        re.DOTALL,
    )),
)

def clean_literal(value: str) -> str:
    return value.replace(r"\n", " ").replace(r"\t", " ").replace(r"\"", '"').strip()

def main() -> None:
    candidates: set[tuple[str, str, int, str]] = set()
    scanned = 0
    for root in ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.rs"):
            if "i18n" in path.parts or path.name.startswith("i18n"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            relative = path.as_posix()
            for kind, pattern in PATTERNS:
                for match in pattern.finditer(source):
                    literal = clean_literal(match.group(1))
                    if not literal or not re.search(r"[A-Za-z]", literal):
                        continue
                    # Ignore literals already passed through the translation helper.
                    call_prefix = source[match.start():match.start(1)]
                    if re.search(r"\btr(?:_args)?\s*\(", call_prefix):
                        continue
                    prefix = source[:match.start()]
                    line = prefix.count("\n") + 1
                    line_text = source.splitlines()[line - 1].strip() if source.splitlines() else ""
                    if line_text.startswith("//") or line_text.startswith("*"):
                        continue
                    candidates.add((kind, relative, line, literal))

    print(f"Rust source files scanned: {scanned}")
    print(f"Uncatalogued English-literal candidates for manual review: {len(candidates)}")
    print("These are candidate strings, not all proven missing: verify context before translating.")
    for kind, path, line, literal in sorted(candidates):
        print(f"{kind}\t{path}:{line}\t{literal}")

if __name__ == "__main__":
    main()
