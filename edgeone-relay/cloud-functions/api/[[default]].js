/**
 * EffectCraft account HTTPS relay for EdgeOne Makers Cloud Functions.
 *
 * Fixed upstream: Cloudflare Workers. Never accept an upstream URL from a
 * client request; that would turn this endpoint into an open proxy / SSRF risk.
 *
 * Configure the project environment variable:
 *   CLOUDFLARE_API_ORIGIN=https://<worker-name>.<workers-dev-subdomain>.workers.dev
 */
const ALLOWED_METHODS = new Set(["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]);
const MAX_BODY_BYTES = 64 * 1024;
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
  "Access-Control-Max-Age": "600",
  "Cache-Control": "no-store",
};

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...CORS_HEADERS,
      ...extraHeaders,
    },
  });
}

function normalizeOrigin(value) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error("Cloudflare API origin is not configured");
  }
  const url = new URL(value.trim());
  if (url.protocol !== "https:" || url.username || url.password ||
      url.search || url.hash || url.pathname !== "/" ||
      !url.hostname.endsWith(".workers.dev")) {
    throw new Error("CLOUDFLARE_API_ORIGIN must be an HTTPS workers.dev origin without a path");
  }
  return url.origin;
}

function isAllowedPath(path) {
  if (path === "/health") return true;
  if (path === "/v1/register" || path === "/v1/login" ||
      path === "/v1/me" || path === "/v1/profile" ||
      path === "/v1/admin/login" || path === "/v1/admin/users") {
    return true;
  }
  return /^\/v1\/admin\/users\/[A-Za-z0-9_-]+(?:\/(?:ban|unban))?$/.test(path);
}

export default async function onRequest(context) {
  const request = context.request;
  const incoming = new URL(request.url);
  const apiPath = incoming.pathname.replace(/^\/api(?=\/|$)/, "") || "/";

  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: CORS_HEADERS,
    });
  }

  if (!ALLOWED_METHODS.has(request.method)) {
    return json({ ok: false, error: "Method not allowed" }, 405, {
      Allow: "GET, POST, PATCH, PUT, DELETE, OPTIONS",
    });
  }

  if (apiPath === "/_relay-health" && request.method === "GET") {
    let configured = false;
    try {
      normalizeOrigin(context.env.CLOUDFLARE_API_ORIGIN);
      configured = true;
    } catch {}
    return json({
      ok: true,
      service: "EffectCraft EdgeOne Relay",
      upstreamConfigured: configured,
      region: context.server?.region ?? null,
    });
  }

  // WebSocket upgrades require a separately supported, persistent duplex
  // transport. Do not silently downgrade live events to ordinary HTTP.
  if (apiPath === "/v1/events" || apiPath === "/v1/nodes/events") {
    return json({
      ok: false,
      error: "WebSocket event relay is not enabled in this HTTP test relay",
    }, 501);
  }

  if (!isAllowedPath(apiPath)) {
    return json({ ok: false, error: "API path is not allowed" }, 404);
  }

  let origin;
  try {
    origin = normalizeOrigin(context.env.CLOUDFLARE_API_ORIGIN);
  } catch (error) {
    return json({ ok: false, error: error.message }, 503);
  }

  let body;
  if (!["GET", "HEAD"].includes(request.method)) {
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return json({ ok: false, error: "Request body exceeds 64 KiB test limit" }, 413);
    }
  }

  const target = new URL(apiPath, origin);
  target.search = incoming.search;

  const headers = new Headers();
  for (const name of ["accept", "content-type", "authorization"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("Cache-Control", "no-store");
  headers.set("X-EffectCraft-Relay", "edgeone");

  try {
    const upstream = await fetch(target.toString(), {
      method: request.method,
      headers,
      body,
      redirect: "manual",
      signal: AbortSignal.timeout(25_000),
    });

    const responseHeaders = {
      ...CORS_HEADERS,
      "X-EffectCraft-Relay": "edgeone",
    };
    for (const name of ["content-type", "retry-after", "www-authenticate"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders[name] = value;
    }

    const responseBody = request.method === "HEAD" || upstream.status === 204
      ? null
      : upstream.body;

    return new Response(responseBody, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    return json({
      ok: false,
      error: "Cloudflare upstream request failed",
      detail: error?.name === "TimeoutError" ? "upstream timeout" : "upstream connection error",
    }, 502);
  }
}
