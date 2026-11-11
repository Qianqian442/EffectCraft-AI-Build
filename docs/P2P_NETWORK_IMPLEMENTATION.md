# EffectCraft mobile P2P network implementation plan

## Selected engine

Use the official Rust implementation of libp2p (the libp2p crate, MIT license) as the peer transport and protocol engine. Pin an exact crate version in the implementation commit and update the Cargo lockfile in CI. Do not vendor an unpinned upstream branch.

Official project: https://github.com/libp2p/rust-libp2p

## Required protocol stack

- Noise/TLS authenticated encrypted peer sessions and stable Peer IDs.
- Identify for exchanging peer identity and observed addresses.
- AutoNAT for reachability classification.
- Circuit Relay v2 for connectivity when direct inbound access is impossible.
- DCUtR for upgrading a relayed session to a direct connection where NAT behavior permits.
- QUIC first, with TCP as a compatibility transport.
- An authenticated application protocol for task offers, task acceptance, task data, results and signed control messages.
- Optional Kademlia/Gossipsub only after peer discovery and abuse controls are in place; account authorization must not be delegated to gossip.

## Authority and service boundaries

- The existing Cloudflare account API remains authoritative for registration, login, account status, bans, administrator permissions and the global node-network switch.
- libp2p carries peer-to-peer sessions and task traffic. A peer must never be able to override account status or issue an unsigned ban/unban command.
- The administrator APK remains the control plane. Its global node switch disables new peer authorizations and causes clients to close/revoke their node sessions; it is independent of account API availability.
- The administrator phone is not the sole relay or sole network server.
- A public bootstrap/relay service is a required infrastructure dependency for peers behind carrier-grade NAT. A Cloudflare Worker URL is an account API URL, not automatically a libp2p relay address. Do not claim cross-network P2P works until a real relay endpoint is deployed and tested.

## Android requirements

- Keep networking behind an explicit node-participation opt-in. Explain battery, mobile-data and resource use before enabling.
- Use an Android foreground service with a persistent notification while a user-enabled node is actively relaying or processing tasks. Respect Android background execution and battery restrictions.
- Persist the device private key in Android Keystore-backed storage; never put private keys or bearer tokens in source code, APK resources, logs or exported projects.
- Bind network startup/shutdown to the account authorization and administrator global switch. On logout, ban, opt-out or global OFF, stop task acceptance and close peer sessions.
- Prefer direct peer transport; fall back to a quota-limited relay. Apply peer allowlists, rate limits, connection limits, task size limits and signed task manifests.

## Build and verification gates

1. Add the pinned libp2p dependency and compile it for Android arm64-v8a in the existing NDK/Cargo workflow.
2. Add a native networking module and connect its lifecycle to the existing node opt-in and global-switch authorization.
3. Deploy a public bootstrap/relay endpoint and configure its signed address through the account API.
4. Verify two Android devices on different mobile/Wi-Fi networks can discover each other, establish an encrypted relay session, attempt DCUtR, and transfer a test payload in both directions.
5. Verify OFF, logout, ban, opt-out and process restart revoke or restore connectivity correctly.
6. Only then label the network operational. A successful Rust build alone is not proof of P2P connectivity.

## Non-regression

Do not remove or weaken EffectCraft editor functionality, project import/export, WASM plugins, desktop AE plugin inspection/import, RIFE frame interpolation, Real-ESRGAN enhancement, or the separate optional DeepSeek plugin to make the network compile.
