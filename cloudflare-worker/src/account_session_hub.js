// Per-account WebSocket hub. Connections hibernate while idle so an open Ae
// session does not require periodic polling or keep the Durable Object awake.
export class AccountSessionHub {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/v1/events") {
      if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
        return new Response("WebSocket upgrade required", { status: 426 });
      }
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server);
      // Every connection/reconnection is announced. A still-active ban is also
      // replayed so a launch race cannot miss a ban written just before connect.
      server.send(JSON.stringify({ type: "account_session_connected" }));
      const activeBan = await this.ctx.storage.get("active_ban");
      if (activeBan && Date.parse(activeBan.banned_until) > Date.now()) {
        server.send(JSON.stringify({
          type: "account_status_changed",
          status: "banned",
          banned_until: activeBan.banned_until
        }));
      } else if (activeBan) {
        await this.ctx.storage.delete("active_ban");
      }
      return new Response(null, { status: 101, webSocket: client });
    }

    if (url.pathname === "/notify" && request.method === "POST") {
      const event = await request.json();
      if (!event || event.type !== "account_status_changed" ||
          !["banned", "unbanned"].includes(event.status)) {
        return Response.json({ error: "invalid event" }, { status: 400 });
      }
      if (event.status === "banned" && typeof event.banned_until === "string") {
        await this.ctx.storage.put("active_ban", { banned_until: event.banned_until });
      } else {
        await this.ctx.storage.delete("active_ban");
      }
      const payload = JSON.stringify(event);
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
