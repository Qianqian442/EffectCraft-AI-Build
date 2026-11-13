#!/usr/bin/env python3
"""Add the missing Bionic netdb *_r compatibility used by Box64 BOX32.

Bionic provides the non-reentrant getservbyname/getprotobyname/
getprotobynumber functions but not the glibc *_r entry points in this pinned
Box64 revision. The adapters copy results immediately into the caller's
scratch buffer and serialize access to Bionic's static database results.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "EFFECTCRAFT_BOX64_BIONIC_NETDB_R_COMPAT"

COMPAT = r"""
#if defined(__BIONIC__)
/* EFFECTCRAFT_BOX64_BIONIC_NETDB_R_COMPAT
 * Bionic omits these glibc/POSIX re-entrant netdb entry points. Keep the
 * adaptation local to Box64's 32-bit guest bridge; never inspect libc-private
 * resolver structures. Bionic returns static records, so copy them while
 * holding a mutex before another lookup can replace them.
 */
static pthread_mutex_t effectcraft_netdb_mutex = PTHREAD_MUTEX_INITIALIZER;

static int effectcraft_netdb_copy_string(const char *src, char **dst,
                                         char **cursor, size_t *remaining)
{
    if (!src) {
        *dst = NULL;
        return 0;
    }
    size_t n = strlen(src) + 1;
    if (n > *remaining)
        return ERANGE;
    memcpy(*cursor, src, n);
    *dst = *cursor;
    *cursor += n;
    *remaining -= n;
    return 0;
}

static int effectcraft_netdb_prepare_buffer(char *buffer, size_t buflen,
                                            char **cursor, size_t *remaining)
{
    uintptr_t misalignment;
    size_t padding;
    if (!buffer)
        return EINVAL;
    misalignment = (uintptr_t)buffer % _Alignof(char *);
    padding = misalignment ? (_Alignof(char *) - misalignment) : 0;
    if (padding > buflen)
        return ERANGE;
    *cursor = buffer + padding;
    *remaining = buflen - padding;
    return 0;
}

static int effectcraft_netdb_copy_aliases(char *const *source, char ***target,
                                          char **cursor, size_t *remaining)
{
    size_t count = 0;
    size_t bytes;
    char **aliases;
    if (!source) {
        *target = NULL;
        return 0;
    }
    while (source[count])
        ++count;
    bytes = (count + 1) * sizeof(char *);
    if (bytes > *remaining)
        return ERANGE;
    aliases = (char **)*cursor;
    *cursor += bytes;
    *remaining -= bytes;
    for (size_t i = 0; i < count; ++i) {
        int rc = effectcraft_netdb_copy_string(source[i], &aliases[i],
                                               cursor, remaining);
        if (rc)
            return rc;
    }
    aliases[count] = NULL;
    *target = aliases;
    return 0;
}

static int getservbyname_r(const char *name, const char *proto,
                           struct servent *result_buf, char *buffer,
                           size_t buflen, struct servent **result)
{
    struct servent *source;
    char *cursor;
    size_t remaining;
    int rc;
    if (!result)
        return EINVAL;
    *result = NULL;
    if (!name || !result_buf || !buffer)
        return EINVAL;
    rc = effectcraft_netdb_prepare_buffer(buffer, buflen, &cursor, &remaining);
    if (rc)
        return rc;
    pthread_mutex_lock(&effectcraft_netdb_mutex);
    source = getservbyname(name, proto);
    if (!source) {
        pthread_mutex_unlock(&effectcraft_netdb_mutex);
        return 0;
    }
    rc = effectcraft_netdb_copy_aliases(source->s_aliases,
                                        &result_buf->s_aliases,
                                        &cursor, &remaining);
    if (!rc)
        rc = effectcraft_netdb_copy_string(source->s_name,
                                           &result_buf->s_name,
                                           &cursor, &remaining);
    if (!rc)
        rc = effectcraft_netdb_copy_string(source->s_proto,
                                           &result_buf->s_proto,
                                           &cursor, &remaining);
    if (!rc) {
        result_buf->s_port = source->s_port;
        *result = result_buf;
    }
    pthread_mutex_unlock(&effectcraft_netdb_mutex);
    return rc;
}

static int getprotobyname_r(const char *name, struct protoent *result_buf,
                            char *buffer, size_t buflen,
                            struct protoent **result)
{
    struct protoent *source;
    char *cursor;
    size_t remaining;
    int rc;
    if (!result)
        return EINVAL;
    *result = NULL;
    if (!name || !result_buf || !buffer)
        return EINVAL;
    rc = effectcraft_netdb_prepare_buffer(buffer, buflen, &cursor, &remaining);
    if (rc)
        return rc;
    pthread_mutex_lock(&effectcraft_netdb_mutex);
    source = getprotobyname(name);
    if (!source) {
        pthread_mutex_unlock(&effectcraft_netdb_mutex);
        return 0;
    }
    rc = effectcraft_netdb_copy_aliases(source->p_aliases,
                                        &result_buf->p_aliases,
                                        &cursor, &remaining);
    if (!rc)
        rc = effectcraft_netdb_copy_string(source->p_name,
                                           &result_buf->p_name,
                                           &cursor, &remaining);
    if (!rc) {
        result_buf->p_proto = source->p_proto;
        *result = result_buf;
    }
    pthread_mutex_unlock(&effectcraft_netdb_mutex);
    return rc;
}

static int getprotobynumber_r(int proto, struct protoent *result_buf,
                              char *buffer, size_t buflen,
                              struct protoent **result)
{
    struct protoent *source;
    char *cursor;
    size_t remaining;
    int rc;
    if (!result)
        return EINVAL;
    *result = NULL;
    if (!result_buf || !buffer)
        return EINVAL;
    rc = effectcraft_netdb_prepare_buffer(buffer, buflen, &cursor, &remaining);
    if (rc)
        return rc;
    pthread_mutex_lock(&effectcraft_netdb_mutex);
    source = getprotobynumber(proto);
    if (!source) {
        pthread_mutex_unlock(&effectcraft_netdb_mutex);
        return 0;
    }
    rc = effectcraft_netdb_copy_aliases(source->p_aliases,
                                        &result_buf->p_aliases,
                                        &cursor, &remaining);
    if (!rc)
        rc = effectcraft_netdb_copy_string(source->p_name,
                                           &result_buf->p_name,
                                           &cursor, &remaining);
    if (!rc) {
        result_buf->p_proto = source->p_proto;
        *result = result_buf;
    }
    pthread_mutex_unlock(&effectcraft_netdb_mutex);
    return rc;
}
#endif /* __BIONIC__ */

"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("box64_source", type=Path)
    root = parser.parse_args().box64_source
    path = root / "src/libtools/libc_net32.c"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Bionic netdb *_r compatibility patch already applied.")
        return 0

    include_anchor = "#include <netdb.h>\n"
    if source.count(include_anchor) != 1:
        raise SystemExit("expected exactly one netdb.h include")
    source = source.replace(
        include_anchor,
        include_anchor + "#include <pthread.h>\n",
        1,
    )

    function_anchor = "EXPORT int my32_getservbyname_r("
    if source.count(function_anchor) != 1:
        raise SystemExit("expected exactly one my32_getservbyname_r insertion point")
    source = source.replace(function_anchor, COMPAT + "\n" + function_anchor, 1)
    path.write_text(source, encoding="utf-8")
    print("Applied Bionic getservbyname_r/getprotobyname_r/getprotobynumber_r adapters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
