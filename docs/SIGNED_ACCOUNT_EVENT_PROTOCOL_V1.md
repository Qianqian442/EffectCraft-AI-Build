# Signed account-event protocol (draft v1)

This is a protocol specification for the no-hosted-server migration. It is not an implementation and must not be enabled in production until the acceptance tests in `NO_SERVER_ACCOUNT_NODE_MESH_PLAN.md` pass.

## Security boundary

- Identity keys: Ed25519 key pair per installation. Generate and retain the private key using Android Keystore-backed storage; export only the public key.
- Admin authority: a separate Ed25519 public key is enrolled into clients through a trusted, out-of-band bootstrap. Never trust an admin key received only from an untrusted peer.
- Event signatures: sign the UTF-8 bytes of RFC 8785 JSON Canonicalization Scheme output for the `signed` object. The outer `signature` field is excluded from the signed bytes.
- Hash: SHA-256 of the canonical signed object. Event IDs are the lowercase hex digest.
- Transport encryption is not a substitute for event signatures. Peers authenticate each other before exchanging events.

## Envelope

```json
{
  "version": 1,
  "signed": {
    "event_type": "account.register",
    "event_id": "<sha256-of-canonical-signed-object>",
    "issuer_key": "<base64url-ed25519-public-key>",
    "sequence": 1,
    "issued_at": "2026-01-01T00:00:00Z",
    "expires_at": null,
    "subject_key": "<base64url-account-public-key>",
    "payload": {
      "display_name": "Example"
    }
  },
  "signature": "<base64url-ed25519-signature>"
}
```

The example is illustrative only; implementations must compute the ID and signature and must not copy the placeholder values.

## Event types and authority

| Event | Issuer | Required payload |
|---|---|---|
| `account.register` | account key | display name; no password or reusable secret |
| `account.profile` | account key | allow-listed profile fields |
| `account.ban` | enrolled admin key | reason, issued time, expiry or null for permanent |
| `account.unban` | enrolled admin key | reference to the ban event being revoked |
| `mesh.state` | enrolled admin key | enabled boolean |

An account event must be signed by the account key identified by `subject_key`. Administrative events must be signed by an enrolled admin key. Peers must reject unknown event types, oversized payloads, invalid encodings, invalid signatures, and events from unauthorized issuers.

## Ordering, replay, and conflict handling

- Track the highest accepted sequence per issuer key. Reject duplicate event IDs and sequences already used by a different event.
- A gap in sequence numbers is not proof of invalidity: retain the event as pending until missing predecessors arrive, then validate the chain.
- Do not use device wall-clock time as the sole ordering authority. Sequence and signed predecessor references determine issuer order; timestamps are display/expiry metadata.
- A ban is active only if its admin signature is valid and no later valid unban references that ban event. A permanent ban has `expires_at: null`.
- Concurrent profile edits are resolved deterministically by issuer sequence and then event ID, and the UI must disclose when a conflict was resolved.
- Username/display-name uniqueness cannot be guaranteed across disconnected partitions without a reachable authority or consensus quorum. The first version must use public-key identity as the unique account identifier and treat display names as non-unique.

## Synchronization

Peers exchange inventory summaries (issuer key, highest contiguous sequence, pending sequence ranges, and known event IDs), then request missing event envelopes. Every received event is verified locally before persistence or application. Use bounded batches, pagination, and backoff. Persist the event log transactionally before acknowledging it to a peer.

Never replicate passwords, password hashes, login tokens, session cookies, admin passwords, private keys, or local device secrets.

## Offline and revocation semantics

An offline device cannot receive a new ban or network-disable event. On its next successful peer synchronization it must apply verified newer events before unlocking the editor or joining the mesh. The product must not claim instant remote revocation while disconnected. Clearing app data or reinstalling requires identity recovery/re-enrollment; do not silently create a fresh identity and treat it as the old account.

## Required protocol tests

1. Valid account registration and profile events verify and persist.
2. A bit-flipped payload or signature is rejected.
3. An event signed by an untrusted admin key is rejected.
4. Duplicate event IDs and reused issuer sequence numbers are rejected.
5. Out-of-order events remain pending until predecessors arrive.
6. A valid ban blocks access after sync; a valid unban references and clears only that ban.
7. Expired temporary bans cease to apply according to a trusted-time policy; clock rollback tests are required.
8. Concurrent profile events converge to the same result on every peer.
9. No test fixture or event payload contains password material or private keys.
10. A device offline during a ban is explicitly tested as receiving that ban only after reconnecting.

## Open design decisions (must be resolved before implementation)

- Trusted admin-key enrollment and rotation/revocation.
- Trusted-time strategy for temporary-ban expiry when devices are offline.
- Identity recovery after reinstall or device replacement.
- Peer introduction and cross-network transport without a relay/bootstrap server. Some carrier NAT combinations will prevent direct connections; strict no-server mode cannot guarantee universal reachability.
- Rate limits and abuse resistance for untrusted peer invitations and event floods.
