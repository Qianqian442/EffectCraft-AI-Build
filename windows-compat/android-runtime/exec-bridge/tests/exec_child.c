#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 3) return 31;
    if (strcmp(argv[0], "effectcraft-test-argv0") != 0) return 32;
    if (strcmp(argv[1], "alpha") != 0) return 33;
    if (strcmp(argv[2], "beta") != 0) return 34;
    puts("EFFECTCRAFT_EXEC_BRIDGE_CHILD_OK");
    return 0;
}
