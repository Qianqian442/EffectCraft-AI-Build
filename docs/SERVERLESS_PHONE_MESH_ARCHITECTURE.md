# EffectCraft VPN account channel + independent phone P2P node network

Status: selected implementation target. This document is a specification, not proof that the APK implementation is complete.

## Product decision

Use the administrator's Android phone as the sole account authority and SQLite database host. Main APKs reach the account API only through an authenticated, encrypted VPN overlay connection to the administrator phone. The account channel is limited to registration, login/session verification, account profile modification, account deletion, and administrator ban/unban operations. It is not a general-purpose public API.

The node network is a separate phone-to-phone P2P subsystem. Do not route node payloads through the account API, do not use the administrator account endpoint as a media relay, and keep the account-service switch independent from the global node-network switch.

The user does not operate or maintain a rented VPS, cloud database, Docker host, or fixed account server. A VPN overlay may still rely on its own coordination/relay infrastructure depending on the selected VPN implementation and NAT conditions; never describe such a dependency as literally infrastructure-free. Prefer direct VPN peer paths and use only the VPN product's encrypted relay fallback when required. Do not introduce a self-hosted public server as a hidden prerequisite.

## Account authority and allowed API surface

- The Admin APK owns the local SQLite database and the administrator signing key.
- The Admin APK runs the account listener only while its independent account-service switch is ON.
- The listener must accept account requests only on the VPN interface/address and from authenticated VPN peers. It must not bind broadly to public interfaces or accept arbitrary LAN clients as a substitute.
- Account operations: registration, login, session/token validation, read/update own profile, delete own account, admin list/read users, admin edit/delete users, admin ban and unban with mandatory reason and optional expiry.
- Main APK users may register/login and modify/delete only their own account. They cannot invoke admin endpoints or change another account.
- Admin endpoints require a separate administrator authorization proof in addition to VPN membership. VPN membership alone is not administrator permission.
- Keep password hashing with a modern salted password KDF, short-lived challenge where appropriate, token expiry/revocation, rate limiting, request-size limits, and audit events.
- Use HTTPS/TLS or an equivalently authenticated encrypted application channel inside the VPN; VPN encryption does not justify sending reusable credentials over plaintext HTTP.
- Never expose SQLite, database files, admin secrets, or debug endpoints.
- On account-service OFF, stop the listener and reject new account operations. Node networking remains independently controlled.
- On VPN loss, account actions fail closed and show a clear offline/retry state. Do not pretend registration/login succeeded or silently fall back to a cloud endpoint.

## VPN connectivity and limitations

- Both APKs join the same private VPN overlay using device-specific cryptographic identities.
- The Admin APK advertises/reaches its account endpoint only over the VPN address; the Main APK discovers the authorized admin peer through a signed invitation/peer configuration, not LAN broadcast alone.
- Do not require the same Wi-Fi SSID, subnet, router, ISP, city, or manual public IP.
- Prefer direct encrypted peer-to-peer VPN paths. If NAT/CGNAT or network policy prevents direct paths, the chosen VPN may require an encrypted coordination or relay service. The owner must not have to operate that service, but it must be disclosed and its availability cannot be guaranteed without it.
- If the user requires absolutely no third-party coordination or relay infrastructure, cross-network VPN reachability cannot be guaranteed. Show unreachable status rather than weakening security.
- Respect captive portals, hotspot client isolation, VPN restrictions, Android background limits, battery settings, and user permission revocation. Never bypass network-owner policy.
- The VPN is for account control-plane traffic only. Node P2P transport remains separate and must not be coupled to account VPN availability unless explicitly required by a security policy.

## On-demand VPN session lifecycle (required)

The Main APK must not keep the account VPN tunnel continuously connected.

