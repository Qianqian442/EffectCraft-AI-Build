# Ae Cloud Account API (Cloudflare Workers + D1 + Durable Objects)

This service provides the cloud account features used by the two Ae APKs: registration, login, profile management, administrator account search, bans and unbans. Video editing, export, RIFE interpolation, Real-ESRGAN enhancement, WASM effects and local media operations remain on-device and do not call this Worker.

## API

- `POST /v1/register`
- `POST /v1/login`
- `GET /v1/me`
- `POST /v1/profile`
- `GET /v1/events` (authenticated WebSocket)
- `POST /v1/admin/login`
- `GET /v1/admin/users?q=`
- `GET /v1/admin/users/{id}`
- `POST /v1/admin/users/{id}/ban`

## Public-proxy account transport

The Android clients may reach this Worker directly over HTTPS or use a public HTTP CONNECT / SOCKS5 proxy only as a byte tunnel when direct access fails. The destination remains this Worker and D1 remains the authoritative account store.

- The clients validate the Worker's HTTPS/WSS certificate and hostname end-to-end. They do not trust proxy-provided CA certificates and never downgrade account requests to plaintext HTTP.
- Public proxy feeds are untrusted discovery data. A candidate is used only after a real `GET /health` check succeeds through that tunnel.
- A proxy operator can still observe the Worker hostname, connection time and traffic volume. It must not receive decrypted passwords, JWTs or account request bodies.
- The clients do not automatically replay a registration, profile update, ban or unban POST if the connection fails after submission, because the Worker may already have applied it.
- Public proxy availability and mainland carrier reachability are not guaranteed. Test with the target mobile carriers before wide distribution.
- This is client-side transport selection only. The Worker does not act as an open proxy and does not accept a client-supplied upstream URL.

## Ban/unban behavior

1. The administrator request immediately updates the authoritative account row in D1.
2. The Worker sends one event to the account-specific SQLite Durable Object.
3. The Durable Object pushes the event to any live Ae WebSocket sessions for that account.
4. An online Ae client receives the event and performs one `GET /v1/me` verification. A ban locks the editor; an unban restores access.
5. The Durable Object remembers the latest ban/unban state. When Ae reconnects, it replays that state; the client checks its current state and calls `/v1/me` only when the state differs. This catches notifications missed during a disconnect.
6. A device that is offline, has lost network access, or whose Android process/socket has been suspended cannot receive a live push immediately. It verifies when it reconnects or next opens Ae.

There is no 10-second or 5-minute account polling. A launch performs one verification. Normal editing and local AI/export do not make account API calls.

PBKDF2-SHA256 password hashing (210,000 iterations) runs inside a Durable Object rather than the Workers Free 10 ms CPU budget. The original password is never stored; only a salted hash is stored in D1. Registration, login and password changes therefore also use a small number of Durable Object requests.

## Free-tier behavior

Workers, D1 and Durable Objects have separate usage limits. SQLite-backed Durable Objects are available on Workers Free; hibernating WebSocket connections avoid keeping an idle Durable Object active. Free-tier overages can cause requests of the affected type to fail until the daily reset. There is no guarantee that Cloudflare's free tier will remain available forever, or that a `workers.dev` hostname is reachable from every ISP/VPN route. Test from the intended Chinese networks before distributing widely.

## Deploy from GitHub Actions (phone-friendly)

The repository contains `.github/workflows/deploy-ae-cloud-account.yml`. The required repository **Actions secrets** are these three values:

- `CLOUDFLARE_API_TOKEN`: use the least-privilege Cloudflare permissions Account → Workers Scripts → **Edit** and Account → D1 → **Edit**. The token must belong to the same Cloudflare account whose Account ID is configured below. Restrict the resource selector to that account. Never paste this token into chat.
- `JWT_SECRET`: a randomly generated secret of at least 32 characters.
- `ADMIN_PASSWORD`: your private administrator password of at least 12 characters.

`CLOUDFLARE_ACCOUNT_ID` is **not required as a fourth secret**: the current deployment workflow has the already-configured account ID as a fallback (`6ed9bd81b9aef69ba61060f33510f014`). If you later add a `CLOUDFLARE_ACCOUNT_ID` repository secret, it overrides that fallback; do not add it merely to satisfy the old instructions.

The Worker name is `ae-cloud-account-api`. If it already exists in Workers & Pages, keep using it; do not create a duplicate. If it does not exist, the current least-privilege deployment path requires creating that empty Worker once in Cloudflare (Workers & Pages → Create application → Create Worker → Deploy) before the GitHub deployment workflow can update it. The D1 Database ID is already in `wrangler.jsonc` and should not be edited.

The workflow applies `schema.sql`, deploys the Worker and Durable Object migration, then sets `JWT_SECRET` and `ADMIN_PASSWORD` as Worker secrets. GitHub Actions masks secret values in logs. Keep all three secret values private.

After the run succeeds, open the deployment log to find the Worker `workers.dev` URL. It will look like:

`https://ae-cloud-account-api.<your-workers-dev-subdomain>.workers.dev`

Check that `https://...workers.dev/health` returns `{"ok":true,"service":"Ae Cloud Account API","database":true}`.


## Deployment verification note

A documentation-only update to this file can be used to start the repository's deployment workflow because the workflow watches `cloudflare-worker/**`. A successful run must show all of the following before the APK builds are dispatched:

1. D1 schema application completed.
2. Worker deployment printed the actual `workers.dev` URL.
3. Worker runtime secrets were configured.
4. `GET /health` returned `ok: true` and `database: true`.
5. The repository variable `AE_ACCOUNT_API_URL` was saved.

A successful GitHub-hosted health check confirms that the Worker and D1 are responding from the GitHub runner only. It does not prove mainland mobile-carrier reachability; test China Mobile, China Unicom, and China Telecom separately before claiming nationwide availability.

## Main APK build

After the actual Worker URL is known, set the repository Actions **variable** (not a secret) `AE_ACCOUNT_API_URL` to the exact base URL, for example `https://ae-cloud-account-api.<your-workers-dev-subdomain>.workers.dev`. The main APK workflow checks for this variable and only then runs the cloud-account conversion step. The admin APK accepts the same HTTPS URL in its server address field.

Do not distribute the previous LAN-only builds. Build and validate both cloud-connected APKs first.
