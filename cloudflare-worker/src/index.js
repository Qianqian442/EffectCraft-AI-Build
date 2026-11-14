import { AccountSessionHub } from "./account_session_hub.js";
import { NodeNetworkHub } from "./node_network_hub.js";
export { AccountSessionHub, NodeNetworkHub };

const encoder = new TextEncoder();
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "Authorization,Content-Type",
};

function response(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}
function fail(status, message, extra = {}) {
  return response({ detail: { message, ...extra } }, status);
}
async function accountServiceEnabled(env) {
  const row = await env.DB.prepare("SELECT enabled FROM account_service_state WHERE id = 1").first();
  return !row || Number(row.enabled) !== 0;
}
async function requireAccountServiceEnabled(env) {
  if (!(await accountServiceEnabled(env))) {
    throw new HttpError(503, "云端账号服务器当前已关闭，请联系管理员开启后重试");
  }
}
function bytesToB64Url(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function b64UrlToBytes(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(normalized + "=".repeat((4 - normalized.length % 4) % 4));
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}
function jsonPart(value) {
  return bytesToB64Url(encoder.encode(JSON.stringify(value)));
}
function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}
function randomBytes(size) {
  const out = new Uint8Array(size);
  crypto.getRandomValues(out);
  return out;
}

async function passwordCryptoRequest(env, path, body) {
  if (!env.ACCOUNT_SESSIONS) throw new Error("密码计算服务尚未绑定");
  const id = env.ACCOUNT_SESSIONS.idFromName("__ae_password_crypto__");
  const stub = env.ACCOUNT_SESSIONS.get(id);
  const res = await stub.fetch("https://account-session.internal" + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error("密码计算服务暂时不可用");
  return res.json();
}
async function passwordHash(env, password) {
  const result = await passwordCryptoRequest(env, "/password/hash", { password });
  if (!result.hash) throw new Error("密码哈希计算失败");
  return result.hash;
}
async function verifyPassword(env, password, stored) {
  const result = await passwordCryptoRequest(env, "/password/verify", { password, stored });
  return result.valid === true;
}
async function signingKey(secret) {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}
async function makeToken(env, subject, role, seconds) {
  if (!env.JWT_SECRET || env.JWT_SECRET.length < 32) throw new Error("JWT_SECRET 未正确设置");
  const now = Math.floor(Date.now() / 1000);
  const header = jsonPart({ alg: "HS256", typ: "JWT" });
  const payload = jsonPart({ sub: subject, role, iat: now, exp: now + seconds });
  const signingInput = header + "." + payload;
  const signature = await crypto.subtle.sign("HMAC", await signingKey(env.JWT_SECRET), encoder.encode(signingInput));
  return signingInput + "." + bytesToB64Url(new Uint8Array(signature));
}
async function readToken(env, request, requiredRole) {
  const value = request.headers.get("authorization") || "";
  if (!value.startsWith("Bearer ")) throw new AuthError("需要登录");
  const token = value.slice(7);
  const parts = token.split(".");
  if (parts.length !== 3) throw new AuthError("登录凭据无效");
  let payload;
  try {
    const input = parts[0] + "." + parts[1];
    const valid = await crypto.subtle.verify("HMAC", await signingKey(env.JWT_SECRET), b64UrlToBytes(parts[2]), encoder.encode(input));
    if (!valid) throw new Error("signature");
    payload = JSON.parse(new TextDecoder().decode(b64UrlToBytes(parts[1])));
  } catch (_) {
    throw new AuthError("登录凭据无效");
  }
  if (!payload.exp || payload.exp <= Math.floor(Date.now() / 1000)) throw new AuthError("登录已过期，请重新登录");
  if (payload.role !== requiredRole) throw new AuthError("无权访问");
  return payload;
}
class AuthError extends Error {}

function publicUser(row) {
  return {
    id: row.id,
    qq: row.qq || "",
    wechat: row.wechat || "",
    name: row.name,
    avatar_url: row.avatar_url || "",
    created_at: row.created_at,
    banned_until: row.banned_until || null,
    ban_reason: row.ban_reason || "",
  };
}
async function ensureNotBanned(db, row) {
  if (!row.banned_until) return null;
  if (String(row.banned_until).toLowerCase() === "permanent") {
    return { until: "permanent", reason: row.ban_reason || "未填写封禁原因", permanent: true, remaining_ms: -1, server_time_ms: Date.now() };
  }
  const until = Date.parse(row.banned_until);
  if (!Number.isFinite(until)) {
    return { until: row.banned_until, reason: row.ban_reason || "未填写封禁原因", permanent: false, remaining_ms: null, server_time_ms: Date.now() };
  }
  const remaining = until - Date.now();
  if (remaining <= 0) {
    await db.prepare("UPDATE accounts SET banned_until = NULL, ban_reason = '' WHERE id = ?").bind(row.id).run();
    return null;
  }
  return { until: row.banned_until, reason: row.ban_reason || "未填写封禁原因", permanent: false, remaining_ms: remaining, server_time_ms: Date.now() };
}
async function authResult(env, row, role, seconds) {
  return {
    token: await makeToken(env, row.id, role, seconds),
    expires_in: seconds,
    user: publicUser(row),
  };
}
async function readJson(request) {
  // Photo-picked avatars are embedded as a compact JPEG data URI (up to 96 KiB).
  // The JSON/base64 envelope needs more than the old 64 KiB limit.
  const maxBytes = 192 * 1024;
  const contentLength = Number(request.headers.get("content-length") || "0");
  if (contentLength > maxBytes) throw new HttpError(413, "请求内容过大");

  const reader = request.body && request.body.getReader ? request.body.getReader() : null;
  if (!reader) throw new HttpError(400, "请求数据为空");
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      total += part.value.byteLength;
      if (total > maxBytes) {
        try { await reader.cancel(); } catch (_) {}
        throw new HttpError(413, "请求内容过大");
      }
      chunks.push(part.value);
    }
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(400, "请求数据读取失败");
  }
  try {
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch (_) {
    throw new HttpError(400, "请求数据格式不正确");
  }
}
class HttpError extends Error {
  constructor(status, message, extra = {}) {
    super(message);
    this.status = status;
    this.extra = extra;
  }
}
function validateAvatar(value) {
  const avatar = String(value || "").trim();
  if (!avatar) return "";
  if (/^https?:\/\/\S+$/i.test(avatar)) {
    if (avatar.length > 8192) throw new HttpError(422, "头像图片地址过长");
    return avatar;
  }
  const prefix = "data:image/jpeg;base64,";
  if (!avatar.startsWith(prefix)) throw new HttpError(422, "头像只支持 JPG 相册图片或 HTTP(S) 图片地址");
  const encoded = avatar.slice(prefix.length);
  if (!encoded || encoded.length > 131072 || encoded.length % 4 !== 0
      || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    throw new HttpError(422, "相册头像数据格式不正确或超过96KB");
  }
  let bytes;
  try {
    const binary = atob(encoded);
    bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch (_) {
    throw new HttpError(422, "相册头像 Base64 数据无效");
  }
  if (bytes.length < 3 || bytes.length > 96 * 1024
      || bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes[2] !== 0xff) {
    throw new HttpError(422, "头像必须是有效的 JPEG 图片且不超过96KB");
  }
  return avatar;
}

function validateRegistration(body) {
  const rawQQ = String(body.qq || "").trim();
  const rawWechat = String(body.wechat || "").trim();
  const name = String(body.name || "").trim();
  const password = String(body.password || "");
  const avatar = validateAvatar(body.avatar_url);
  if (!rawQQ && !rawWechat) throw new HttpError(422, "QQ号和微信号至少填写一项");
  if (rawQQ && !/^[1-9][0-9]{4,11}$/.test(rawQQ)) throw new HttpError(422, "QQ号应填写5至12位数字");
  if (rawWechat && !/^[A-Za-z][A-Za-z0-9_-]{5,31}$/.test(rawWechat)) throw new HttpError(422, "微信号格式不正确");
  if (!name || name.length > 40) throw new HttpError(422, "姓名不能为空且不能超过40字");
  if (password.length < 8 || password.length > 128) throw new HttpError(422, "密码至少8位");
  return { qq: rawQQ || null, wechat: rawWechat || null, name, password, avatar };
}
async function register(request, env) {
  await requireAccountServiceEnabled(env);
  const body = validateRegistration(await readJson(request));
  const id = crypto.randomUUID();
  const hash = await passwordHash(env, body.password);
  const created = new Date().toISOString();
  try {
    await env.DB.prepare(
      "INSERT INTO accounts (id, qq, wechat, name, password_hash, avatar_url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
    ).bind(id, body.qq, body.wechat, body.name, hash, body.avatar, created).run();
  } catch (_) {
    return fail(409, "QQ号或微信号已注册");
  }
  const row = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(id).first();
  return response(await authResult(env, row, "user", 30 * 24 * 60 * 60), 201);
}
async function login(request, env) {
  await requireAccountServiceEnabled(env);
  const body = await readJson(request);
  const identifier = String(body.identifier || "").trim();
  const password = String(body.password || "");
  if (!identifier || !password) return fail(422, "请填写QQ号/微信号和密码");
  const row = await env.DB.prepare(
    "SELECT * FROM accounts WHERE qq = ? OR lower(wechat) = lower(?) LIMIT 1"
  ).bind(identifier, identifier).first();
  if (!row || !(await verifyPassword(env, password, row.password_hash))) return fail(401, "QQ号/微信号或密码错误");
  const banned = await ensureNotBanned(env.DB, row);
  if (banned) return fail(423, "账号已被封禁", banned);
  return response(await authResult(env, row, "user", 30 * 24 * 60 * 60));
}
async function me(request, env) {
  await requireAccountServiceEnabled(env);
  const claims = await readToken(env, request, "user");
  const row = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(claims.sub).first();
  if (!row) return fail(401, "账号不存在，请重新注册");
  const banned = await ensureNotBanned(env.DB, row);
  if (banned) return fail(423, "账号已被封禁", banned);
  return response({ user: publicUser(row) });
}
async function updateProfile(request, env) {
  await requireAccountServiceEnabled(env);
  const claims = await readToken(env, request, "user");
  const body = await readJson(request);
  const row = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(claims.sub).first();
  if (!row) return fail(401, "账号不存在");
  const banned = await ensureNotBanned(env.DB, row);
  if (banned) return fail(423, "账号已被封禁", banned);
  const rawQQ = String(body.qq || "").trim();
  const rawWechat = String(body.wechat || "").trim();
  const qq = rawQQ || null;
  const wechat = rawWechat || null;
  const name = String(body.name || "").trim();
  let avatar;
  try { avatar = validateAvatar(body.avatar_url); }
  catch (error) { return fail(error.status || 422, error.message || "头像格式不正确"); }
  if ((!rawQQ && !rawWechat)
      || (rawQQ && !/^[1-9][0-9]{4,11}$/.test(rawQQ))
      || (rawWechat && !/^[A-Za-z][A-Za-z0-9_-]{5,31}$/.test(rawWechat))
      || !name || name.length > 40) {
    return fail(422, "QQ号和微信号至少填写一项，且已填写的账号格式必须正确");
  }
  let newHash = row.password_hash;
  const newPassword = String(body.new_password || "");
  if (newPassword) {
    if (newPassword.length < 8 || newPassword.length > 128) return fail(422, "新密码至少8位");
    if (!(await verifyPassword(env, String(body.current_password || ""), row.password_hash))) return fail(401, "当前密码不正确");
    newHash = await passwordHash(env, newPassword);
  }
  try {
    await env.DB.prepare(
      "UPDATE accounts SET qq = ?, wechat = ?, name = ?, avatar_url = ?, password_hash = ? WHERE id = ?"
    ).bind(qq, wechat, name, avatar, newHash, claims.sub).run();
  } catch (_) {
    return fail(409, "QQ号或微信号已被其他账号使用");
  }
  const updated = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(claims.sub).first();
  return response({ user: publicUser(updated) });
}

async function adminServerState(request, env) {
  await readToken(env, request, "admin");
  const row = await env.DB.prepare("SELECT enabled, updated_at, updated_by FROM account_service_state WHERE id = 1").first();
  return response({ enabled: !row || Number(row.enabled) !== 0, updated_at: row && row.updated_at || null, updated_by: row && row.updated_by || "system" });
}
async function adminSetServerState(request, env) {
  const claims = await readToken(env, request, "admin");
  const body = await readJson(request);
  if (typeof body.enabled !== "boolean") return fail(422, "enabled 必须是布尔值");
  const updatedAt = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO account_service_state (id, enabled, updated_at, updated_by) VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at, updated_by = excluded.updated_by"
  ).bind(body.enabled ? 1 : 0, updatedAt, claims.sub).run();
  return response({ enabled: body.enabled, updated_at: updatedAt, updated_by: claims.sub });
}
async function adminLogin(request, env) {
  const body = await readJson(request);
  const username = String(body.username || "");
  const password = String(body.password || "");
  if (!env.ADMIN_PASSWORD || env.ADMIN_PASSWORD.length < 12) return fail(503, "管理员密码尚未在云端设置");
  if (username !== "admin" || password !== env.ADMIN_PASSWORD) return fail(401, "管理员账号或密码错误");
  return response({
    token: await makeToken(env, "admin", "admin", 8 * 60 * 60),
    expires_in: 8 * 60 * 60,
  });
}
async function adminUsers(request, env, url) {
  await readToken(env, request, "admin");
  const query = (url.searchParams.get("q") || "").trim().toLowerCase().slice(0, 80);
  const totalRow = await env.DB.prepare("SELECT COUNT(*) AS total_count FROM accounts").first();
  const totalCount = Number(totalRow && totalRow.total_count || 0);
  let result;
  let filteredCount = totalCount;
  if (query) {
    const like = "%" + query.replace(/[%_\\]/g, "\\$&") + "%";
    const countRow = await env.DB.prepare(
      "SELECT COUNT(*) AS filtered_count FROM accounts WHERE qq LIKE ? ESCAPE '\\' OR lower(wechat) LIKE ? ESCAPE '\\' OR lower(name) LIKE ? ESCAPE '\\'"
    ).bind(like, like, like).first();
    filteredCount = Number(countRow && countRow.filtered_count || 0);
    result = await env.DB.prepare(
      "SELECT id, qq, wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts WHERE qq LIKE ? ESCAPE '\\' OR lower(wechat) LIKE ? ESCAPE '\\' OR lower(name) LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT 500"
    ).bind(like, like, like).all();
  } else {
    result = await env.DB.prepare(
      "SELECT id, qq, wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts ORDER BY created_at DESC LIMIT 500"
    ).all();
  }
  const users = result.results || [];
  // Keep the visible admin list consistent with automatic expiry even when a
  // banned account has not attempted to log in since its temporary ban elapsed.
  for (const row of users) {
    const ban = await ensureNotBanned(env.DB, row);
    if (!ban) {
      row.banned_until = null;
      row.ban_reason = "";
    }
  }
  return response({ users, total_count: totalCount, filtered_count: filteredCount, limit: 500 });
}
async function adminUser(request, env, id) {
  await readToken(env, request, "admin");
  const row = await env.DB.prepare(
    "SELECT id, qq, wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts WHERE id = ?"
  ).bind(id).first();
  if (!row) return fail(404, "账号不存在");
  return response({ user: row });
}

