# EffectCraft AI Build

Private, reproducible Android build workspace for EffectCraft 0.21.1.

## APK outputs

- Main EffectCraft APK.
- Separate EffectCraft Admin APK.

## Network architecture

Two independent network systems are part of the selected design. Neither replaces the other.

### A. Cloud account and administration

The Cloudflare Worker account API is authoritative for registration, login, profile, account status, ban/unban, administrator permissions and the global node-network switch. Both APKs use the configured HTTPS Worker endpoint. The Worker deployment and health checks must pass before account features are described as live.

The administrator APK manages accounts and the global node-network switch. The administrator phone is not the only account server or only network relay.

### B. Cross-network mobile P2P

The selected peer networking engine is the official Rust libp2p implementation. The target stack is encrypted Peer IDs/sessions, Identify, AutoNAT, Circuit Relay v2, DCUtR hole punching, QUIC and TCP fallback.

Phones on different networks may connect directly when NAT/firewall conditions permit. If direct connectivity fails, they need an available public relay. Carrier-grade NAT and Android background restrictions mean that no P2P library can guarantee every phone pair is directly reachable.

A Cloudflare Worker account URL is not itself a libp2p relay endpoint. A public bootstrap/relay endpoint must be deployed and tested before cross-network P2P is considered operational. See [P2P implementation plan](docs/P2P_NETWORK_IMPLEMENTATION.md).

### Independent switch behavior

- Account API available, P2P ON: account services and authorized peer networking operate.
- Account API available, P2P OFF: account services operate; peer discovery and task participation stop.
- Account API unavailable, P2P ON: online account operations and fresh node authorization are unavailable; do not fake successful authentication.
- Both unavailable/OFF: local editor and local project work remain available.

The Admin APK must report actual service and peer status separately. Never infer online status from a switch alone.

## Android node participation and privacy

Main APK devices must explicitly opt in before acting as network nodes. Explain battery, mobile-data and resource use. Use a foreground service with a persistent notification while active relaying or task processing is running. Logout, ban, opt-out or global OFF must stop task acceptance and close/revoke peer sessions.

## Preserved Main APK features

The main APK remains EffectCraft 0.21.1. Do not remove editor features, project import/export, WASM plug-ins, desktop-AE plug-in inspection/import, RIFE frame interpolation, or Real-ESRGAN quality enhancement to make networking compile. The DeepSeek local model remains a separate optional importable plugin/resource and is not bundled into the main APK.

## Build and verification

A queued/running workflow is not a completed APK build. A successful compilation is not proof of installation or cross-network operation. Verify APK integrity, signing, installation compatibility, account registration/login, admin ban/unban, both independent switches, peer discovery, encrypted cross-network transport, relay fallback and bidirectional test-payload transfer separately. Never claim a test passed unless it was actually run.
