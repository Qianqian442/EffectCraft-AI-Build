# EffectCraft AI Build

Private, reproducible Android build workspace for EffectCraft 0.21.1.

## APK outputs

- Main EffectCraft APK.
- Separate EffectCraft Admin APK.

## Two coexisting network systems

Both systems are part of the selected design. They are separate services with independent controls in the Admin APK; neither replaces the other.

### A. Admin-phone account server

The admin phone is the authoritative account server when enabled. It stores the authoritative account database and handles registration, login, profile updates, account status, ban/unban, reasons and expiry. Main APK clients use this service for account operations. The Admin APK has a dedicated **Account Server ON/OFF** switch. OFF stops the account API but does not delete data; account operations are unavailable until it is turned on again. The admin phone being offline, force-stopped, or suspended makes the account service unavailable.

Cross-network inbound access to a phone may be blocked by NAT/CGNAT. The implementation must test reachability and may require an explicitly configured secure relay/reverse tunnel. Such a relay only transports encrypted traffic; the admin phone remains the account authority and the relay must not host a second account database.

### B. P2P phone-node network

Phones in different locations form a peer network for node discovery, peer-to-peer communication, and distributed compute tasks such as eligible frame/image processing. The Admin APK has a separate **P2P Node Network ON/OFF** global control. This switch controls peer networking and task participation independently of the account server switch. Main APK devices do not show node-management controls or connection-status UI.

P2P is not the authoritative account database. Account identity and final account/ban decisions remain governed by the admin-phone account server. P2P peers must authenticate each other, encrypt sessions, verify signed task/control messages, and never accept an unsigned ban/unban instruction. Direct connections can fail behind CGNAT; hole punching and user-operated relays improve reachability but cannot guarantee every pair connects. Android background restrictions may pause nodes.

### Independent switch behavior

- Account Server ON, P2P ON: account services and peer network both operate.
- Account Server ON, P2P OFF: account services operate; peer discovery and distributed tasks stop.
- Account Server OFF, P2P ON: peer network can operate for peer communication/eligible tasks; online account operations are unavailable and must not be faked.
- Both OFF: both network services stop; local editor and local project work remain available.

The Admin APK status panel must report real service state, external reachability, last successful account request/sync, and verified peer connectivity separately. Never infer online status from a switch alone.

## Preserved Main APK features

The main APK remains EffectCraft 0.21.1. Do not remove editor features, project import/export, WASM plug-ins, desktop-AE plug-in inspection/import, RIFE frame interpolation, or Real-ESRGAN quality enhancement to make networking compile. The DeepSeek local model remains a separate optional importable plugin/resource and is not bundled into the main APK.

## Build and verification

A queued/running workflow is not a completed APK build. A successful compilation is not proof of installation or cross-network operation. Verify APK integrity, signing, installation compatibility, both independent switches, admin server start/stop, external reachability, registration/login, account sync, ban/unban, peer discovery, cross-network transport, and task result validation separately. Never claim a test passed unless it was actually run.
