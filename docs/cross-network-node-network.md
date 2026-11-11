# Cross-network phone node network

Status: staged implementation. Authenticated node presence and a bounded opaque relay endpoint are implemented in the Worker source and pass Wrangler dry-run validation. APK-side end-to-end encryption/trust, actual message exchange, deployment and cross-network device tests remain outstanding.

## Product behavior

- Two installable Android packages remain separate: the EffectCraft node client and the administrator app.
- A node joins after the user installs the APK, grants Android-required permissions, and signs in. It then registers a stable device identity and reconnects when Android and the network allow it.
- Nodes in different homes, cities, Wi-Fi networks, and mobile carriers must be able to exchange authenticated control events.
- The administrator app has one global network switch. OFF prevents node sessions and relayed peer traffic; ON permits authenticated nodes to reconnect.
- Account registration/login and ban/unban remain authoritative in the existing Cloudflare Worker + D1 service. Existing account data and secrets must not be replaced during this work.

## Network topology

1. **Control plane:** the existing Cloudflare Worker authenticates users/admins and stores authoritative account state in D1.
2. **Presence and signaling:** authenticated node sessions connect outbound over TLS WebSocket to the Worker. This works behind ordinary home routers and carrier NAT because phones initiate the connection.
3. **Peer transport:** attempt a mutually authenticated direct peer connection where supported. Direct connectivity is an optimization, not a requirement.
4. **Relay fallback:** when NAT/firewall policy prevents direct connectivity, the Worker can route bounded, age-checked opaque envelopes between authenticated live node sessions. The current Worker does not inspect application payload contents; APK-side encryption, key agreement, recipient trust and signature verification are still pending. Never assume mDNS or private IPv4 addresses are routable across the public internet.
5. **Android lifecycle:** run only after explicit opt-in, use a foreground service and visible notification while active, reconnect with bounded exponential backoff, and respect user/system stop controls and battery restrictions.

## Global switch semantics

- Only an authenticated administrator can change the switch.
- The server-side state is authoritative; a local preference is only a display/cache value.
- OFF is enforced server-side: reject new node WebSocket sessions, close existing sessions, and reject relay messages. Do not rely on a best-effort push alone.
- ON permits nodes to reconnect automatically. It does not silently restart an Android service that the user or Android has explicitly stopped.
- Every state change is timestamped and broadcast to connected nodes. Clients must also read the current state after reconnecting to avoid missing events.

## Identity and message security

- Give each installation a stable public/private key pair backed by Android Keystore where available. The private key never leaves the device.
- Bind the public key to the signed-in account through an authenticated pairing/registration flow. Require administrator approval or a clear trusted-device approval step before a node can issue privileged actions.
- Sign every peer control message; include protocol version, sender identity, recipient, message ID, creation time, expiry, and event type.
- Reject replayed, expired, oversized, malformed, untrusted, or unauthorized messages. Use TLS in transit; never transmit passwords or JWT secrets between peers.
- Ban/unban decisions are written to D1 first. Peers receive notifications as hints and must verify authoritative account state with the Worker. A peer must never be able to override D1 ban state.

## Delivery milestones

1. Preserve and verify current account API, D1 schema, admin login, and both existing APK build workflows.
2. Implement server-authoritative global network state and authenticated node presence/session APIs.
3. Add Android node identity registration, pairing/trust, foreground lifecycle, and reconnect behavior.
4. Add signed event relay with recipient authorization, replay protection, rate limits, and bounded payloads.
5. Add direct peer transport/NAT traversal as an optimization; retain relay fallback for restrictive networks.
6. Add the single administrator ON/OFF control, showing the server-confirmed state and handling failed requests safely.
7. Build both APKs and validate with devices on genuinely different networks (for example, home Wi-Fi versus mobile data), including OFF/ON, reconnect, ban/unban, and app/process restart tests.

## Acceptance tests

