/**
 * Cross-network node presence and opaque relay.
 * The Worker authenticates the account before upgrading the socket. It only
 * routes bounded ciphertext envelopes; it must never receive plaintext jobs,
 * account credentials, or private device keys.
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
        enabled: true, changed_at: null, changed_by: "bootstrap"
      };
      return Response.json({ network: state });
    }
    if (url.pathname === "/nodes" && request.method === "GET") {
      const nodes = this.ctx.getWebSockets().map((socket) => {
        const a = socket.deserializeAttachment() || {};
        return { node_id: a.nodeId || "unknown", connected_at: a.connectedAt || null };
      });
      return Response.json({ enabled: (await this.ctx.storage.get("network_state"))?.enabled !== false, nodes });
    }
    if (url.pathname === "/revoke-node" && request.method === "POST") {
      const body = await request.json().catch(() => null);
      const nodeId = String(body?.node_id || "");
      if (!/^[a-f0-9-]{16,80}$/i.test(nodeId)) return Response.json({ error: "invalid node identity" }, { status: 400 });
      const reason = String(body?.reason || "node access revoked").slice(0, 120);
      let revoked = 0;
      for (const socket of this.ctx.getWebSockets()) {
        const a = socket.deserializeAttachment() || {};
        if (a.nodeId !== nodeId) continue;
        try { socket.send(JSON.stringify({ type: "node_access_revoked", reason })); } catch (_) {}
        try { socket.close(4003, "account access revoked"); revoked++; } catch (_) {}
      }
      return Response.json({ revoked });
    }
    if (url.pathname === "/set-state" && request.method === "POST") {
      const body = await request.json().catch(() => null);
      if (!body || typeof body.enabled !== "boolean" || !body.changed_by) {
        return Response.json({ error: "invalid network state" }, { status: 400 });
      }
      const state = { enabled: body.enabled, changed_at: new Date().toISOString(), changed_by: String(body.changed_by).slice(0, 80) };
      await this.ctx.storage.put("network_state", state);
      const sockets = this.ctx.getWebSockets();
      const disconnected = state.enabled ? 0 : sockets.length;
      const payload = JSON.stringify({ type: "network_state", ...state });
      for (const socket of sockets) {
        try { socket.send(payload); if (!state.enabled) socket.close(4001, "network disabled by administrator"); }
        catch (_) { try { socket.close(1011, "network state update failed"); } catch (_) {} }
      }
      return Response.json({ network: state, disconnected });
    }
    if (url.pathname === "/connect" && request.method === "GET") {
      if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
        return new Response("WebSocket upgrade required", { status: 426 });
      }
      const nodeId = url.searchParams.get("node_id") || "";
      if (!/^[a-f0-9-]{16,80}$/i.test(nodeId)) return Response.json({ error: "invalid node identity" }, { status: 400 });
      const state = await this.ctx.storage.get("network_state") || { enabled: true };
      if (!state.enabled) return Response.json({ error: "node network disabled" }, { status: 423 });
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server);
      server.serializeAttachment({ nodeId, connectedAt: new Date().toISOString(), windowStart: Date.now(), windowCount: 0 });
      server.send(JSON.stringify({ type: "network_state", enabled: true, changed_at: state.changed_at || null }));
      return new Response(null, { status: 101, webSocket: client });
    }
    return new Response("Not found", { status: 404 });
  }

  async webSocketMessage(socket, message) {
    let a = socket.deserializeAttachment() || {};
    if (message === "ping") {
      try { socket.send("pong"); } catch (_) {}
      return;
    }
    if (typeof message !== "string" || message.length > 50000) {
      try { socket.send(JSON.stringify({ type: "error", code: "invalid_frame" })); } catch (_) {}
      return;
    }
    let packet;
    try { packet = JSON.parse(message); } catch (_) {
      try { socket.send(JSON.stringify({ type: "error", code: "invalid_json" })); } catch (_) {}
      return;
    }
    // Relay only opaque end-to-end ciphertext. Device-side key agreement,
    // encryption, signature validation and trust approval are required before
    // production use; this relay does not claim to provide those functions.
    if (packet?.type !== "relay" || packet.v !== 1 ||
        !/^[a-f0-9-]{16,80}$/i.test(String(packet.to || "")) ||
        !/^[a-f0-9-]{16,80}$/i.test(String(packet.message_id || "")) ||
        typeof packet.ciphertext !== "string" ||
        packet.ciphertext.length < 16 || packet.ciphertext.length > 40000) {
      try { socket.send(JSON.stringify({ type: "error", code: "invalid_relay_envelope" })); } catch (_) {}
      return;
    }
    const sentAt = Date.parse(String(packet.sent_at || ""));
    if (!Number.isFinite(sentAt) || Math.abs(Date.now() - sentAt) > 120000) {
      try { socket.send(JSON.stringify({ type: "error", code: "expired_message" })); } catch (_) {}
      return;
    }
    const now = Date.now();
    if (now - Number(a.windowStart || 0) >= 60000) {
      a.windowStart = now; a.windowCount = 0;
    }
    a.windowCount = Number(a.windowCount || 0) + 1;
    if (a.windowCount > 30) {
      socket.serializeAttachment(a);
      try { socket.send(JSON.stringify({ type: "error", code: "rate_limited" })); } catch (_) {}
      return;
    }
    socket.serializeAttachment(a);
    const duplicateKey = "relay:" + a.nodeId + ":" + packet.message_id;
    if (await this.ctx.storage.get(duplicateKey)) {
      try { socket.send(JSON.stringify({ type: "error", code: "duplicate_message" })); } catch (_) {}
      return;
    }
    await this.ctx.storage.put(duplicateKey, true, { expirationTtl: 180 });
    const state = await this.ctx.storage.get("network_state") || { enabled: true };
    if (!state.enabled) {
      try { socket.send(JSON.stringify({ type: "error", code: "network_disabled" })); } catch (_) {}
      return;
    }
    const targets = this.ctx.getWebSockets();
    let delivered = 0;
    for (const target of targets) {
      if (target === socket) continue;
      const recipient = target.deserializeAttachment() || {};
      if (recipient.nodeId !== packet.to) continue;
      try {
        target.send(JSON.stringify({
          type: "relay",
          v: 1,
          from: a.nodeId,
          to: packet.to,
          message_id: packet.message_id,
          sent_at: packet.sent_at,
          ciphertext: packet.ciphertext
        }));
        delivered++;
      } catch (_) { try { target.close(1011, "relay delivery failed"); } catch (_) {} }
    }
    try {
      socket.send(JSON.stringify({ type: "relay_ack", message_id: packet.message_id, delivered }));
    } catch (_) {}
  }

  webSocketClose(socket, code, reason) {
    try { socket.close(code, reason); } catch (_) {}
  }
}
