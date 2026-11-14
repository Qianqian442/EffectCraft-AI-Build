// Public Pages hostname used as an alternate ingress for the existing account Worker.
// The Service binding invokes the existing Worker inside Cloudflare without making
// a second public request to its workers.dev hostname.
export default {
  async fetch(request, env) {
    if (!env.ACCOUNT_API || typeof env.ACCOUNT_API.fetch !== "function") {
      return new Response(
        JSON.stringify({ ok: false, error: "account_api_binding_missing" }),
        {
          status: 503,
          headers: {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
          },
        },
      );
    }

    // Forward the original Request intact, including method, path, query,
    // Authorization, body, CORS preflight and WebSocket upgrade metadata.
    return env.ACCOUNT_API.fetch(request);
  },
};