- Two phones on different networks can authenticate and exchange a signed test event through the relay.
- The same test succeeds after changing one phone from Wi-Fi to mobile data.
- Turning the global switch OFF rejects new sessions and stops relay delivery to existing sessions.
- Turning it ON allows eligible nodes to reconnect without manual IP, SSH, or port-forwarding configuration.
- A banned account remains blocked after reconnect and cannot use peer messaging to bypass the ban.
- A lost connection does not lose authoritative state; the client reconciles from the Worker on reconnect.
- Android-required foreground-service/notification behavior is visible and user-controllable.
- Both APKs install and update with stable signing; no release is marked complete until artifacts are actual APK files and the cross-network tests pass.

## Main APK automatic node participation (user requirement, 2026-11-11)

The EffectCraft main APK is itself the node client. There is no third node APK and no separate in-app node enrollment/registration screen. After installation and first launch, the app should create a per-install node identity locally and automatically attempt to join the node network. This node identity is distinct from the user's EffectCraft account registration/login.

Do not present a separate "register this phone as a node" flow, do not ask the user to enter a node/server address, and do not require manual peer pairing for ordinary node participation. The network protocol must still authenticate devices cryptographically in the background (for example, ephemeral or provisioned device keys) and enforce authorization server-side; "no manual node registration" does not mean unauthenticated public relay access.

Android system rules remain mandatory: use the required foreground-service notification and runtime permission prompts where the OS requires them. Do not hide node activity, bypass system permission dialogs, or restart a service after the user/system explicitly stops it. Once the user launches the app and required Android system conditions are satisfied, node startup and reconnect should be automatic.

The standalone administrator APK remains the only separate management app and owns the global network ON/OFF control. OFF must stop node sessions and relayed traffic; ON permits eligible main-app nodes to reconnect automatically. Keep the existing account registration/login requirement separate from node enrollment: this change removes only the separate node-registration flow, not the account system.

## Operational constraints

- Wi-Fi alone cannot connect private devices across unrelated routers. A public coordination/relay endpoint is required.
- Cloudflare Workers/D1/DO free plans have quotas and are not guaranteed unlimited or permanent. Relay bandwidth and connection limits must be measured before broad distribution.
- Do not place Cloudflare tokens, JWT secrets, admin passwords, signing keys, or private peer keys in source, APK assets, issue comments, or chat.
- Do not claim nationwide availability until the intended Chinese carrier/network routes have been tested. Some networks may block or impair particular public endpoints.


## Current implementation checkpoint (2026-11-11)

- Worker-side authenticated node presence already exists; main APK account sessions automatically attempt `/v1/nodes/events` after account verification.
- Worker-side relay envelope routing was added on `implementation/p2p-full-replacement`; Wrangler dry-run validation passed on run `42961309379`.
- Relay is not yet deployed to production. The current APK client maintains node presence but does not yet implement complete end-to-end encrypted peer message exchange. Do not describe the network as fully interconnected until two phones on genuinely different networks exchange a test message and the administrator OFF/ON switch is verified.


## Public Wi-Fi requirement (confirmed 2026-11-11)

Public Wi-Fi is a supported Internet uplink for node-to-node connectivity. Two phones on unrelated public hotspots must be able to attempt discovery and exchange data without sharing an SSID/subnet or entering IP addresses. Local mDNS/UDP broadcast is only an optional same-LAN optimization.

The implementation must use outbound authenticated signaling, attempt encrypted direct connectivity/NAT traversal, and fall back to an available encrypted relay when the hotspot isolates clients or blocks inbound/UDP traffic. A captive portal must be completed by the user; the app must not bypass it. Public Wi-Fi alone does not guarantee peer reachability because hotspots commonly use NAT/CGNAT and filtering.

The administrator-phone account database remains private and must not be exposed by removing the same-subnet account API guard. Cross-network account operations require a separately designed authenticated encrypted tunnel/service. Account-server and node-network switches remain independent.

**Current status:** this is a confirmed requirement, not a completed feature. Current local account discovery and peer health checks are LAN-only; complete public-Wi-Fi signaling, end-to-end encrypted payload exchange, relay fallback and two-real-device tests remain outstanding.
