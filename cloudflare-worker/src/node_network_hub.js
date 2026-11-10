/**
 * Server-authoritative global node gate and authenticated node presence.
 * This first stage deliberately does not relay peer payloads: peer-key pairing,
 * signature verification and replay protection must land before relay is enabled.
 */
export class NodeNetworkHub {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/state" && request.method === "GET") {
      const state = await this.ctx.storage.get("network_state") || {
        enabled: true,
        changed_at: null,
        changed_by: "bootstrap"
      };
      return Response.json({ network: state });
    }

    if (url.pathname === "/nodes" && request.method === "GET") {
      const sockets = this.ctx.getWebSockets();
      const nodes = [];
      for (const socket of sockets) {
        const attachment = socket.deserializeAttachment() || {};
        nodes.push({
          node_id: attachment.nodeId || "unknown",
          connected_at: attachment.connectedAt || null
        });
      }
      return Response.json({ enabled: (await this.ctx.storage.get("network_state"))?.enabled !== false, nodes });
    }

    if (url.pathname === "/revoke-node" && request.method === "POST") {
      const body = await request.json().catch(() => null);
      const nodeId = String(body?.node_id || "");
      if (!/^[a-f0-9-]{16,80}$/i.test(nodeId)) {
        return Response.json({ error: "invalid node identity" }, { status: 400 });
      }
      const reason = String(body?.reason || "node access revoked").slice(0, 120);
      let revoked = 0;
      for (const socket of this.ctx.getWebSockets()) {
        const attachment = socket.deserializeAttachment() || {};
        if (attachment.nodeId !== nodeId) continue;
        try {
          socket.send(JSON.stringify({ type: "node_access_revoked", reason }));
        } catch (_) {}
        try {
          socket.close(4003, "account access revoked");
          revoked++;
        } catch (_) {}
      }
      return Response.json({ revoked });
    }

    if (url.pathname === "/set-state" && request.method === "POST") {
      const body = await request.json().catch(() => null);
      if (!body || typeof body.enabled !== "boolean" || !body.changed_by) {
        return Response.json({ error: "invalid network state" }, { status: 400 });
      }
      const state = {
        enabled: body.enabled,
        changed_at: new Date().toISOString(),
        changed_by: String(body.changed_by).slice(0, 80)
      };
      await this.ctx.storage.put("network_state", state);
      const sockets = this.ctx.getWebSockets();
      const disconnected = state.enabled ? 0 : sockets.length;
      const payload = JSON.stringify({ type: "network_state", ...state });
      for (const socket of sockets) {
        try {
          socket.send(payload);
          if (!state.enabled) socket.close(4001, "network disabled by administrator");
        } catch (_) {
          try { socket.close(1011, "network state update failed"); } catch (_) {}
        }
      }
      // Count the sessions selected for shutdown before closing them. The
      // runtime may remove closed sockets from getWebSockets() immediately.
      return Response.json({ network: state, disconnected });
    }

    if (url.pathname === "/connect" && request.method === "GET") {
      if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
        return new Response("WebSocket upgrade required", { status: 426 });
      }
      const nodeId = url.searchParams.get("node_id") || "";
      if (!/^[a-f0-9-]{16,80}$/i.test(nodeId)) {
        return Response.json({ error: "invalid node identity" }, { status: 400 });
      }
      const state = await this.ctx.storage.get("network_state") || { enabled: true };
      if (!state.enabled) return Response.json({ error: "node network disabled" }, { status: 423 });
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server);
      server.serializeAttachment({ nodeId, connectedAt: new Date().toISOString() });
      server.send(JSON.stringify({ type: "network_state", enabled: true, changed_at: state.changed_at || null }));
      return new Response(null, { status: 101, webSocket: client });
    }

    return new Response("Not found", { status: 404 });
  }

  webSocketMessage(socket, message) {
    // Presence-only milestone: no arbitrary peer payload forwarding until
    // trusted-device pairing and message signature/replay checks are shipped.
    if (message === "ping") {
      try { socket.send("pong"); } catch (_) {}
      return;
    }
    try {
      socket.send(JSON.stringify({ type: "error", code: "relay_not_enabled", message: "安全配对与签名验证尚未完成，节点转发暂未开放" }));
    } catch (_) {}
  }

  webSocketClose(socket, code, reason) {
    try { socket.close(code, reason); } catch (_) {}
  }
}