async function revokeNodeAccount(env, accountId, reason = "account banned") {
  const stub = await nodeNetworkStub(env);
  const res = await stub.fetch("https://node-network.internal/revoke-node", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ node_id: accountId, reason })
  });
  if (!res.ok) throw new Error("节点会话撤销失败");
  const result = await res.json();
  return Number(result.revoked || 0);
}

async function notifyAccountStatus(env, accountId, status, bannedUntil = null, reason = "") {
  const id = env.ACCOUNT_SESSIONS.idFromName(accountId);
  const stub = env.ACCOUNT_SESSIONS.get(id);
  const changedAt = new Date().toISOString();
  const res = await stub.fetch("https://account-session.internal/notify", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      type: "account_status_changed",
      status,
      banned_until: bannedUntil,
      until: bannedUntil,
      remaining_ms: status !== "banned" ? 0 : (String(bannedUntil || "").toLowerCase() === "permanent" ? -1 : Math.max(0, Date.parse(String(bannedUntil || "")) - Date.now())),
      server_time_ms: Date.now(),
      reason: status === "banned" ? reason : "",
      changed_at: changedAt
    })
  });
  if (!res.ok) return 0;
  const result = await res.json();
  return Number(result.delivered || 0);
}

async function accountEvents(request, env) {
  await requireAccountServiceEnabled(env);
  const claims = await readToken(env, request, "user");
  if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
    return fail(426, "需要 WebSocket 连接");
  }
  const id = env.ACCOUNT_SESSIONS.idFromName(claims.sub);
  // Forward the original Upgrade request intact; constructing a new Request can
  // drop platform-specific WebSocket upgrade metadata.
  return env.ACCOUNT_SESSIONS.get(id).fetch(request);
}

