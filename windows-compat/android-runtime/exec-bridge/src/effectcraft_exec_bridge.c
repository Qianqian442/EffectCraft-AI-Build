#define _GNU_SOURCE
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

extern char **environ;

#if defined(__aarch64__)
#define EC_NATIVE_ELF_MACHINE EM_AARCH64
#elif defined(__x86_64__)
#define EC_NATIVE_ELF_MACHINE EM_X86_64
#else
#define EC_NATIVE_ELF_MACHINE EM_NONE
#endif

#if defined(__aarch64__) || defined(__x86_64__)
#define EC_LINKER64_PATH "/system/bin/linker64"
#else
#define EC_LINKER64_PATH "/system/bin/linker"
#endif

static int ec_raw_execve(const char *path, char *const argv[], char *const envp[]) {
    return (int)syscall(SYS_execve, path, argv, envp);
}

static bool ec_path_is_under_root(const char *path, char **canonical_out) {
    const char *root = getenv("EFFECTCRAFT_RUNTIME_ROOT");
    if (!root || !*root || !path || !*path) return false;

    char *canonical_root = realpath(root, NULL);
    char *canonical_path = realpath(path, NULL);
    if (!canonical_root || !canonical_path) {
        free(canonical_root);
        free(canonical_path);
        return false;
    }

    size_t root_len = strlen(canonical_root);
    bool under = strncmp(canonical_path, canonical_root, root_len) == 0 &&
                 (canonical_path[root_len] == '/' || canonical_path[root_len] == '\0');
    free(canonical_root);

    if (!under) {
        free(canonical_path);
        return false;
    }
    *canonical_out = canonical_path;
    return true;
}

static bool ec_is_native_bionic_elf(const char *path) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return false;

    Elf64_Ehdr eh;
    ssize_t got = read(fd, &eh, sizeof(eh));
    if (got != (ssize_t)sizeof(eh) ||
        memcmp(eh.e_ident, ELFMAG, SELFMAG) != 0 ||
        eh.e_ident[EI_CLASS] != ELFCLASS64 ||
        eh.e_machine != EC_NATIVE_ELF_MACHINE ||
        eh.e_phentsize != sizeof(Elf64_Phdr) ||
        eh.e_phnum == 0 || eh.e_phnum > 256) {
        close(fd);
        return false;
    }

    bool has_android_interpreter = false;
    for (uint16_t i = 0; i < eh.e_phnum; ++i) {
        Elf64_Phdr ph;
        off_t off = (off_t)eh.e_phoff + (off_t)i * (off_t)eh.e_phentsize;
        if (pread(fd, &ph, sizeof(ph), off) != (ssize_t)sizeof(ph)) break;
        if (ph.p_type != PT_INTERP || ph.p_filesz == 0 || ph.p_filesz >= PATH_MAX) continue;

        char interp[PATH_MAX];
        if (pread(fd, interp, (size_t)ph.p_filesz, (off_t)ph.p_offset) != (ssize_t)ph.p_filesz) break;
        interp[PATH_MAX - 1] = '\0';
        has_android_interpreter = strcmp(interp, EC_LINKER64_PATH) == 0;
        break;
    }
    close(fd);

#ifdef EFFECTCRAFT_HOST_TEST
    (void)has_android_interpreter;
    return true;
#else
    return has_android_interpreter;
#endif
}

static int ec_execve_wrapped(const char *path, char *const argv[], char *const envp[]) {
    char *canonical = NULL;
    if (!ec_path_is_under_root(path, &canonical)) {
        return ec_raw_execve(path, argv, envp);
    }

    if (!ec_is_native_bionic_elf(canonical)) {
        free(canonical);
        return ec_raw_execve(path, argv, envp);
    }

    const char *linker = EC_LINKER64_PATH;
#ifdef EFFECTCRAFT_HOST_TEST
    const char *test_linker = getenv("EFFECTCRAFT_TEST_LINKER");
    if (test_linker && *test_linker) linker = test_linker;
#endif

    size_t argc = 0;
    if (argv) while (argv[argc] != NULL) ++argc;
    char **linker_argv = calloc(argc + 2, sizeof(char *));
    if (!linker_argv) {
        free(canonical);
        errno = ENOMEM;
        return -1;
    }

    linker_argv[0] = (argv && argv[0]) ? argv[0] : canonical;
    linker_argv[1] = canonical;
    for (size_t i = 1; i < argc; ++i) linker_argv[i + 1] = argv[i];

    int result = ec_raw_execve(linker, linker_argv, envp ? envp : environ);
    int saved_errno = errno;
    free(linker_argv);
    free(canonical);
    errno = saved_errno;
    return result;
}

__attribute__((visibility("default")))
int execve(const char *path, char *const argv[], char *const envp[]) {
    return ec_execve_wrapped(path, argv, envp);
}

