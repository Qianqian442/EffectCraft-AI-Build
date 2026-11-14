# EffectCraft EdgeOne HTTPS relay (test stage)

This folder is a small EdgeOne Makers project intended to test a mainland China HTTPS entry point that forwards a limited set of EffectCraft account API requests to the existing Cloudflare Worker.

## Important limitations

- This is a **connectivity test relay**, not a production account endpoint yet.
- For the free Makers plan, Cloud Functions use the default execution region (documented as Guangzhou, `ap-guangzhou`).
- Mainland access to Makers project/deployment domains currently requires a system-generated preview URL. The official docs say that preview URL is valid for 3 hours and must be refreshed from the Console. This is unsuitable as a permanent APK endpoint.
- The relay forwards normal HTTP account routes only. It intentionally does not forward `/v1/events` or `/v1/nodes/events` WebSocket connections. Real-time ban/unban delivery needs a separately verified duplex transport or an explicit polling/SSE design before this can be used by the two APKs.
- No account password, JWT secret, Cloudflare API token, or admin secret belongs in this repository.

## Project setup in EdgeOne Makers

1. Import the GitHub repository `Qianqian442/EffectCraft-AI-Build`.
2. Set **Root Directory** to `edgeone-relay`.
3. Use Node.js Cloud Functions / the default Node.js runtime.
4. Set the project environment variable `CLOUDFLARE_API_ORIGIN` to the exact Worker origin, for example `https://ae-cloud-account-api.<your-workers-dev-subdomain>.workers.dev`. Do not include a path, query, or trailing endpoint.
5. Deploy. For a test from a mainland network, generate and use the current **Preview** URL from the Makers Console.

## Test endpoints

- `GET /`: checks that the EdgeOne project is deployed.
- `GET /api/_relay-health`: checks that the relay handler runs and the Worker origin is configured.
- `GET /api/health`: forwards to the Cloudflare Worker `/health` endpoint. A healthy Cloudflare response should report `ok: true` and `database: true`.

The APK is not changed by this test. Do not put the preview URL into either APK because it expires after 3 hours.

## Security behavior

- The upstream origin is read only from the server-side environment variable; clients cannot choose a destination.
- Only a narrow allowlist of account API routes is forwarded.
- Only the Authorization, Accept and Content-Type request headers are forwarded.
- Request bodies are capped at 64 KiB for the connectivity test.
- Responses are marked no-store.
