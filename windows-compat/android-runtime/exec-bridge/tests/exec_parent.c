#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 2) return 40;
    char *child_argv[] = { "effectcraft-test-argv0", "alpha", "beta", NULL };
    char *child_envp[] = { "EFFECTCRAFT_TEST_ENV=from-parent", NULL };
    execve(argv[1], child_argv, child_envp);
    fprintf(stderr, "execve failed: %s\n", strerror(errno));
    return 41;
}
