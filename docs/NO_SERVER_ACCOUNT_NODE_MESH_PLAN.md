# EffectCraft account VPN and distributed phone-node scope

Status: implementation scope. This is a target specification; it does not claim the features are already implemented.

## Account and administrator functions

The administrator Android phone is the account authority and stores the account database in its private SQLite storage. The Main APK reaches this database only through a private, authenticated, encrypted VPN overlay connection to the Admin APK.

Allowed account-channel operations:
1. Registration and login/session verification.
2. Read and modify the signed-in user's own profile.
3. Delete the signed-in user's own account.
4. Admin list/read, edit, and delete user accounts.
5. Admin ban/unban with mandatory reason, optional expiry, audit history, and immediate revocation where connected.

The Main APK must never receive administrator authority. VPN membership is not admin authorization. The account listener must accept requests only from authenticated VPN peers and must not be exposed on public Wi-Fi/mobile interfaces. Account-service ON/OFF and global node-network ON/OFF remain independent controls in the Admin APK.

Do not use Cloudflare Worker/D1 or AE_ACCOUNT_API_URL as the account authority. Do not silently fall back to a cloud endpoint. A VPN overlay may use provider-operated coordination or encrypted relay infrastructure when NAT prevents direct peer paths; this must be disclosed. The user should not need to rent or maintain a server. If all third-party coordination/relay is forbidden, cross-network connectivity cannot be guaranteed.

## Local EffectCraft functions

These remain in the Main APK and must not depend on the account channel for local processing:
- Existing editor and timeline functions.
- AI frame interpolation (RIFE).
- AI quality enhancement (Real-ESRGAN).
- Project import/export and supported preset ZIP import.
- WASM plugins and supported desktop-AE plugin inspection/migration.
- Export to the phone gallery.

The optional DeepSeek model/plugin remains separate and is not bundled into the Main APK. Do not remove existing functions to force a build.

## Independent distributed phone-node network

The node network is separate from the VPN account channel:
1. The Admin APK owns the global node-network ON/OFF control and is not a worker node.
2. Main APK devices participate according to clear first-run disclosure/consent and Android system permissions.
3. OFF closes active node sessions and stops new participation; ON permits eligible peers to reconnect.
4. Use authenticated encrypted peer sessions, replay protection, bounded peer discovery, capability negotiation, task leases, retries, and result-integrity checks before distributed compute is enabled.
5. Same-LAN discovery is an optional accelerator only. Cross-network P2P may fail under CGNAT/firewalls; any relay/bootstrap dependency must be disclosed.
6. Do not route project media, video frames, or AI model weights through the account API.
7. Do not silently consume another user's CPU/GPU/battery/network. Provide transparent consent and Android-visible controls/notifications for active resource use.

## Acceptance gates

- Main APK account operations work through the Admin phone VPN endpoint only.
- Main APK cannot call admin operations; admin authority is separately authenticated and auditable.
- Admin ban/unban reason/expiry persist and are enforced on next authenticated account check.
- Account-service switch does not affect node-network switch and vice versa.
- VPN loss fails closed; no LAN/public HTTP/cloud fallback.
- Two real Android devices on different networks complete account registration/login over the VPN overlay.
- Global node switch stops/resumes node participation independently.
- Distributed compute is not marked complete until multi-device task execution, result verification, failure recovery, resource controls, and cross-network tests pass.
- APK signature, manifest, ABI, alignment, and package-integrity checks pass.
- Main APK retains RIFE, Real-ESRGAN, editor, project import/export, plugins, and export.
