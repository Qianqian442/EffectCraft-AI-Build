# No-server account and node-mesh implementation plan

Status: design baseline only. This document does not claim that peer-to-peer account sync, global bans, or cross-network relay are implemented.

## Product constraints

- Keep exactly two Android packages: the EffectCraft main app and the separate admin app.
- The main app must not expose the global node-network switch. It joins the mesh automatically when networking is enabled.
- The admin app owns the global mesh enable/disable control and account ban/unban controls. The admin app itself is not a mesh node.
- Do not remove editor, project import/export, WASM plugin, desktop-AE-plugin inspection/migration, AI frame interpolation, or AI quality enhancement features to make a build pass.
- Do not bundle the local DeepSeek model in the main APK; keep the separate model/plugin path.
- No Cloudflare Worker, VPS, or other centrally hosted account server is acceptable for the requested no-server mode.

## Verified current gaps

- The existing account-gate conversion script requires an HTTPS `.workers.dev` endpoint. It cannot currently operate in a serverless peer-only mode.
- The current node hub tracks WebSocket presence and ping/pong; it explicitly rejects peer payload relay.
- The documented Android discovery path is LAN/mDNS discovery and health checks, not cross-network peer transport.
- There is no implemented signed account-event replication, anti-entropy synchronization, or mobile NAT traversal in the current codebase.

## Required protocol before enabling no-server mode

1. **Device identity**: generate a per-install public/private key pair in Android Keystore; never export the private key. Define recovery and reinstall behavior explicitly.
2. **Admin authority**: pin the admin public key in a deliberate enrollment flow. Admin actions (ban, unban, network state changes) must be signed and carry monotonically increasing sequence numbers.
3. **Account events**: represent registration, credential changes, ban, and unban as signed immutable events. Passwords and reusable credentials must never be replicated in plaintext.
4. **Replication**: exchange signed event batches with authenticated peers; verify signatures, authority, sequence numbers, expiry, and conflict rules before applying. Add anti-entropy so temporarily disconnected peers can converge.
5. **Ban enforcement**: apply a verified ban on receipt and re-check before enabling editing. An offline device cannot learn a new ban until it reconnects; do not claim instantaneous offline revocation.
6. **Peer discovery and transport**: retain LAN discovery, then add an explicit peer introduction mechanism and a tested NAT traversal strategy. Direct connections will not work on every carrier NAT. A relay or reachable bootstrap endpoint would be infrastructure and would violate the strict no-server requirement.
7. **Global registration semantics**: define how two isolated partitions prevent duplicate usernames and conflicting registrations. Without a reachable authority or consensus quorum, global uniqueness cannot be guaranteed while partitions are offline.
8. **Admin network switch**: publish a signed global enabled/disabled event. On disabled, clients stop peer sessions; on enabled, they retry discovery and peer connections. This setting belongs only in the admin app.

## Acceptance tests required before an APK is called complete

- Two Android devices on the same Wi-Fi discover and authenticate each other.
- Two devices on different networks establish a peer session without a centrally hosted relay, or the UI clearly reports that the current network cannot establish a direct path.
- A signed ban and unban replicate to connected peers and survive app restart.
- An offline peer applies the latest signed ban when it next synchronizes; tests must not imply that an offline peer receives an immediate update.
- Conflicting account events and stale/replayed admin events are rejected deterministically.
- Admin app never advertises itself as a node and its global switch is the only UI control for global mesh state.
- Main and admin APKs pass APK signature, manifest, ABI, and ZIP-alignment checks.
- Existing editor and import/export regression tests pass; no feature is removed to satisfy account/network tests.

## Build gate policy

Do not bypass the current account-service build gate by supplying a fake URL or by compiling a UI-only account stub. Until the peer protocol and its tests exist, label any APK as a base/editor-only build and do not represent it as containing working global registration, bans, or cross-network node networking.
