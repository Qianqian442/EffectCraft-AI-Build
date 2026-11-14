#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 3) return 31;
    if (strcmp(argv[0], "effectcraft-test-argv0") != 0) return 32;
    if (strcmp(argv[1], "alpha") != 0) return 33;
    if (strcmp(argv[2], "beta") != 0) return 34;
    const char *root = getenv("EFFECTCRAFT_RUNTIME_ROOT");
    const char *preload = getenv("LD_PRELOAD");
    const char *marker = getenv("EFFECTCRAFT_TEST_ENV");
    if (!root || !*root) return 35;
    if (!preload || !strstr(preload, "libeffectcraft-exec.so")) return 36;
    if (!marker || strcmp(marker, "from-parent") != 0) return 37;
    puts("EFFECTCRAFT_EXEC_BRIDGE_CHILD_OK");
    return 0;
}