static int ec_execvpe(const char *file, char *const argv[], char *const envp[]) {
    if (!file || !*file) {
        errno = ENOENT;
        return -1;
    }
    if (strchr(file, '/')) return ec_execve_wrapped(file, argv, envp);

    const char *path = getenv("PATH");
    if (!path) path = "/system/bin:/system/xbin";
    char *copy = strdup(path);
    if (!copy) {
        errno = ENOMEM;
        return -1;
    }

    bool saw_eacces = false;
    char *save = NULL;
    for (char *dir = strtok_r(copy, ":", &save); dir; dir = strtok_r(NULL, ":", &save)) {
        if (!*dir) dir = ".";
        size_t n = strlen(dir) + strlen(file) + 2;
        char *candidate = malloc(n);
        if (!candidate) {
            free(copy);
            errno = ENOMEM;
            return -1;
        }
        snprintf(candidate, n, "%s/%s", dir, file);
        ec_execve_wrapped(candidate, argv, envp);
        int e = errno;
        free(candidate);
        if (e == EACCES) saw_eacces = true;
        else if (e != ENOENT && e != ENOTDIR && e != ELOOP) {
            free(copy);
            errno = e;
            return -1;
        }
    }
    free(copy);
    errno = saw_eacces ? EACCES : ENOENT;
    return -1;
}

__attribute__((visibility("default")))
int execv(const char *path, char *const argv[]) {
    return ec_execve_wrapped(path, argv, environ);
}

__attribute__((visibility("default")))
int execvp(const char *file, char *const argv[]) {
    return ec_execvpe(file, argv, environ);
}

__attribute__((visibility("default")))
int execvpe(const char *file, char *const argv[], char *const envp[]) {
    return ec_execvpe(file, argv, envp);
}

static int ec_exec_list(const char *path, const char *arg, va_list ap, bool search_path, char *const envp[]) {
    size_t count = 1;
    va_list copy;
    va_copy(copy, ap);
    while (va_arg(copy, char *) != NULL) ++count;
    va_end(copy);

    char **argv = calloc(count + 1, sizeof(char *));
    if (!argv) {
        errno = ENOMEM;
        return -1;
    }
    argv[0] = (char *)arg;
    for (size_t i = 1; i < count; ++i) argv[i] = va_arg(ap, char *);
    (void)va_arg(ap, char *);
    int result = search_path ? ec_execvpe(path, argv, envp) : ec_execve_wrapped(path, argv, envp);
    int saved_errno = errno;
    free(argv);
    errno = saved_errno;
    return result;
}

__attribute__((visibility("default")))
int execl(const char *path, const char *arg, ...) {
    va_list ap;
    va_start(ap, arg);
    int result = ec_exec_list(path, arg, ap, false, environ);
    va_end(ap);
    return result;
}

__attribute__((visibility("default")))
int execlp(const char *file, const char *arg, ...) {
    va_list ap;
    va_start(ap, arg);
    int result = ec_exec_list(file, arg, ap, true, environ);
    va_end(ap);
    return result;
}

__attribute__((visibility("default")))
int execle(const char *path, const char *arg, ...) {
    va_list ap;
    va_start(ap, arg);
    size_t count = 1;
    va_list copy;
    va_copy(copy, ap);
    while (va_arg(copy, char *) != NULL) ++count;
    va_end(copy);

    char **argv = calloc(count + 1, sizeof(char *));
    if (!argv) {
        va_end(ap);
        errno = ENOMEM;
        return -1;
    }
    argv[0] = (char *)arg;
    for (size_t i = 1; i < count; ++i) argv[i] = va_arg(ap, char *);
    (void)va_arg(ap, char *);
    char *const *child_env = va_arg(ap, char *const *);
    int result = ec_execve_wrapped(path, argv, (char *const *)child_env);
    int saved_errno = errno;
    free(argv);
    va_end(ap);
    errno = saved_errno;
    return result;
}

__attribute__((visibility("default")))
int fexecve(int fd, char *const argv[], char *const envp[]) {
    char proc_path[64];
    snprintf(proc_path, sizeof(proc_path), "/proc/self/fd/%d", fd);
    char resolved[PATH_MAX];
    ssize_t n = readlink(proc_path, resolved, sizeof(resolved) - 1);
    if (n > 0) {
        resolved[n] = '\0';
        char *canonical = NULL;
        if (ec_path_is_under_root(resolved, &canonical)) {
            int result = ec_execve_wrapped(canonical, argv, envp);
            int saved_errno = errno;
            free(canonical);
            errno = saved_errno;
            return result;
        }
    }
#ifdef SYS_execveat
    return (int)syscall(SYS_execveat, fd, "", argv, envp ? envp : environ, AT_EMPTY_PATH);
#else
    errno = ENOSYS;
    return -1;
#endif
}
