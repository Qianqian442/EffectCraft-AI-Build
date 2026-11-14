#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/build-host-test"
mkdir -p "$WORK/runtime" "$WORK/bin"
CC=cc
CFLAGS="-O2 -g -Wall -Wextra -Werror -fPIE"

"$CC" $CFLAGS "$ROOT/exec_child.c" -pie -o "$WORK/runtime/exec-child"
"$CC" $CFLAGS "$ROOT/linker_stub.c" -pie -o "$WORK/linker-stub"
"$CC" $CFLAGS "$ROOT/exec_parent.c" -pie -o "$WORK/exec-parent"
"$CC" -shared -fPIC -O2 -g -Wall -Wextra -Werror -DEFFECTCRAFT_HOST_TEST \
  "$ROOT/../src/effectcraft_exec_bridge.c" -o "$WORK/libeffectcraft-exec.so"

OUT="$(EFFECTCRAFT_RUNTIME_ROOT="$WORK/runtime" EFFECTCRAFT_TEST_LINKER="$WORK/linker-stub" \
  LD_PRELOAD="$WORK/libeffectcraft-exec.so" "$WORK/exec-parent" "$WORK/runtime/exec-child")"
grep -Fq "EFFECTCRAFT_EXEC_BRIDGE_CHILD_OK" <<<"$OUT"
echo "EffectCraft exec bridge host test passed: private native ELF routed through linker shim; argv preserved."

env -u LD_PRELOAD "$WORK/exec-parent" /bin/true >/dev/null 2>&1
echo "EffectCraft exec bridge host tests completed."
