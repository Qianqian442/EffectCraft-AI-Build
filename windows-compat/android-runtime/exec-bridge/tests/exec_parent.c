#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 3) return 40;
    char *child_argv[] = { "effectcraft-test-argv0", "alpha", "beta", NULL };
    char *child_envp[] = { "EFFECTCRAFT_TEST_ENV=from-parent", NULL };

    if (strcmp(argv[2], "execveat") == 0) {
        execveat(AT_FDCWD, argv[1], child_argv, child_envp, 0);
    } else if (strcmp(argv[2], "fexecve") == 0) {
        int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
        if (fd < 0) {
            fprintf(stderr, "open failed: %s\n", strerror(errno));
            return 42;
        }
        fexecve(fd, child_argv, child_envp);
    } else if (strcmp(argv[2], "execve") == 0) {
        execve(argv[1], child_argv, child_envp);
    } else {
        return 43;
    }

    fprintf(stderr, "%s failed: %s\n", argv[2], strerror(errno));
    return 41;
}
