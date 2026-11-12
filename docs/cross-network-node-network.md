# Administrator-phone account authority and multi-relay network

Status: implementation specification. This file is not a claim that cross-network relay transport is already operational.

## Authority and roles

- The standalone administrator APK is the only account authority and the only account database host.
- The administrator phone stores account records in its private SQLite database. Registration, login, profile updates, password verification, bans, and unbans are committed locally on that phone.
- The EffectCraft main APK is an ordinary account client and network peer. It must not become an alternate account authority.
- Public relays are transport-only. They do not store accounts, passwords, tokens, ban records, or administrator secrets.
- No paid VPS, hosted database, or cloud account API is required for the target design.

## Connection order

1. Same Wi-Fi: discover the admin phone using Android NSD/mDNS and try a direct LAN connection.
2. Different networks: attempt peer-to-peer direct connectivity and NAT hole punching.
3. If direct connectivity fails: discover multiple independent public libp2p Circuit Relay v2 peers and request reservations on more than one relay when available.
4. Choose a healthy relay based on recent reachability, connection latency, and congestion. Keep at least one alternate reservation where possible.
5. On timeout, relay refusal, disconnect, or congestion, fail over to another reserved relay with bounded exponential retry.
6. If no relay is reachable, fail closed for account operations and show a clear connection-unavailable state. Do not silently authenticate from stale account state.

Use relays as alternatives, not as replicated sources of truth. A single account request should normally use one active route, with retry/idempotency protection if the route changes. Do not broadcast password-bearing account requests to every relay.

## Automatic connection admission

- Ordinary user devices do not enter a manual approval queue. Connection admission is automatic after device cryptographic identity and account authorization checks pass.
- Every installation has a device key pair. The private key remains on that device, preferably protected by Android Keystore.
- The peer handshake authenticates the device key and binds it to an authenticated EffectCraft account.
- A banned or expired account is rejected by the administrator phone even if its device was previously admitted.
- Automatic admission never grants administrator permissions. Only the local administrator credential on the administrator phone can perform user management or change network controls.
- Reject unknown identity keys, invalid signatures, expired/replayed messages, malformed frames, oversized payloads, and unauthenticated requests.

## Relay selection and failover

- Discover candidates dynamically; do not rely on one hard-coded public relay address.
- Use Circuit Relay v2 reservations and keepalives. Attempt a small bounded number of reservations concurrently (target up to 3; actual count depends on candidate availability and relay quotas).
- Track per-relay last success, connect latency, reservation expiry, disconnect reason, and recent failure rate.
- Prefer a healthy low-latency relay, not necessarily the geographically nearest advertised node.
- Keep one alternate reservation warm where the public relay permits it; on active relay failure, switch without requiring the user to reconfigure the app.
- Add cooldowns for failing relays, bounded retries, jitter, and a cap on concurrent relay attempts to avoid hammering public infrastructure.
- Never use a public relay for account data unless the underlying peer transport is end-to-end encrypted and peer-authenticated.
- Do not duplicate account operations over multiple relays. Use request IDs and idempotent server operations to prevent duplicate registration or ban actions if a connection drops mid-request.

## Encryption and privacy

- End-to-end authenticated transport encryption is mandatory. Use libp2p's secure transport (Noise or another supported authenticated secure channel) on top of Circuit Relay v2.
- The relay must only forward the encrypted peer stream. It must not terminate account-level encryption or receive plaintext passwords/JWT signing material.
- The relay may still observe peer IDs, network addresses, timing, and byte counts; tell users that relay use is not anonymous.
- Do not expose the current plaintext HTTP account listener to the public internet or route it directly through an unencrypted generic relay.
- LAN-only development endpoints must remain restricted to the local subnet until the encrypted peer transport is in place.

## Administrator phone lifecycle

- The admin app starts the phone-hosted account server only while the administrator has enabled it and Android permits the foreground service.
- Show the ongoing foreground-service notification and a visible ON/OFF control.
- Recommend keeping the admin phone on power and disabling battery optimization for the admin app; do not bypass Android permission or foreground-service requirements.
- When the admin phone is offline, all remote account changes and authoritative login/ban verification are unavailable. Clients should fail closed instead of treating the last-known state as authoritative.
- The admin app displays `当前注册人数` from the local database count query. Banned accounts remain included; pending device connections are not counted; one account counts once even across multiple devices.

## Build and verification milestones

1. Complete and compile-check the phone-hosted SQLite account API, admin authentication, and migrations (including QQ-only or WeChat-only registration).
2. Start/stop the account server through a visible Android foreground service; confirm it survives ordinary activity navigation and respects explicit user stop.
3. Integrate main APK device-key creation and discovery without a separate manual node-enrollment form.
4. Integrate libp2p secure peer transport, direct connection/NAT traversal, and Circuit Relay v2.
5. Implement dynamic discovery of multiple relay candidates, concurrent bounded reservation attempts, health scoring, and automatic failover.
6. Bind authenticated peer requests to the admin-phone account API; automatically admit valid ordinary devices, but always enforce account login and ban status.
7. Build both APKs and perform real-device tests across distinct Wi-Fi networks and mobile data, including relay failure/failover, admin phone offline, app restart, ban/unban, and count refresh.

## Acceptance tests

- Same-Wi-Fi account registration/login succeeds without a public server.
- The admin phone shows the correct total registered-account count; it increments on successful registration and includes banned accounts.
- A QQ-only registration succeeds; a WeChat-only registration succeeds; an empty QQ+WeChat registration is rejected.
- A normal authenticated, non-banned device joins automatically without a manual admin approval prompt.
- An unauthenticated device, invalid device key, or banned account is rejected.
- Two or more independent public relay peers can be reserved when available; if one fails, the client uses a different healthy relay.
- Traffic through a public relay is end-to-end encrypted; a relay cannot read account credentials or alter account commands.
- The same account remains authoritative only on the administrator phone; no relay or user node can create, ban, or unban accounts.
- If the administrator phone loses power or connectivity, remote verification is unavailable and clients fail closed.
- No cross-network feature is marked complete until tests run on real devices and record actual relay IDs, selected path, and failover results.
