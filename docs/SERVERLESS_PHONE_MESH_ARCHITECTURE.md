# Serverless phone-to-phone account and node mesh

Status: selected target architecture; implementation is not complete. Do not publish either APK as a serverless release until all acceptance tests pass.

## Product decision

The selected design removes the fixed account server and the build-time `AE_ACCOUNT_API_URL` variable. Phones communicate directly with other participating phones. Slower discovery, login synchronization, and ban propagation are acceptable; silently falling back to a central account server is not.

## Identity and registration

- Each installation creates a cryptographic device key pair using Android Keystore where supported.
- An account identity is derived from its public key (stable, globally unique without a central username allocator).
- Registration creates a signed account record and propagates it to reachable peers.
- Display name, QQ/WeChat contact fields, avatar, and profile data are attributes, not globally unique identity keys.
- Login proves possession of the private key. A local PIN/password may unlock the protected key; never replicate passwords or private keys.
- New-device recovery/onboarding uses a QR invitation or a previously paired trusted device. Do not promise recovery if the user loses every trusted device and recovery phrase.

## Admin authority and ban/unban

- The admin APK owns an offline administrator signing key. Its public verification key is pinned in the main APK and admin APK.
- Ban/unban records are signed, append-only events containing account public-key ID, action, reason, issue time, optional expiry, and monotonic admin sequence number.
- Every peer verifies the signature before applying an admin event. Ordinary worker nodes cannot create or override admin actions.
- A ban remains effective offline once received. A disconnected device cannot learn about a newer ban until it reconnects; the UI must show the last synchronization time and must not claim globally current status while offline.
- Admin key rotation requires a record signed by the currently trusted admin key (or a separately documented recovery process).

## Peer discovery and synchronization

- Prefer nearby Android discovery / Wi-Fi LAN discovery when available.
- For internet peers, use authenticated peer invitations and a bounded peer table; attempt direct connections with retries and exponential backoff.
- Use signed gossip/synchronization messages and request missing event ranges by sequence/hash.
- Persist verified records locally and replicate to multiple reachable peers. Never trust an unsigned profile, node-presence, ban, or unban message.
- A phone may act as a relay only after explicit opt-in. The admin APK is an administrator console, not a worker node.
- No fixed account endpoint, Cloudflare Worker, central database, or GitHub variable is part of the runtime account protocol.

## Important network limitation

Pure phone-to-phone internet connectivity cannot guarantee that any two phones can reach each other. Carrier NAT/CGNAT, Android background restrictions, battery optimization, and offline peers can prevent discovery or direct connections. Without a central rendezvous/relay service, first contact across unrelated networks may require a QR invitation, manual peer exchange, or a previously known peer. The app must report this honestly. Slow retries are acceptable; fabricating online status or silently routing through a central server is not.

## Conflict and consistency rules

- Account IDs are public-key-derived, not usernames.
- Admin events are authoritative only when signed by the pinned admin key and have a valid monotonic sequence.
- Profile and node-presence updates are non-authoritative, timestamped/versioned metadata.
- Duplicate or replayed events are idempotently ignored.
- Conflicting admin events at the same sequence are treated as a security fault and surfaced to the admin; never resolve by trusting the latest wall-clock timestamp.
- Offline clients reconcile missing records after reconnecting.

## Privacy and resource controls

- Encrypt peer sessions and authenticate both endpoints.
- Share only account/event metadata needed for synchronization; do not send project media or AI model weights as part of account sync.
- Worker participation and relay participation require explicit opt-in, visible status, and pause/stop controls.
- The global node-network enable/disable control remains in the admin APK only. Disabling it stops mesh participation; enabling it resumes discovery/reconnection.
- The admin APK must not become a worker node.

## Build requirements

- Remove `AE_ACCOUNT_API_URL` from both APK workflows only after the LAN/Cloudflare account patch path is replaced by the peer-mesh implementation.
- Add no fake URL and no localhost/LAN fallback.
- Include the same pinned admin public key and protocol version in both APKs.
- Build must fail if the peer-mesh module or protocol verification tests are absent/failing, not silently ship the old LAN account gate.

## Acceptance tests before release

1. Two phones discover and pair on the same Wi-Fi without any account server.
2. A new account is created and synchronized between peers; duplicate/replayed records are rejected.
3. Login works offline on a previously paired device using its protected key.
4. A signed admin ban with reason/expiry propagates to online peers and is applied when an offline peer reconnects.
5. A signed unban propagates and restores access; a forged unsigned ban/unban is rejected.
6. Admin sequence conflicts and admin-key rotation are handled safely.
7. A device with no known peer clearly reports that first-time registration/sync is unavailable rather than pretending success.
8. Global node toggle in the admin APK stops/resumes discovery; the main APK has no global toggle.
9. Cross-network tests document where direct P2P fails due to NAT/background restrictions; the UI accurately reports disconnected/stale state.
10. Main APK retains editor, RIFE, Real-ESRGAN, project import/export, plug-ins, and export features. Admin APK remains separate.
11. APK package/signature checks pass, followed by real multi-device end-to-end tests.
