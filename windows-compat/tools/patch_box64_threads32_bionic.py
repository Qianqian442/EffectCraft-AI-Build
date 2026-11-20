#!/usr/bin/env python3
"""Replace glibc-private pthread introspection in Box64 BOX32 only on Android."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("box64_source", type=Path)
    root = parser.parse_args().box64_source
    path = root / "src/libtools/threads32.c"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_BOX64_BIONIC_THREADS32_COMPAT"
    if marker in source:
        print("Box64 Bionic threads32 patch already applied.")
        return 0

    old_stack = """            pthread_attr_t attr;
            pthread_getattr_default_np(&attr);
            pthread_attr_getstacksize(&attr, &sz);
            pthread_attr_destroy(&attr);"""
    new_stack = """            pthread_attr_t attr;
#ifdef ANDROID
            /* Bionic does not expose glibc's pthread_getattr_default_np().
             * pthread_attr_init supplies the process default stack attributes.
             */
            pthread_attr_init(&attr);
#else
            pthread_getattr_default_np(&attr);
#endif
            pthread_attr_getstacksize(&attr, &sz);
            pthread_attr_destroy(&attr);"""
    source = replace_once(source, old_stack, new_stack, "default pthread stack size")

    old_mutex = """    fake->i386__kind = ((struct __pthread_mutex_s*)from_ptrv(fake->real_mutex))->__kind;"""
    new_mutex = """#ifdef ANDROID
    /* Bionic does not expose glibc's private struct __pthread_mutex_s.
     * Preserve the requested POSIX mutex type through the public attr API.
     */
    fake->i386__kind = PTHREAD_MUTEX_NORMAL;
    if (att) pthread_mutexattr_gettype(att, &fake->i386__kind);
#else
    fake->i386__kind = ((struct __pthread_mutex_s*)from_ptrv(fake->real_mutex))->__kind;
#endif"""
    source = replace_once(source, old_mutex, new_mutex, "glibc private mutex kind")
    source = source.replace(
        "// SPDX-License-Identifier: MIT\n",
        "// SPDX-License-Identifier: MIT\n/* " + marker + " */\n",
        1,
    )
    path.write_text(source, encoding="utf-8")
    print("Applied Android-only pthread stack and mutex introspection compatibility.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
