#!/usr/bin/env python3
"""Provide the minimal GNU obstack ABI declarations needed by Box64 BOX32.

Android's Bionic NDK does not ship the GNU obstack header. Box64's
myalign32.c only inspects/rewrites the layout of struct obstack and
struct _obstack_chunk; it does not call obstack allocation functions.
This header is scoped to the Box64 build tree and does not add an allocator.
"""
from __future__ import annotations

import argparse
from pathlib import Path

HEADER = r"""/* EffectCraft BOX32 build-only compatibility declaration.
 * Layout follows the public GNU obstack ABI fields used by Box64 myalign32.c.
 * No GNU obstack implementation or allocation functions are provided.
 */
#ifndef EFFECTCRAFT_BOX64_OBSTACK_ABI_COMPAT_H
#define EFFECTCRAFT_BOX64_OBSTACK_ABI_COMPAT_H
#include <stddef.h>

struct _obstack_chunk {
    char *limit;
    struct _obstack_chunk *prev;
    char contents[4];
};

struct obstack {
    long chunk_size;
    struct _obstack_chunk *chunk;
    char *object_base;
    char *next_free;
    char *chunk_limit;
    union {
        ptrdiff_t tempint;
        void *tempptr;
    } temp;
    int alignment_mask;
    struct _obstack_chunk *(*chunkfun)(void *, long);
    void (*freefun)(void *, struct _obstack_chunk *);
    void *extra_arg;
    unsigned int use_extra_arg : 1;
    unsigned int maybe_empty_object : 1;
    unsigned int alloc_failed : 1;
};
#endif
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("box64_source", type=Path)
    root = parser.parse_args().box64_source
    source = root / "src/libtools/myalign32.c"
    include_dir = root / "src/include"
    if not source.is_file():
        raise SystemExit(f"Box64 source file not found: {source}")
    include_dir.mkdir(parents=True, exist_ok=True)

    text = source.read_text(encoding="utf-8")
    old = "#include <obstack.h>"
    new = '#include "box64_obstack_compat.h"'
    if text.count(new) == 1:
        print("Box64 BOX32 obstack compatibility patch already applied.")
    elif text.count(old) == 1:
        source.write_text(text.replace(old, new, 1), encoding="utf-8")
    else:
        raise SystemExit("expected one obstack include in src/libtools/myalign32.c")

    header = include_dir / "box64_obstack_compat.h"
    if header.exists() and header.read_text(encoding="utf-8") != HEADER:
        raise SystemExit(f"refusing to overwrite unexpected file: {header}")
    header.write_text(HEADER, encoding="utf-8")
    print(f"Installed build-only Box64 obstack ABI declarations: {header}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
