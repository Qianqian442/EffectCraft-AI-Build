#!/usr/bin/env python3
"""Adapt Box64's BOX32 posix_spawn_file_actions bridge to Android Bionic.

glibc exposes posix_spawn_file_actions_t as a struct; Bionic exposes it as an
opaque pointer handle. The 32-bit guest structure keeps the native handle in
its pointer field through Box64's pointer translation map. Non-Android builds
retain Box64's original glibc field-copy implementation unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "EFFECTCRAFT_BOX64_BIONIC_POSIX_SPAWN_ACTIONS_COMPAT"

NEW_BLOCK = r"""
#ifdef ANDROID
/* Bionic typedefs posix_spawn_file_actions_t as an opaque pointer. The guest
 * i386 structure cannot mirror the host private layout: store only a mapped
 * handle in __actions and leave glibc bookkeeping fields zeroed.
 */
void convert_file_action_to_32(void* d, void* s)
{
    posix_spawn_file_actions_32_t* dst = d;
    posix_spawn_file_actions_t* src = s;
    memset(dst, 0, sizeof(*dst));
    dst->__actions = to_ptrv(*src);
}

void convert_file_action_to_64(void* d, void* s)
{
    posix_spawn_file_actions_t* dst = d;
    posix_spawn_file_actions_32_t* src = s;
    *dst = (posix_spawn_file_actions_t)from_ptrv(src->__actions);
}
#else
void convert_file_action_to_32(void* d, void* s)
{
    posix_spawn_file_actions_32_t* dst = d;
    posix_spawn_file_actions_t* src = s;
    dst->__allocated = src->__allocated;
    dst->__used = src->__used;
    dst->__actions = to_ptrv(src->__actions);
}
void convert_file_action_to_64(void* d, void* s)
{
    posix_spawn_file_actions_t* dst = d;
    posix_spawn_file_actions_32_t* src = s;
    dst->__actions = from_ptrv(src->__actions);
    dst->__used = src->__used;
    dst->__allocated = src->__allocated;
}
#endif
"""

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("box64_source", type=Path)
    root = parser.parse_args().box64_source
    path = root / "src/wrapped32/wrappedlibc.c"
    source = path.read_text(encoding="utf-8")

    if MARKER in source:
        print("Bionic posix_spawn_file_actions compatibility patch already applied.")
        return 0

    start = source.find("void convert_file_action_to_32(void* d, void* s)")
    end = source.find("\nEXPORT int my32_posix_spawn_file_actions_init", start)
    if start < 0 or end < 0:
        raise SystemExit("could not locate Box64 posix_spawn_file_actions conversion helpers")

    source = source[:start] + "/* " + MARKER + " */\n" + NEW_BLOCK + source[end:]

    old_destroy = """EXPORT int my32_posix_spawn_file_actions_destroy(x64emu_t* emu, posix_spawn_file_actions_32_t* action)
{
    posix_spawn_file_actions_t action_l;
    convert_file_action_to_64(&action_l, action);
    int ret = posix_spawn_file_actions_destroy(&action_l);
    convert_file_action_to_32(action, &action_l);   // just in case?
    return ret;
}
"""
    new_destroy = """EXPORT int my32_posix_spawn_file_actions_destroy(x64emu_t* emu, posix_spawn_file_actions_32_t* action)
{
    posix_spawn_file_actions_t action_l;
    convert_file_action_to_64(&action_l, action);
    int ret = posix_spawn_file_actions_destroy(&action_l);
#ifdef ANDROID
    if (ret == 0)
        memset(action, 0, sizeof(*action));
#else
    convert_file_action_to_32(action, &action_l);   // preserve upstream glibc behavior
#endif
    return ret;
}
"""
    if source.count(old_destroy) != 1:
        raise SystemExit("could not uniquely locate posix_spawn_file_actions_destroy wrapper")
    source = source.replace(old_destroy, new_destroy, 1)
    path.write_text(source, encoding="utf-8")
    print("Applied Bionic opaque posix_spawn_file_actions handle bridge.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
