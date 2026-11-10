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

## Shared accounts across different Wi-Fi networks

The account system uses **Cloudflare Workers + D1** as a hosted account endpoint and shared database. This avoids renting or maintaining a VPS and avoids requiring the administrator's phone to stay online as a server. Each EffectCraft phone can use its own Wi-Fi or mobile-data connection; all devices contact the same HTTPS account API, so registration, login, profile changes, bans, and unbans share one account state.

This is **not direct Wi-Fi-to-Wi-Fi bridging**. Wi-Fi only connects a phone to its local router. Phones in different homes cannot reach one another using Wi-Fi alone because routers, NAT, and firewalls isolate private networks. A publicly reachable coordination point is required for cross-network account synchronization; here that point is the existing Cloudflare account, not a user-managed VPS.

### Deployment and APK sequence

The `Deploy Ae Cloud Account API` workflow applies the D1 schema, deploys the Worker, configures its runtime secrets, checks `/health`, saves the resulting Worker URL as the repository variable `AE_ACCOUNT_API_URL`, and then starts builds for both the EffectCraft main APK and the standalone account-admin APK.

Required GitHub Actions repository secrets (never put their values in source code or chat):

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `JWT_SECRET` (at least 32 characters)
- `ADMIN_PASSWORD` (at least 12 characters)

Cloudflare Workers, D1, and Durable Objects have free-plan limits. This avoids VPS rental, but it is not a promise of unlimited or permanently free usage. Test the deployed endpoint on the intended networks before distributing the APKs.
