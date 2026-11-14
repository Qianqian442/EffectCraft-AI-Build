#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WARP_DIR="$ROOT/warp-mobile"
UPSTREAM="$WARP_DIR/upstream-usque"
OUTPUT="${WARP_AAR_OUTPUT:-$WARP_DIR/build/effectcraft-warp-masque.aar}"
PINNED_USQUE_COMMIT="6aa03fc97d12848dce34eedbd187fb1077b5d1ea"

if [[ ! -d "$UPSTREAM/.git" ]]; then
  git clone --filter=blob:none https://github.com/Diniboy1123/usque.git "$UPSTREAM"
fi
git -C "$UPSTREAM" fetch --depth=1 origin "$PINNED_USQUE_COMMIT"
git -C "$UPSTREAM" checkout --detach "$PINNED_USQUE_COMMIT"
USQUE_SOURCE_DIR="$UPSTREAM" python3 "$ROOT/.github/scripts/patch_usque_for_android.py"
grep -Fq 'golang.org/x/mobile ' "$WARP_DIR/go.mod" || { echo "golang.org/x/mobile must be included in warp-mobile/go.mod" >&2; exit 1; }
grep -Fq 'tool golang.org/x/mobile/cmd/gobind' "$WARP_DIR/go.mod" || { echo "gobind must be declared as a go.mod tool dependency" >&2; exit 1; }
mkdir -p "$(dirname "$OUTPUT")"
cd "$WARP_DIR"
# Go 1.26's gomobile checks the generated gobind package as a declared tool.
# Run the official command so the active module graph is updated, then assert
# that the binding package is resolvable before starting the expensive bind.
go get -tool golang.org/x/mobile/cmd/gobind
go list golang.org/x/mobile/bind >/dev/null
go mod download
gomobile bind -target=android/arm64 -androidapi=26 -javapkg=com.effectcraft.warp -o "$OUTPUT" .
test -s "$OUTPUT"
unzip -l "$OUTPUT" | grep -q 'jni/arm64-v8a/.*\.so'
unzip -l "$OUTPUT" | grep -q 'classes.jar'
sha256sum "$OUTPUT"
echo "Built EffectCraft task-scoped MASQUE Android AAR: $OUTPUT"
