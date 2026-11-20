#!/usr/bin/env python3
"""Apply the minimum Android/Bionic compatibility changes to Box64 signal32.c.

Bionic exports si_tid as a macro in asm-generic/siginfo.h and defines
_NSIG_WORDS. Box64's emulated i386 signal-info layout also declares a member
named si_tid and its own guest word count, while __SI_SIGFAULT_ADDL is a
glibc-private extension absent from Bionic. Keep the patch under #ifdef
ANDROID so non-Android Box64 builds retain their upstream behavior.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "EFFECTCRAFT_BOX64_BIONIC_SIGNAL32_COMPAT"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("box64_source", type=Path)
    root = parser.parse_args().box64_source
    path = root / "src/libtools/signal32.c"
    if not path.is_file():
        raise SystemExit(f"Box64 signal32.c not found: {path}")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Box64 Bionic signal32 compatibility patch already applied.")
        return 0

    include_anchor = "#include <pthread.h>\n"
    include_patch = """#include <pthread.h>

/* EFFECTCRAFT_BOX64_BIONIC_SIGNAL32_COMPAT */
#ifdef ANDROID
/* Bionic asm-generic/siginfo.h defines si_tid as a field-access macro.
 * Box64 needs this spelling as a member name in its guest i386 siginfo ABI.
 */
#ifdef si_tid
#undef si_tid
#endif
/* This field macro is private to glibc headers; Bionic does not provide it. */
#ifndef __SI_SIGFAULT_ADDL
#define __SI_SIGFAULT_ADDL
#endif
#endif
"""
    source = replace_once(source, include_anchor, include_patch, "Bionic signal macro compatibility")

    old = "#define _NSIG_WORDS (64 / 32)"
    new = """#ifndef _NSIG_WORDS
#define _NSIG_WORDS (64 / 32)
#endif"""
    source = replace_once(source, old, new, "guest i386 signal word count")

    path.write_text(source, encoding="utf-8")
    print("Applied Android-only Bionic signal32 macro compatibility.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
