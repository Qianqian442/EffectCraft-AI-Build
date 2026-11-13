#!/usr/bin/env python3
"""Patch Box64's glibc-specific 32-bit resolver-state bridge for Android Bionic.

Bionic intentionally keeps struct __res_state opaque.  Do not guess or copy
glibc's private resolver layout on Android.  Keep the guest's 32-bit state
buffer private to Box64 and let Bionic's res_query/res_search maintain its own
thread-local resolver state.
"""
from __future__ import annotations

import pathlib
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_box64_resolver_bionic.py <box64-source-root>")

source = pathlib.Path(sys.argv[1]) / "src/libtools/libc_net32.c"
text = source.read_text(encoding="utf-8")
start = text.find("typedef struct my_res_state_32_s")
end = text.find("void convert_ns_msg_to_32", start)
if start < 0 or end < 0:
    if "EFFECTCRAFT_BIONIC_RESOLVER_COMPAT" in text:
        print("Bionic resolver compatibility patch already applied")
        raise SystemExit(0)
    raise SystemExit("could not locate Box64 resolver-state compatibility block")

replacement = r'''#if defined(__BIONIC__)
/* Android Bionic does not expose glibc's struct __res_state fields.
 * Keep the 32-bit guest ABI storage opaque and delegate DNS operations to
 * Bionic, which manages its own resolver state internally. */
typedef struct my_res_state_32_s {
    unsigned char opaque_guest_state[512];
} my_res_state_32_t;

#define EFFECTCRAFT_BIONIC_RESOLVER_COMPAT 1

EXPORT void* my32___res_state(x64emu_t* emu)
{
    if (!emu->res_state_32)
        emu->res_state_32 = actual_calloc(1, sizeof(my_res_state_32_t));
    return emu->res_state_32;
}

EXPORT int my32_res_query(x64emu_t* emu, void* dname, int class, int type, void* answer, int anslen)
{
    int ret = res_query(dname, class, type, answer, anslen);
    emu->libc_herr = h_errno;
    return ret;
}

EXPORT int my32_res_search(x64emu_t* emu, void* dname, int class, int type, void* answer, int anslen)
{
    int ret = res_search(dname, class, type, answer, anslen);
    emu->libc_herr = h_errno;
    return ret;
}
#else
''' + text[start:end] + r'''#endif /* __BIONIC__ */

'''
text = text[:start] + replacement + text[end:]
source.write_text(text, encoding="utf-8")
print(f"Patched Bionic resolver-state bridge in {source}")
