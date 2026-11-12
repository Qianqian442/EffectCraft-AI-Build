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

## Phone-hosted account authority (current target architecture)

The standalone administrator APK is the only account authority. It hosts the account API on the administrator phone and stores the SQLite account database locally. Registration, login, profile changes, password verification, bans, and unbans are evaluated against this database. A cloud VPS or hosted account database is not required.

The administrator app starts a foreground service for the phone-hosted account API. Android must show its persistent notification while the service is active. The administrator phone must remain powered, connected to a network, and allowed to run in the background for remote account operations to work.

The administrator home screen displays the total registered account count from `SELECT COUNT(*)`, including banned accounts. Pending connection/device joins are not counted as accounts. A registered account is counted once regardless of how many devices it uses.

Ordinary device connection requests are automatically admitted after the connection identity and account authorization checks pass. There is no per-device manual approval queue. This does not grant administrator rights, bypass login, or permit banned accounts to connect.

## Cross-network connection order

1. Same Wi-Fi: discover and connect directly to the administrator phone.
2. Different networks: attempt peer-to-peer direct connection and NAT hole punching.
3. If direct connection fails: discover multiple independent public Circuit Relay v2 peers, reserve more than one relay where possible, and use the healthiest available relay.
4. If the active relay fails or becomes congested: fail over to another reserved relay. Do not duplicate every account request across all relays.

Relays are transport only. They must forward end-to-end encrypted streams and must not store account records, passwords, JWT signing secrets, or ban authority. The administrator phone remains the sole source of truth. Peer identities use per-install keys; connections are admitted automatically only after cryptographic authentication and account authorization.

## Free public relay limitations and security

Free public relays are best-effort community infrastructure: availability, speed, geographic reach, bandwidth quotas, and uptime are not guaranteed. The client should maintain a small healthy relay set, measure reachability/latency, use bounded retries and backoff, and clearly report when no relay is reachable. Do not hard-code an unverified public relay as the only route.

Public relays can observe connection metadata such as peer identifiers, IP addresses visible to the relay, timing, and data volume. They must not be able to read or modify account payloads. End-to-end encryption and authentication are mandatory before cross-network relay traffic is enabled.

## Implementation status

- Phone-hosted SQLite account service: Android-side implementation in progress.
- QQ or WeChat as the single required registration identifier: included in the phone account API schema/validation.
- Admin registered-account counter: sourced from the local database and refreshed while the admin account screen is open.
- Automatic connection admission: the protocol policy is automatic after cryptographic identity and account-status checks; the relay/device protocol still needs integration.
- LAN discovery: an existing Android NSD/mDNS discovery milestone is present.
- P2P/NAT traversal and multi-relay Circuit Relay v2 transport: design target only; not yet implemented or proven by cross-network device testing.

Do not describe the multi-relay or cross-network path as operational until the main APK and administrator APK both build, the encrypted relay transport is integrated, and real phones on different Wi-Fi/mobile networks pass the acceptance tests.