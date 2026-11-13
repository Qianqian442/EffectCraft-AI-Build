#!/usr/bin/env python3
"""Split Box64 BOX32 allocator entry points into a Bionic-specific source file.

The Android BOX32 link reached the final linker but did not expose the
box32_* allocator symbols from mallochook.c. Keep upstream's allocator block
for non-Bionic builds and provide Android with direct custom 32-bit allocator
wrappers. These wrappers always allocate from Box64's below-4-GiB custom
allocator, which is the correct address domain for the 32-bit guest.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "EFFECTCRAFT_BOX64_BIONIC_BOX32_ALLOC_V1"

ALLOC_SOURCE = r'''/* SPDX-License-Identifier: MIT */
/* EffectCraft Android/Bionic BOX32 allocator bridge. */
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "custommem.h"

void* box32_calloc(size_t n, size_t size)
{
    if (size && n > SIZE_MAX / size)
        return NULL;
    return customCalloc32(n, size);
}

void* box32_malloc(size_t size)
{
    return customMalloc32(size);
}

void* box32_realloc(void* p, size_t size)
{
    return customRealloc32(p, size);
}

void box32_free(void* p)
{
    if (p)
        customFree32(p);
}

void* box32_memalign(size_t align, size_t size)
{
    return customMemAligned32(align, size);
}

size_t box32_malloc_usable_size(void* p)
{
    return p ? customGetUsableSize(p) : 0;
}

char* box32_strdup(const char* s)
{
    if (!s)
        return NULL;
    size_t size = strlen(s) + 1;
    char* ret = box32_malloc(size);
    if (ret)
        memcpy(ret, s, size);
    return ret;
}
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("box64_source", type=Path)
    root = parser.parse_args().box64_source

    mallochook = root / "src/mallochook.c"
    source = mallochook.read_text(encoding="utf-8")
    marker_comment = "/* " + MARKER + " */"
    old_guard = "#ifdef BOX32\nint isCustomAddr(void* p);"
    new_guard = "#if defined(BOX32) && !defined(__BIONIC__)\nint isCustomAddr(void* p);"
    if marker_comment not in source:
        source = replace_once(source, old_guard, marker_comment + "\n" + new_guard,
                              "upstream BOX32 allocator guard")
        mallochook.write_text(source, encoding="utf-8")

    alloc_path = root / "src/libtools/box32_alloc_bionic.c"
    if alloc_path.exists():
        if alloc_path.read_text(encoding="utf-8") != ALLOC_SOURCE:
            raise SystemExit(f"refusing to overwrite unexpected file: {alloc_path}")
    else:
        alloc_path.write_text(ALLOC_SOURCE, encoding="utf-8")

    cmake_path = root / "CMakeLists.txt"
    cmake = cmake_path.read_text(encoding="utf-8")
    cmake_marker = "# " + MARKER
    if cmake_marker not in cmake:
        anchor = "if(BOX32)\n    list(APPEND ELFLOADER_SRC\n"
        replacement = (
            "# " + MARKER + "\n"
            "if(BOX32 AND ANDROID)\n"
            "    list(APPEND ELFLOADER_SRC \"${BOX64_ROOT}/src/libtools/box32_alloc_bionic.c\")\n"
            "endif()\n"
            + anchor
        )
        cmake = replace_once(cmake, anchor, replacement, "BOX32 ELFLOADER source list")
        cmake_path.write_text(cmake, encoding="utf-8")

    print("Installed the Android Bionic BOX32 allocator bridge and disabled the upstream duplicate block on Bionic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
