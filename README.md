# EffectCraft AI Build

Private, reproducible Android build workspace for **EffectCraft 0.21.1**.

## Repository layout

- `.github/workflows/`: Android APK build, account-service deployment, and source-import workflows.
- `.github/scripts/`: export dialog, project import/export, local AI, account integration, and Android WASM plug-in patches.
- `.github/native/`: Android native video-worker build files.
- `assets/ae-avatar.png`: supplied EffectCraft AI assistant avatar.
- `vendor/effectcraft/`: upstream EffectCraft 0.21.1 source (populated by the vendor workflow).
- `vendor/android-builder/`: upstream Android builder v0.5.0 source (populated by the vendor workflow).
- `vendor/native-deps/rife/`: pinned RIFE ncnn Vulkan source and initialized submodules.
- `vendor/native-deps/realesrgan/`: pinned Real-ESRGAN ncnn Vulkan source and initialized submodules.

## Complete source import

The workflow **Vendor complete EffectCraft source tree** imports these upstream revisions into the repository itself:

- EffectCraft: `storytold/effectcraft@v0.21.1`
- Android builder: `MostafaXS1/artcraft-android@v0.5.0`
- RIFE ncnn Vulkan: `nihui/rife-ncnn-vulkan@a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7`
- Real-ESRGAN ncnn Vulkan: `xinntao/Real-ESRGAN-ncnn-vulkan@37026f49824c5cf84062e7c6a5dd71445dcf610f`

Source import is started by changes to `SOURCE_VENDOR.lock` or manually from GitHub Actions. The vendor workflow commits the checked-out upstream files under `vendor/`; it preserves source and license files and removes only Git metadata.

## AI model assets

Large model weights are intentionally not stored in Git:
- DeepSeek R1 Distill Qwen 1.5B IQ4_XS GGUF
- RIFE 4.6 model files
- Real-ESRGAN x4 model files

The APK workflow downloads these pinned/identified model assets, verifies their sizes, and packages them into the APK. This keeps the source repository manageable while retaining a reproducible model-fetch step.

## Android build

The Android workflow targets EffectCraft 0.21.1 and applies the patches in `.github/scripts/` before compiling the arm64 APK. A successful Actions run publishes one standalone `.apk` file in the GitHub Release. Do not install files downloaded from the Actions **Artifacts** area: GitHub wraps those downloads in ZIP archives. A queued or running workflow is not a completed APK build.

## No-hosted-server account and node-network target

The requested product direction is **no Cloudflare Worker, no VPS, and no centrally hosted account server**. The main EffectCraft APK must retain registration/login and editing features; the separate admin APK owns ban/unban and the global node-network switch. The main APK must not show that global switch, and the admin APK must not become a node itself.

**Implementation status: not complete.** The current account-gate build patch still requires an HTTPS `.workers.dev` endpoint. The current node hub only tracks WebSocket presence and ping/pong, and Android NSD/mDNS discovery is limited to the same Wi-Fi. There is no completed signed account-event replication, anti-entropy synchronization, or cross-network peer transport. The existing cloud deployment workflow is legacy infrastructure and is not the requested no-server solution.

The no-server migration design is documented in:
- `docs/NO_SERVER_ACCOUNT_NODE_MESH_PLAN.md`
- `docs/SIGNED_ACCOUNT_EVENT_PROTOCOL_V1.md`

A no-server design has unavoidable limits: disconnected phones cannot receive an immediate ban, and direct peer connections cannot be guaranteed across every carrier NAT without a reachable bootstrap or relay service. Do not describe those capabilities as implemented until the protocol, Android transport, and acceptance tests are complete.

### Build safety

Do not bypass the account-service build gate with a fake URL or a UI-only account stub. Do not remove existing editor, project import/export, plugin, or AI video features to force a build. Any editor-only APK must be clearly labelled as such and must not claim working shared registration, bans, or global cross-network node networking.
