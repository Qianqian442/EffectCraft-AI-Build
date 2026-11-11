# EffectCraft AI Build

Private, reproducible Android build workspace for EffectCraft 0.21.1.

## APK outputs

- Main EffectCraft APK.
- Separate EffectCraft Admin APK.

The admin phone is the authoritative account server when its owner enables the server switch in the Admin APK. The Admin APK is both the management console and the optional server host; it is not a worker node. Main APK clients connect to that admin-hosted service for registration, login, account/profile sync, and ban-status checks. The server can be stopped at any time from the Admin APK.

## Admin-phone server mode (selected architecture)

- Switch ON: the admin phone starts the account service, opens its authenticated API, and publishes/maintains its reachable endpoint. Main APK clients connect to it.
- Switch OFF: the service stops accepting new requests and stops account synchronization. Existing local projects and editor functions remain usable; online account operations are unavailable until the admin server is enabled again.
- Admin phone offline / app force-stopped / Android suspends it: clients cannot reach the authoritative account service. The service does not magically remain available.
- Cross-network access: phones on different carriers are commonly behind CGNAT. A phone-hosted server may not accept inbound connections directly. The implementation must test direct reachability and, where required, use an explicitly configured secure reverse tunnel/relay. A relay is transport only; it must not become a second account database or silently replace the admin phone as authority.
- No false online state: Admin APK status must reflect a real listener and a real external reachability/health check, not merely the switch value.

This is a phone-hosted client/server account architecture, not a fully decentralized P2P account mesh. The user has chosen the admin phone as the central authority with a manual ON/OFF control. Do not describe it as serverless or as every phone holding an authoritative replicated account database.

## Preserved Main APK features

The main APK remains EffectCraft 0.21.1. Do not remove editor features, project import/export, WASM plug-ins, desktop-AE plug-in inspection/import, RIFE frame interpolation, or Real-ESRGAN quality enhancement to make account networking compile. The DeepSeek local model remains a separate optional importable plugin/resource and is not bundled into the main APK.

## Build and verification

A queued/running workflow is not a completed APK build. A successful compilation is not proof of installation or cross-network operation. Verify APK integrity, signing, installation compatibility, admin server start/stop, external reachability, registration/login, account sync, and ban/unban behavior separately. Never claim a test passed unless it was actually run.