async function adminBan(request, env, id) {
  await readToken(env, request, "admin");
  const body = await readJson(request);
  const existing = await env.DB.prepare("SELECT id FROM accounts WHERE id = ?").bind(id).first();
  if (!existing) return fail(404, "账号不存在");
  const until = body.banned_until;
  let status;
  let bannedUntil = null;
  if (until === null || until === undefined || until === "") {
    await env.DB.prepare("UPDATE accounts SET banned_until = NULL, ban_reason = '' WHERE id = ?").bind(id).run();
    status = "unbanned";
  } else {
    const reason = String(body.reason || "").trim();
    if (!reason || reason.length > 200) return fail(422, "请填写封禁原因（最多200字）");
    if (String(until).toLowerCase() === "permanent") {
      bannedUntil = "permanent";
    } else {
      const timestamp = Date.parse(String(until));
      if (!Number.isFinite(timestamp) || timestamp <= Date.now()) return fail(422, "封禁时间必须晚于当前时间");
      bannedUntil = new Date(timestamp).toISOString();
    }
    await env.DB.prepare("UPDATE accounts SET banned_until = ?, ban_reason = ? WHERE id = ?")
      .bind(bannedUntil, reason, id).run();
    status = "banned";
  }
  // The database update is authoritative. A ban also revokes the account's
  // live node-network socket immediately; reconnects are rejected by the
  // active-account check in nodeNetworkEvents.
  let revokedNodeSessions = 0;
  if (status === "banned") {
    try {
      revokedNodeSessions = await revokeNodeAccount(env, id, "account banned");
    } catch (error) {
      console.error("node-revocation-error", error && error.message ? error.message : String(error));
    }
  }
  // Push one event to connected Ae clients; each client then performs /v1/me.
  let notified = 0;
  try {
    notified = await notifyAccountStatus(env, id, status, bannedUntil, status === "banned" ? String(body.reason || "").trim() : "");
  } catch (error) {
    console.error("account-notification-error", error && error.message ? error.message : String(error));
  }
  const row = await env.DB.prepare(
    "SELECT id, qq, wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts WHERE id = ?"
  ).bind(id).first();
  return response({ user: row, notification_delivered: notified, revoked_node_sessions: revokedNodeSessions });
}
async function nodeNetworkStub(env) {
  if (!env.NODE_NETWORK) throw new HttpError(503, "节点网络服务尚未部署");
  const id = env.NODE_NETWORK.idFromName("global-effectcraft-node-network");
  return env.NODE_NETWORK.get(id);
}

