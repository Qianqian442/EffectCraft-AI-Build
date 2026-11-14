#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

extern char **environ;

int main(int argc, char **argv) {
    if (argc != 2) return 40;
    char *child_argv[] = { "effectcraft-test-argv0", "alpha", "beta", NULL };
    execve(argv[1], child_argv, environ);
    fprintf(stderr, "execve failed: %s\n", strerror(errno));
    return 41;
}
