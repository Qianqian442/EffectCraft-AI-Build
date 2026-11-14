#!/usr/bin/env python3
"""Provide the small *_r netdb APIs missing from Android Bionic for Box64 BOX32.

Box64's 32-bit wrapper immediately converts the temporary host result into its
32-bit guest representation.  The Bionic shims therefore use per-host-thread
scratch storage for the duration of that conversion instead of pretending
Bionic exports glibc's reentrant netdb symbols.
"""
from __future__ import annotations

import pathlib
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_box64_netdb_bionic.py <box64-source-root>")

source = pathlib.Path(sys.argv[1]) / "src/libtools/libc_net32.c"
text = source.read_text(encoding="utf-8")
marker = "/* EFFECTCRAFT_BIONIC_NETDB_COMPAT */"
if marker in text:
    print("Bionic netdb compatibility shims already applied")
    raise SystemExit(0)

anchor = '#include "custommem.h"'
if anchor not in text:
    raise SystemExit("could not locate libc_net32.c include anchor")

shim = r'''

#if defined(__BIONIC__)
/* EFFECTCRAFT_BIONIC_NETDB_COMPAT
 * These are private Box64 host-side shims, not public libc replacements.
 * my32_* callers below convert the temporary result into guest memory before
 * returning to the emulated process.  Per-thread storage avoids races between
 * simultaneous Box64 guest threads while preserving the *_r call shape.
 */
static __thread char effectcraft_netdb_storage[16384];
static __thread size_t effectcraft_netdb_used;
static __thread char* effectcraft_netdb_aliases[128];

static void effectcraft_netdb_reset(void)
{
    effectcraft_netdb_used = 0;
    memset(effectcraft_netdb_aliases, 0, sizeof(effectcraft_netdb_aliases));
}

static char* effectcraft_netdb_copy(const char* value)
{
    if (!value)
        return NULL;
    size_t n = strlen(value) + 1;
    if (n > sizeof(effectcraft_netdb_storage) - effectcraft_netdb_used)
        return NULL;
    char* out = effectcraft_netdb_storage + effectcraft_netdb_used;
    memcpy(out, value, n);
    effectcraft_netdb_used += n;
    return out;
}

static int effectcraft_netdb_copy_aliases(char* const* source, char*** target)
{
    size_t i = 0;
    if (source) {
        while (source[i]) {
            if (i >= (sizeof(effectcraft_netdb_aliases) / sizeof(effectcraft_netdb_aliases[0])) - 1)
                return ERANGE;
            effectcraft_netdb_aliases[i] = effectcraft_netdb_copy(source[i]);
            if (!effectcraft_netdb_aliases[i])
                return ERANGE;
            ++i;
        }
    }
    effectcraft_netdb_aliases[i] = NULL;
    *target = effectcraft_netdb_aliases;
    return 0;
}

static int getservbyname_r(const char* name, const char* proto,
                           struct servent* result_buf, char* buf,
                           size_t buflen, struct servent** result)
{
    (void)buf;
    (void)buflen;
    if (!result || !result_buf)
        return EINVAL;
    *result = NULL;
    effectcraft_netdb_reset();
    struct servent* source = getservbyname(name, proto);
    if (!source)
        return 0;
    result_buf->s_name = effectcraft_netdb_copy(source->s_name);
    result_buf->s_proto = effectcraft_netdb_copy(source->s_proto);
    result_buf->s_port = source->s_port;
    if (!result_buf->s_name || !result_buf->s_proto)
        return ERANGE;
    int rc = effectcraft_netdb_copy_aliases(source->s_aliases, &result_buf->s_aliases);
    if (rc)
        return rc;
    *result = result_buf;
    return 0;
}

static int getprotobyname_r(const char* name, struct protoent* result_buf,
                            char* buf, size_t buflen, struct protoent** result)
{
    (void)buf;
    (void)buflen;
    if (!result || !result_buf)
        return EINVAL;
    *result = NULL;
    effectcraft_netdb_reset();
    struct protoent* source = getprotobyname(name);
    if (!source)
        return 0;
    result_buf->p_name = effectcraft_netdb_copy(source->p_name);
    result_buf->p_proto = source->p_proto;
    if (!result_buf->p_name)
        return ERANGE;
    int rc = effectcraft_netdb_copy_aliases(source->p_aliases, &result_buf->p_aliases);
    if (rc)
        return rc;
    *result = result_buf;
    return 0;
}

static int getprotobynumber_r(int proto, struct protoent* result_buf,
                              char* buf, size_t buflen, struct protoent** result)
{
    (void)buf;
    (void)buflen;
    if (!result || !result_buf)
        return EINVAL;
    *result = NULL;
    effectcraft_netdb_reset();
    struct protoent* source = getprotobynumber(proto);
    if (!source)
        return 0;
    result_buf->p_name = effectcraft_netdb_copy(source->p_name);
    result_buf->p_proto = source->p_proto;
    if (!result_buf->p_name)
        return ERANGE;
    int rc = effectcraft_netdb_copy_aliases(source->p_aliases, &result_buf->p_aliases);
    if (rc)
        return rc;
    *result = result_buf;
    return 0;
}
#endif /* __BIONIC__ */
'''
text = text.replace(anchor, anchor + shim)
source.write_text(text, encoding="utf-8")
print(f"Patched Bionic netdb reentrant API gaps in {source}")
