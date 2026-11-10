# EffectCraft AI Build

Private, reproducible Android build workspace for **EffectCraft 0.21.1**.

## Repository layout

- `.github/workflows/`: Android APK build and complete-source vendor workflows.
- `.github/scripts/`: export dialog, project import/export, local AI, and Android WASM plug-in integration patches.
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

## Home-Wi-Fi account system

The account system is split from the editor:
- `account-server/`: self-hosted account API and SQLite database for a home PC. Follow its Chinese README and run `start-server.bat` on the PC that stays on at home.
- `admin-app/`: independent Android administrator APK project. Its workflow publishes a separate APK release asset.
- `.github/scripts/add_home_lan_account_gate.py`: integrates registration/login, home-server status checks, the home-screen profile editor and account-ban lock into the main Android build.

The mobile app defaults to `http://192.168.1.100:8787` as a placeholder. Replace it in the first-launch account screen with the actual Wi-Fi IPv4 address of the home PC. This design is LAN-only: do not configure router port forwarding. The main APK requires the home server to be reachable at startup and rechecks account status while it stays open; an unavailable server keeps the editor locked.
