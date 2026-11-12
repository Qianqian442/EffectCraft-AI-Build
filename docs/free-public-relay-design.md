# Free public multi-relay design

## Goal

Let the administrator phone remain the sole account server while allowing main-app phones on unrelated Wi-Fi/mobile networks to reach it without a paid VPS. Use community-operated public relays only as encrypted transport fallbacks.

## Protocol choice

Use libp2p Circuit Relay v2 with secure peer transport and direct-connection upgrade/hole-punching support. Circuit Relay v2 lets a private peer reserve a slot on a relay, advertise a relay path, and receive an incoming connection through that relay. The reservation must remain active and can be refused or terminated when relay quotas are reached.

Reference: https://libp2p.io/docs/circuit-relay/
Protocol specification: https://github.com/libp2p/specs/blob/master/relay/circuit-v2.md

## Multiple relays

- Discover a set of candidate relays dynamically through the peer-routing/discovery layer; do not ship a single fixed public relay as the only endpoint.
- Attempt reservations concurrently but with a cap. The target is up to three active or warm reservations; if fewer relays are discoverable or accept reservations, continue with the available subset.
- Maintain a scored list: reachable, reservation valid-until, latency, recent success ratio, disconnect/error count, and reported resource limits.
- Pick one active route for each peer session. Maintain a standby reservation for fast switching where possible.
- On failure: close the failed route, cool down that relay, select the best remaining valid reservation, and reconnect with a bounded backoff and jitter.
- If the chosen relay is congested or rejects the circuit due resource limits, try the next candidate.
- Do not send every request to all relays. Duplicate relay fan-out wastes bandwidth and may cause non-idempotent account operations to run twice.
- Account operations carry unique request IDs and the account API enforces idempotency where retries could otherwise duplicate work.

## Data security

- Use authenticated end-to-end encryption between the app peer and the administrator phone. The relay transports ciphertext only.
- Keep account passwords, password hashes, user tokens, admin tokens, signing secrets, account database rows, and ban commands out of relay storage.
- Bind a device public key to an authenticated user account. Admission is automatic only after the peer key is authenticated and the account is valid and not banned.
- Relay operators can still see peer IDs, public network metadata, connection timing, and traffic volume; relay use is not anonymous.

## Availability policy

Public/free relays are best effort, not a guaranteed free service. Nodes may disappear, restrict reservations, apply bandwidth/time limits, or be unreachable from some mobile carriers. The client should never claim universal coverage. When all known candidates fail, show a clear unavailable state and retry later.

## Current implementation status

This document is a target design. The repository currently has an Android LAN discovery milestone and a phone-hosted account API under development. Multi-relay discovery, Circuit Relay v2 reservations, authenticated relay streams, automatic relay selection/failover, and real cross-carrier tests are not yet integrated. The plain local account listener must not be exposed to public relays; encrypted peer transport must be completed first.
