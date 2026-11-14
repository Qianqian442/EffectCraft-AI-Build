#define _GNU_SOURCE
#include <errno.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <unistd.h>

extern char **environ;

int main(int argc, char **argv) {
    if (argc < 2) return 120;
    char **target_argv = calloc((size_t)argc, sizeof(char *));
    if (!target_argv) return 121;
    target_argv[0] = argv[0];
    for (int i = 2; i < argc; ++i) target_argv[i - 1] = argv[i];
    syscall(SYS_execve, argv[1], target_argv, environ);
    return errno ? errno : 122;
}
