# Ae account API Pages gateway

This is an alternate public ingress for the existing `ae-cloud-account-api`
Worker. It does not implement account logic, store credentials, or create a
second database. A Cloudflare Pages Service binding forwards the incoming
request internally to the existing Worker.

The intent is to provide an alternate hostname because public measurements
show `workers.dev` is blocked on many mainland-China networks. `pages.dev`
is also inconsistently reachable, so this gateway is experimental until the
target OPPO / China network confirms it can open `/health`.

## Deployment

The GitHub Actions workflow creates the Pages project `ae-account-api-gateway`
and deploys the advanced-mode `dist/_worker.js` entrypoint. It uses a
Cloudflare API token with Pages Write / Edit permissions in addition to the
existing Worker deployment permissions.

The Pages Function binds `ACCOUNT_API` to the existing Worker
`ae-cloud-account-api`. All account routes, D1 data, Durable Objects,
password handling, JWTs and ban logic remain on the original Worker.

## Safety and validation

- Requests are forwarded only to the fixed Service binding; this is not an
  open proxy and does not accept a client-supplied upstream URL.
- HTTPS termination remains at Cloudflare. The Android clients must continue
  validating the Pages hostname certificate and preserve the authenticated
  account API request semantics.
- `GET /health` must return the same Worker health response before the APK
  uses this endpoint.
- No registration or login POST is replayed by this gateway.
- A successful GitHub deployment is not proof of mainland reachability.
  Validate the Pages hostname from the target China network before switching
  either APK to it.
