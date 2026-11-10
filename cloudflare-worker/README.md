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

The repository contains `.github/workflows/deploy-ae-cloud-account.yml`. Before running it, add these four repository **Actions secrets** at GitHub → repository → Settings → Secrets and variables → Actions → New repository secret:

- `CLOUDFLARE_API_TOKEN`: create a custom token with Account → Workers → **Admin** (needed because the workflow creates the first Worker and applies its Durable Object migration) and Account → D1 → **Edit** (needed to execute the schema on your database). Restrict the resource selector to your Cloudflare account. The Admin scope is broader than a deploy-to-existing-Worker Editor role, but is required for initial creation; after the first successful deployment you can replace it with a narrower token if desired. Never paste this token into chat.
- `CLOUDFLARE_ACCOUNT_ID`: the account ID shown in the Cloudflare dashboard URL.
- `JWT_SECRET`: a randomly generated secret of at least 32 characters.
- `ADMIN_PASSWORD`: your private administrator password of at least 12 characters.

The workflow applies `schema.sql`, deploys the Worker and Durable Object migration, then sets `JWT_SECRET` and `ADMIN_PASSWORD` as Worker secrets. GitHub Actions masks secret values in logs. Keep all four values private. The Account ID for the already-created Cloudflare account is `6ed9bd81b9aef69ba61060f33510f014`; the D1 Database ID is already in `wrangler.jsonc` and should not be edited.

After the run succeeds, open the deployment log to find the Worker `workers.dev` URL. It will look like:

`https://ae-cloud-account-api.<your-workers-dev-subdomain>.workers.dev`

Check that `https://...workers.dev/health` returns `{"ok":true,"service":"Ae Cloud Account API","database":true}`.

## Main APK build

After the actual Worker URL is known, set the repository Actions **variable** (not a secret) `AE_ACCOUNT_API_URL` to the exact base URL, for example `https://ae-cloud-account-api.<your-workers-dev-subdomain>.workers.dev`. The main APK workflow checks for this variable and only then runs the cloud-account conversion step. The admin APK accepts the same HTTPS URL in its server address field.

Do not distribute the previous LAN-only builds. Build and validate both cloud-connected APKs first.