async function adminNetworkState(request, env) {
  await readToken(env, request, "admin");
  const stub = await nodeNetworkStub(env);
  return stub.fetch("https://node-network.internal/state");
}

async function adminSetNetworkState(request, env) {
  const claims = await readToken(env, request, "admin");
  const body = await readJson(request);
  if (typeof body.enabled !== "boolean") return fail(422, "enabled 必须是布尔值");
  const stub = await nodeNetworkStub(env);
  return stub.fetch("https://node-network.internal/set-state", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ enabled: body.enabled, changed_by: claims.sub })
  });
}

async function requireActiveAccount(env, accountId) {
  await requireAccountServiceEnabled(env);
  const row = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(accountId).first();
  if (!row) throw new HttpError(401, "账号不存在，请重新登录");
  const banned = await ensureNotBanned(env.DB, row);
  if (banned) throw new HttpError(423, "账号已被管理员封禁", banned);
  return row;
}

async function nodeNetworkState(request, env) {
  const claims = await readToken(env, request, "user");
  await requireActiveAccount(env, claims.sub);
  const stub = await nodeNetworkStub(env);
  return stub.fetch("https://node-network.internal/state");
}

async function nodeNetworkEvents(request, env) {
  const claims = await readToken(env, request, "user");
  await requireActiveAccount(env, claims.sub);
  if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
    return fail(426, "需要 WebSocket 连接");
  }
  const stub = await nodeNetworkStub(env);
  const target = new URL(request.url);
  target.pathname = "/connect";
  target.search = "";
  target.searchParams.set("node_id", claims.sub);
  // Preserve the incoming WebSocket upgrade while adding the identity that
  // was verified from the bearer token above.
  return stub.fetch(new Request(target.toString(), request));
}

