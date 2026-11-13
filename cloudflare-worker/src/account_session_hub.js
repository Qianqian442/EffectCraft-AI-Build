const encoder = new TextEncoder();

function bytesToB64Url(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/g, "");
}

function b64UrlToBytes(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(normalized + "=".repeat((4 - normalized.length % 4) % 4));
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function passwordHash(password, salt = crypto.getRandomValues(new Uint8Array(16))) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: 210000, hash: "SHA-256" },
    key,
    256
  );
  return "pbkdf2-sha256$210000$" + bytesToB64Url(salt) + "$" + bytesToB64Url(new Uint8Array(bits));
}

async function verifyPassword(password, stored) {
  try {
    const parts = String(stored || "").split("$");
    if (parts.length !== 4 || parts[0] !== "pbkdf2-sha256" || Number(parts[1]) !== 210000) return false;
    const actual = await passwordHash(password, b64UrlToBytes(parts[2]));
    return constantTimeEqual(encoder.encode(actual), encoder.encode(stored));
  } catch (_) {
    return false;
  }
}

// Per-account WebSocket hub. Connections hibernate while idle so an open Ae
// session does not require periodic polling or keep the Durable Object awake.
export class AccountSessionHub {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async fetch(request) {
    const url = new URL(request.url);

    // PBKDF2 is intentionally executed in a Durable Object rather than the
    // 10ms Workers Free request CPU budget. Durable Objects have a longer
    // per-request CPU allowance and this object keeps no password material.
    if (request.method === "POST" && url.pathname === "/password/hash") {
      const body = await request.json();
      const password = String(body.password || "");
      if (password.length < 8 || password.length > 128) {
        return Response.json({ error: "invalid password length" }, { status: 422 });
      }
      return Response.json({ hash: await passwordHash(password) });
    }

    if (request.method === "POST" && url.pathname === "/password/verify") {
      const body = await request.json();
      const password = String(body.password || "");
      const stored = String(body.stored || "");
      if (!password || !stored) return Response.json({ valid: false });
      return Response.json({ valid: await verifyPassword(password, stored) });
    }
    if (url.pathname === "/v1/events") {
      if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
        return new Response("WebSocket upgrade required", { status: 426 });
      }
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server);
      // Replay the most recent status on every new connection. The client
      // compares it with its just-verified state and only calls /v1/me if different.
      const lastStatus = await this.ctx.storage.get("last_status");
      if (lastStatus && ["banned", "unbanned"].includes(lastStatus.status)) {
        const expiry = String(lastStatus.banned_until || "");
        const permanent = expiry.toLowerCase() === "permanent";
        const remainingMs = lastStatus.status !== "banned"
          ? 0
          : (permanent ? -1 : Math.max(0, Date.parse(expiry) - Date.now()));
        server.send(JSON.stringify({
          type: "account_status_changed",
          status: lastStatus.status,
          banned_until: lastStatus.banned_until || null,
          until: lastStatus.banned_until || null,
          remaining_ms: remainingMs,
          server_time_ms: Date.now(),
          reason: lastStatus.reason || "",
          changed_at: lastStatus.changed_at || null
        }));
      }
      return new Response(null, { status: 101, webSocket: client });
    }

    if (url.pathname === "/notify" && request.method === "POST") {
      const event = await request.json();
      if (!event || event.type !== "account_status_changed" ||
          !["banned", "unbanned"].includes(event.status)) {
        return Response.json({ error: "invalid event" }, { status: 400 });
      }
      const expiry = String(event.banned_until || event.until || "");
      const permanent = expiry.toLowerCase() === "permanent";
      const remainingMs = event.status !== "banned"
        ? 0
        : (permanent ? -1 : Math.max(0, Date.parse(expiry) - Date.now()));
      const savedStatus = {
        status: event.status,
        banned_until: event.status === "banned" ? expiry : null,
        reason: event.status === "banned" ? String(event.reason || "") : "",
        changed_at: event.changed_at || new Date().toISOString()
      };
      await this.ctx.storage.put("last_status", savedStatus);
      const payload = JSON.stringify({
        ...event,
        remaining_ms: remainingMs,
        server_time_ms: Date.now()
      });
      let delivered = 0;
      for (const socket of this.ctx.getWebSockets()) {
        try {
          socket.send(payload);
          delivered++;
        } catch (_) {
          try { socket.close(1011, "notification failed"); } catch (_) {}
        }
      }
      return Response.json({ delivered });
    }

    return new Response("Not found", { status: 404 });
  }

  webSocketMessage(socket, message) {
    if (message === "ping") {
      try { socket.send("pong"); } catch (_) {}
    }
  }

  webSocketClose(socket, code, reason, wasClean) {
    try { socket.close(code, reason); } catch (_) {}
  }
}
