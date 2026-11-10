# Ae Cloud Account API (Cloudflare Workers + D1)

This is the cloud replacement for the old home-Wi-Fi-only account host. It implements the same mobile API paths used by the two Ae APKs:

- POST /v1/register
- POST /v1/login
- GET /v1/me
- POST /v1/profile
- POST /v1/admin/login
- GET /v1/admin/users?q=
- GET /v1/admin/users/{id}
- POST /v1/admin/users/{id}/ban

## Important

- Never commit passwords, API tokens, or private keys.
- Configure Worker secrets named `JWT_SECRET` (at least 32 random characters) and `ADMIN_PASSWORD` (at least 12 characters) in Cloudflare > Workers & Pages > your Worker > Settings > Variables and Secrets.
- Create a D1 database named `ae-accounts`, apply `schema.sql`, then add a D1 binding to the Worker with variable name `DB`.
- The admin login username is `admin`; the password is the `ADMIN_PASSWORD` secret.
- The Worker only returns account records to a valid admin token. User passwords are PBKDF2-SHA256 hashes and never included in API responses.
- The free plan has daily limits. When D1's daily row read/write allowance is reached, database requests fail until the daily reset.
- Test on multiple network types before distributing the new APKs. A public `workers.dev` address is not a guarantee of reachability from every ISP or VPN route.

## Dashboard-first deployment (phone-friendly)

1. In Cloudflare, create a D1 database named `ae-accounts`.
2. Open the database's SQL console and execute the contents of `schema.sql`.
3. Go to Workers & Pages and create a Worker named `ae-cloud-account-api`.
4. Deploy this folder's `src/index.js` as the Worker entry point (Cloudflare Git integration can deploy the repository using this folder as the root directory).
5. In Worker Settings > Bindings, add a D1 database binding: variable name `DB`, database `ae-accounts`.
6. In Worker Settings > Variables and Secrets, add secrets `JWT_SECRET` and `ADMIN_PASSWORD`, then deploy.
7. Confirm `https://<worker-name>.<account-subdomain>.workers.dev/health` returns `{ "ok": true, ... }`.

Do not use the old LAN server APK or old main APK for nationwide accounts. Both APKs must be rebuilt to use the deployed HTTPS Worker URL.
