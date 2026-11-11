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

## Account server scope and device-to-device compute

The Cloudflare HTTPS account service remains enabled only for functions that require shared authority and synchronization:
- registration, login, and account verification;
- administrator account lookup, ban/unban, ban reasons and expiry;
- live account-status notifications and node-network control/presence.

The main EffectCraft APK keeps the editor and its existing local functions. AI frame interpolation (RIFE), AI quality enhancement (Real-ESRGAN), project import/export, WASM plug-ins, and desktop-AE plug-in inspection/import must not be made dependent on the account server or removed to make the build pass. The DeepSeek local model remains an optional separate plug-in and is not bundled into the main APK.

The separate admin APK remains the only place for administrator controls. The main APK does not expose the global node-network switch. The admin APK is not a worker node.

The account client is built against the repository variable `AE_ACCOUNT_API_URL`, which must be the deployed HTTPS Cloudflare Worker URL ending in `.workers.dev`. The main APK build intentionally fails if this variable is missing or invalid; it must not silently fall back to the temporary home-Wi-Fi server. The admin APK receives the same URL at build time.

Device-to-device compute is a separate capability from the account server: the server must not be used to render users' video or host their AI models. Distributed phone compute is not yet considered complete until task scheduling, opt-in worker participation, result validation, retry, and cross-network transport are implemented and tested. Do not claim that hundreds of phones are already pooled into one compute cluster.

### Build safety

Do not bypass account-service validation with a fake URL or a UI-only account stub. Do not remove existing editor, project import/export, plug-in, or AI video features to force a build. A successful APK compilation is not proof of phone installation or end-to-end account functionality.