async function adminNetworkNodes(request, env) {
  await readToken(env, request, "admin");
  const stub = await nodeNetworkStub(env);
  return stub.fetch("https://node-network.internal/nodes");
}

async function route(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });
  if (request.method === "GET" && url.pathname === "/health") {
    if (!env.DB) {
      return response({ ok: false, service: "Ae Cloud Account API", database: false }, 503);
    }
    try {
      const probe = await env.DB.prepare("SELECT 1 AS connected").first();
      const connected = Number(probe && probe.connected) === 1;
      return response(
        { ok: connected, service: "Ae Cloud Account API", database: connected },
        connected ? 200 : 503
      );
    } catch (error) {
      console.error("health-database-error", error && error.message ? error.message : String(error));
      return response({ ok: false, service: "Ae Cloud Account API", database: false }, 503);
    }
  }
  if (!env.DB) return fail(503, "云端数据库尚未绑定");
  try {
    if (request.method === "GET" && url.pathname === "/v1/events") return await accountEvents(request, env);
    if (request.method === "GET" && url.pathname === "/v1/nodes/network") return await nodeNetworkState(request, env);
    if (request.method === "GET" && url.pathname === "/v1/nodes/events") return await nodeNetworkEvents(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/network") return await adminNetworkState(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/network") return await adminSetNetworkState(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/network/nodes") return await adminNetworkNodes(request, env);
    if (request.method === "POST" && url.pathname === "/v1/register") return await register(request, env);
    if (request.method === "POST" && url.pathname === "/v1/login") return await login(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/login") return await adminLogin(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/server") return await adminServerState(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/server") return await adminSetServerState(request, env);
    if (request.method === "GET" && url.pathname === "/v1/me") return await me(request, env);
    if (request.method === "POST" && url.pathname === "/v1/profile") return await updateProfile(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/users") return await adminUsers(request, env, url);
    const match = url.pathname.match(/^\/v1\/admin\/users\/([^/]+)(?:\/(ban))?$/);
    if (match && request.method === "GET" && !match[2]) return await adminUser(request, env, decodeURIComponent(match[1]));
    if (match && request.method === "POST" && match[2] === "ban") return await adminBan(request, env, decodeURIComponent(match[1]));
    return fail(404, "未找到请求接口");
  } catch (error) {
    if (error instanceof AuthError) return fail(401, error.message);
    if (error instanceof HttpError) return fail(error.status, error.message, error.extra);
    console.error("account-api-error", error && error.message ? error.message : String(error));
    return fail(500, "服务器暂时无法处理请求");
  }
}
export default {
  async fetch(request, env) {
    return route(request, env);
  },
};