1. On every cold app launch, before enabling protected editor/AE functions, start a short-lived account-check VPN session.
2. Authenticate the Main APK device and query the Admin phone for the current account status, ban flag, ban reason/expiry, and account/session validity. The response must be authenticated and bound to the current launch nonce to prevent replay.
3. If the account is active and the response is valid, persist only a short-lived signed status receipt with a strict expiry, then immediately stop the account VPN session. Do not keep a background tunnel alive.
4. If the account is banned, block protected EffectCraft/AE functions and show the administrator-provided reason and expiry. Do not allow a local bypass.
5. If the Admin phone/VPN is unreachable, the response is stale, authentication fails, or the check times out, the app must not claim the account is unbanned. Keep protected functions locked and show retry/offline status. Do not silently fall back to LAN, public HTTP, or Cloudflare.
6. When the user later opens a function that actually requires account service (registration/login, profile change/deletion, account refresh), establish the VPN session just for that operation, complete the authenticated request, and disconnect immediately afterward.
7. If a protected operation spans multiple API requests, keep the tunnel only for that bounded operation and close it on success, failure, cancellation, or timeout.
8. On Android, VPN startup is subject to the platform VPN permission/consent and background execution rules. The first setup may require explicit user approval; do not silently bypass Android's VPN consent UI.
9. The Admin APK account listener remains available only while its account-service switch is ON. The Main APK's global node network is separate and must not be switched on/off by account VPN connect/disconnect.

This is an on-demand, short-session account VPN policy, not an always-on VPN policy. The launch-time status receipt is short-lived; it is not a permanent offline authorization.

## Independent node network

- Main APK devices may join the node P2P network according to the agreed first-run disclosure/consent and Android system controls.
- Admin APK owns the global node-network ON/OFF control and is not a worker node.
- OFF closes existing node sessions and stops new participation; ON allows eligible peers to retry/reconnect.
- Use authenticated encrypted peer sessions, replay protection, bounded peer discovery, and resource controls.
- Same-LAN discovery is an optional accelerator only. Cross-network direct P2P is best effort; CGNAT/firewalls may prevent it. Do not claim universal connectivity without a reachable encrypted relay path.
- Account-service ON/OFF and node-network ON/OFF are two independent switches.

## Android and privacy requirements

- Keep device keys in Android Keystore where supported; never hard-code private keys, passwords, bearer tokens, or VPN credentials in source or APK resources.
- Pair/enroll devices using signed invitations or a secure one-time QR flow. Revocation must invalidate the peer's account-channel access.
- Show a clear first-run explanation of VPN connection, account traffic, background activity, and node participation. Do not hide resource use or imply a connection exists when it does not.
- No project media, video frames, AI model weights, or editor assets are sent through the account channel.
- Preserve user control through Android VPN permission, OS network settings, app uninstall, and notification controls.

## Build requirements

- Remove the old LAN-only account discovery/endpoint assumptions from the Main APK only after VPN peer enrollment and authenticated account transport are implemented.
- Remove Cloudflare Worker/D1 account runtime dependencies and AE_ACCOUNT_API_URL from both APK workflows only after all account operations work over the VPN channel.
- Do not use localhost, a fixed public URL, raw public HTTP, or a fake endpoint as a fallback.
- Add the same protocol version and pinned administrator verification identity to both APKs.
- Build must fail if VPN account transport, peer authentication, endpoint allowlisting, or protocol tests are absent/failing.
- Preserve all original editor functions, project import/export, WASM plugins, desktop AE plugin migration, RIFE interpolation, Real-ESRGAN enhancement, export, and the separate DeepSeek plugin.

## Acceptance tests before release

1. Admin phone and Main phone join the VPN overlay from unrelated networks.
2. Main APK can register and login through the VPN account channel; no cloud account endpoint is used.
3. Main APK can modify/delete its own profile/account but cannot modify/delete another user's account.
4. Admin can list, modify, delete, ban and unban accounts; ban reason and expiry persist and audit records are created.
5. A normal VPN member cannot call admin endpoints; a forged/replayed admin request is rejected.
6. Account-service OFF blocks account API requests while node-network state remains unchanged.
7. VPN disconnection fails closed; reconnection restores account access without manual IP entry.
8. No account listener is reachable through public Wi-Fi/mobile interfaces outside the VPN.
9. Node-network OFF independently closes node sessions; ON permits eligible nodes to reconnect.
10. Test two real phones on different Wi-Fi/mobile networks, including a restrictive NAT case; record when the VPN uses direct path versus encrypted relay.
11. Verify key revocation, token expiry, rate limits, and account deletion behavior.
12. APK package/signature/integrity checks pass and original editor/AI/import/export/plugin features remain intact.

## Current implementation checkpoint

The current Admin APK source is still a LAN-only HTTP listener bound around port 8788 and uses Wi-Fi IPv4/subnet checks. It is not yet a VPN-bound TLS account server. Existing UDP/mDNS discovery is LAN-only. This must be replaced or securely adapted before release. This document does not claim the VPN channel or cross-network account access is already implemented.
