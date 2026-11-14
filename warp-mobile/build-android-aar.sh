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
mkdir -p "$(dirname "$OUTPUT")"
cd "$WARP_DIR"
go mod download
gomobile bind -target=android/arm64 -androidapi=26 -javapkg=com.effectcraft.warp -o "$OUTPUT" .
test -s "$OUTPUT"
unzip -l "$OUTPUT" | grep -q 'jni/arm64-v8a/.*\.so'
unzip -l "$OUTPUT" | grep -q 'classes.jar'
sha256sum "$OUTPUT"
echo "Built EffectCraft task-scoped MASQUE Android AAR: $OUTPUT"
