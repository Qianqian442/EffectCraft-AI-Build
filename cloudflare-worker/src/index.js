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

async function sha256Hex(value) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
async function whitelistSnapshot(env) {
  const result = await env.DB.prepare(
    "SELECT kind, normalized_value, created_at FROM account_whitelist ORDER BY kind, normalized_value"
  ).all();
  const rows = result.results || [];
  const qq_hashes = [];
  const wechat_hashes = [];
  let latest = "";
  for (const row of rows) {
    const digest = await sha256Hex(String(row.kind) + ":" + String(row.normalized_value));
    if (row.kind === "qq") qq_hashes.push(digest);
    else if (row.kind === "wechat") wechat_hashes.push(digest);
    const created = String(row.created_at || "");
    if (created > latest) latest = created;
  }
  return { revision: String(rows.length) + ":" + latest, qq_hashes, wechat_hashes };
}
async function isWhitelistAllowed(db, kind, value) {
  const raw = String(value || "").trim();
  if (!raw) return false;
  const normalized = kind === "wechat" ? raw.toLowerCase() : raw;
  const row = await db.prepare(
    "SELECT id FROM account_whitelist WHERE kind = ? AND normalized_value = ? LIMIT 1"
  ).bind(kind, normalized).first();
  return !!row;
}
async function requireWhitelistedIdentifiers(db, qq, wechat) {
  const normalizedQq = String(qq || "").trim();
  const normalizedWechat = String(wechat || "").trim();
  if (!normalizedQq && !normalizedWechat) {
    throw new HttpError(422, "QQ号和微信号至少填写一项");
  }
  if (normalizedQq && !(await isWhitelistAllowed(db, "qq", normalizedQq))) {
    throw new HttpError(403, "QQ号不在白名单中，无法注册或登录", { code: "not_whitelisted", kind: "qq" });
  }
  if (normalizedWechat && !(await isWhitelistAllowed(db, "wechat", normalizedWechat))) {
    throw new HttpError(403, "微信号不在白名单中，无法注册或登录", { code: "not_whitelisted", kind: "wechat" });
  }
}
async function publicWhitelist(request, env) {
  return response(await whitelistSnapshot(env));
}

async function passwordCryptoRequest(env, path, body) {
  if (!env.ACCOUNT_SESSIONS) {
    console.error("password-crypto-binding-missing");
    throw new HttpError(503, "密码计算服务尚未就绪，请稍后重试", {
      code: "password_service_unavailable"
    });
  }
  try {
    const id = env.ACCOUNT_SESSIONS.idFromName("__ae_password_crypto__");
    const stub = env.ACCOUNT_SESSIONS.get(id);
    const res = await stub.fetch("https://account-session.internal" + path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      let upstreamBody = "";
      try { upstreamBody = (await res.text()).slice(0, 500); } catch (_) {}
      let upstreamCode = "";
      let upstreamErrorName = "";
      let upstreamErrorMessage = "";
      try {
        const upstream = JSON.parse(upstreamBody);
        upstreamCode = String(upstream.code || "");
        upstreamErrorName = String(upstream.error_name || "").slice(0, 80);
        upstreamErrorMessage = String(upstream.error_message || "").slice(0, 180);
      } catch (_) {}
      console.error("password-crypto-do-response", res.status, path, upstreamCode, upstreamErrorName, upstreamErrorMessage);
      const failure = new HttpError(503, "密码计算服务暂时不可用，请稍后重试", {
        code: "password_service_unavailable"
      });
      failure.diagnostic = {
        upstream_status: res.status,
        upstream_code: upstreamCode || "unspecified",
        upstream_error_name: upstreamErrorName,
        upstream_error_message: upstreamErrorMessage
      };
      throw failure;
    }
    return await res.json();
  } catch (error) {
    if (error instanceof HttpError) throw error;
    const errorName = error && error.name ? String(error.name).slice(0, 80) : "Error";
    const errorMessage = error && error.message ? String(error.message).slice(0, 240) : String(error).slice(0, 240);
    console.error("password-crypto-do-error", errorName, errorMessage, path);
    const failure = new HttpError(503, "密码计算服务暂时不可用，请稍后重试", {
      code: "password_service_unavailable"
    });
    failure.diagnostic = {
      upstream_code: "fetch_exception",
      upstream_error_name: errorName,
      upstream_error_message: errorMessage
    };
    throw failure;
  }
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
  const until = Date.parse(row.banned_until);
  if (Number.isFinite(until) && until <= Date.now()) {
    await db.prepare("UPDATE accounts SET banned_until = NULL, ban_reason = '' WHERE id = ?").bind(row.id).run();
    return null;
  }
  return { until: row.banned_until, reason: row.ban_reason || "未填写封禁原因" };
}
async function authResult(env, row, role, seconds) {
  return {
    token: await makeToken(env, row.id, role, seconds),
    expires_in: seconds,
    user: publicUser(row),
  };
}
async function readJson(request) {
  const length = Number(request.headers.get("content-length") || "0");
  const maxBytes = 180 * 1024;
  if (length > maxBytes) throw new HttpError(413, "请求内容过大");
  try {
    const raw = await request.text();
    if (encoder.encode(raw).byteLength > maxBytes) throw new HttpError(413, "请求内容过大");
    return JSON.parse(raw);
  } catch (error) {
    if (error instanceof HttpError) throw error;
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
function validAvatar(avatar) {
  if (!avatar) return true;
  if (/^https?:\/\/\S+$/i.test(avatar)) return true;
  // The Android photo picker sends a 256px JPEG compressed to at most 96 KiB.
  // Allow the resulting Base64 data URI while keeping database payloads bounded.
  return avatar.length <= 135000 &&
    /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(avatar);
}
function validateRegistration(body) {
  const qq = String(body.qq || "").trim();
  const wechat = String(body.wechat || "").trim();
  const name = String(body.name || "").trim();
  const password = String(body.password || "");
  const avatar = String(body.avatar_url || "").trim();
  const validQQ = !qq || /^[1-9][0-9]{4,11}$/.test(qq);
  const validWechat = !wechat || /^[A-Za-z][A-Za-z0-9_-]{5,31}$/.test(wechat);
  if ((!qq && !wechat) || !validQQ || !validWechat) {
    throw new HttpError(422, "QQ号和微信号至少填写一项；填写的项目必须符合格式");
  }
  if (!name || name.length > 40) throw new HttpError(422, "姓名不能为空且不能超过40字");
  if (password.length < 8 || password.length > 128) throw new HttpError(422, "密码至少8位");
  if (!validAvatar(avatar)) throw new HttpError(422, "头像格式不正确或图片超过大小限制");
  return { qq: qq || null, wechat: wechat || null, name, password, avatar };
}

async function adminWhitelist(request, env) {
  await readToken(env, request, "admin");
  const result = await env.DB.prepare(
    "SELECT id, kind, value, created_at FROM account_whitelist ORDER BY created_at DESC, kind, value"
  ).all();
  return response({ entries: result.results || [] });
}
async function adminAddWhitelist(request, env) {
  const claims = await readToken(env, request, "admin");
  const body = await readJson(request);
  const qq = String(body.qq || "").trim();
  const wechat = String(body.wechat || "").trim();
  const validQQ = !qq || /^[1-9][0-9]{4,11}$/.test(qq);
  const validWechat = !wechat || /^[A-Za-z][A-Za-z0-9_-]{5,31}$/.test(wechat);
  if ((!qq && !wechat) || !validQQ || !validWechat) {
    return fail(422, "请填写有效的 QQ号或微信号；两项可以分别添加");
  }
  const created = new Date().toISOString();
  let added = 0;
  for (const entry of [
    ...(qq ? [{ kind: "qq", value: qq, normalized: qq }] : []),
    ...(wechat ? [{ kind: "wechat", value: wechat, normalized: wechat.toLowerCase() }] : [])
  ]) {
    const result = await env.DB.prepare(
      "INSERT OR IGNORE INTO account_whitelist (id, kind, value, normalized_value, created_at, changed_by) VALUES (?, ?, ?, ?, ?, ?)"
    ).bind(crypto.randomUUID(), entry.kind, entry.value, entry.normalized, created, claims.sub).run();
    added += Number(result.meta?.changes || 0);
  }
  const current = await env.DB.prepare(
    "SELECT id, kind, value, created_at FROM account_whitelist ORDER BY created_at DESC, kind, value"
  ).all();
  return response({ added, entries: current.results || [] });
}
async function adminRemoveWhitelist(request, env) {
  await readToken(env, request, "admin");
  const body = await readJson(request);
  const id = String(body.id || "").trim();
  if (!id) return fail(422, "缺少白名单记录 ID");
  const result = await env.DB.prepare("DELETE FROM account_whitelist WHERE id = ?").bind(id).run();
  return response({ removed: Number(result.meta?.changes || 0) });
}
async function register(request, env) {
  const body = validateRegistration(await readJson(request));
  await requireWhitelistedIdentifiers(env.DB, body.qq, body.wechat);
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
  const body = await readJson(request);
  const identifier = String(body.identifier || "").trim();
  const password = String(body.password || "");
  if (!identifier || !password) return fail(422, "请填写QQ号/微信号和密码");
  const identifierKind = /^[1-9][0-9]{4,11}$/.test(identifier) ? "qq" : "wechat";
  if (!(await isWhitelistAllowed(env.DB, identifierKind, identifier))) {
    return fail(403, identifierKind === "qq" ? "QQ号不在白名单中，无法登录" : "微信号不在白名单中，无法登录", {
      code: "not_whitelisted", kind: identifierKind
    });
  }
  const row = await env.DB.prepare(
    "SELECT * FROM accounts WHERE qq = ? OR lower(wechat) = lower(?) LIMIT 1"
  ).bind(identifier, identifier).first();
  if (!row || !(await verifyPassword(env, password, row.password_hash))) return fail(401, "QQ号/微信号或密码错误");
  const banned = await ensureNotBanned(env.DB, row);
  if (banned) return fail(423, "账号已被封禁", banned);
  return response(await authResult(env, row, "user", 30 * 24 * 60 * 60));
}
async function me(request, env) {
  const claims = await readToken(env, request, "user");
  const row = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(claims.sub).first();
  if (!row) return fail(401, "账号不存在，请重新注册");
  await requireWhitelistedIdentifiers(env.DB, row.qq, row.wechat);
  const banned = await ensureNotBanned(env.DB, row);
  if (banned) return fail(423, "账号已被封禁", banned);
  return response({ user: publicUser(row) });
}
async function updateProfile(request, env) {
  const claims = await readToken(env, request, "user");
  const body = await readJson(request);
  const row = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(claims.sub).first();
  if (!row) return fail(401, "账号不存在");
  const banned = await ensureNotBanned(env.DB, row);
  if (banned) return fail(423, "账号已被封禁", banned);
  const qq = String(body.qq || "").trim();
  const wechat = String(body.wechat || "").trim();
  const name = String(body.name || "").trim();
  const avatar = String(body.avatar_url || "").trim();
  const validQQ = !qq || /^[1-9][0-9]{4,11}$/.test(qq);
  const validWechat = !wechat || /^[A-Za-z][A-Za-z0-9_-]{5,31}$/.test(wechat);
  if ((!qq && !wechat) || !validQQ || !validWechat || !name || name.length > 40) {
    return fail(422, "QQ号和微信号至少填写一项；填写的项目必须符合格式");
  }
  await requireWhitelistedIdentifiers(env.DB, qq, wechat);
  if (!validAvatar(avatar)) return fail(422, "头像格式不正确或图片超过大小限制");
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
    ).bind(qq || null, wechat || null, name, avatar, newHash, claims.sub).run();
  } catch (_) {
    return fail(409, "QQ号或微信号已被其他账号使用");
  }
  const updated = await env.DB.prepare("SELECT * FROM accounts WHERE id = ?").bind(claims.sub).first();
  return response({ user: publicUser(updated) });
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
  let result;
  if (query) {
    const like = "%" + query.replace(/[%_\\]/g, "\\$&") + "%";
    result = await env.DB.prepare(
      "SELECT id, COALESCE(qq, '') AS qq, COALESCE(wechat, '') AS wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts WHERE qq LIKE ? ESCAPE '\\' OR lower(wechat) LIKE ? ESCAPE '\\' OR lower(name) LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT 500"
    ).bind(like, like, like).all();
  } else {
    result = await env.DB.prepare(
      "SELECT id, COALESCE(qq, '') AS qq, COALESCE(wechat, '') AS wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts ORDER BY created_at DESC LIMIT 500"
    ).all();
  }
  return response({ users: result.results || [] });
}
async function adminUser(request, env, id) {
  await readToken(env, request, "admin");
  const row = await env.DB.prepare(
    "SELECT id, COALESCE(qq, '') AS qq, COALESCE(wechat, '') AS wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts WHERE id = ?"
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

async function notifyAccountStatus(env, accountId, status, bannedUntil = null) {
  const id = env.ACCOUNT_SESSIONS.idFromName(accountId);
  const stub = env.ACCOUNT_SESSIONS.get(id);
  const res = await stub.fetch("https://account-session.internal/notify", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      type: "account_status_changed",
      status,
      banned_until: bannedUntil,
      changed_at: new Date().toISOString()
    })
  });
  if (!res.ok) return 0;
  const result = await res.json();
  return Number(result.delivered || 0);
}

async function accountEvents(request, env) {
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
    const timestamp = Date.parse(String(until));
    const reason = String(body.reason || "").trim();
    if (!Number.isFinite(timestamp) || timestamp <= Date.now()) return fail(422, "封禁时间必须晚于当前时间");
    if (!reason || reason.length > 200) return fail(422, "请填写封禁原因（最多200字）");
    bannedUntil = new Date(timestamp).toISOString();
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
    notified = await notifyAccountStatus(env, id, status, bannedUntil);
  } catch (error) {
    console.error("account-notification-error", error && error.message ? error.message : String(error));
  }
  const row = await env.DB.prepare(
    "SELECT id, COALESCE(qq, '') AS qq, COALESCE(wechat, '') AS wechat, name, avatar_url, created_at, banned_until, ban_reason FROM accounts WHERE id = ?"
  ).bind(id).first();
  return response({ user: row, notification_delivered: notified, revoked_node_sessions: revokedNodeSessions });
}
async function nodeNetworkStub(env) {
  if (!env.NODE_NETWORK) throw new HttpError(503, "节点网络服务尚未部署");
  const id = env.NODE_NETWORK.idFromName("global-effectcraft-node-network");
  return env.NODE_NETWORK.get(id);
}

async function getAccountServiceState(env) {
  const row = await env.DB.prepare(
    "SELECT enabled, changed_at, changed_by FROM account_service_settings WHERE setting_key = 'global'"
  ).first();
  return {
    enabled: row ? Number(row.enabled) !== 0 : true,
    changed_at: row?.changed_at || null,
    changed_by: row?.changed_by || "bootstrap"
  };
}

async function requireAccountServiceEnabled(env) {
  const state = await getAccountServiceState(env);
  if (!state.enabled) {
    throw new HttpError(503, "云端账号服务器已由管理员关闭，当前无法注册、登录或验证账号", {
      code: "account_service_disabled",
      account_service_enabled: false
    });
  }
}

async function adminAccountServiceState(request, env) {
  await readToken(env, request, "admin");
  return response({ account_service: await getAccountServiceState(env) });
}

async function adminSetAccountServiceState(request, env) {
  const claims = await readToken(env, request, "admin");
  const body = await readJson(request);
  if (typeof body.enabled !== "boolean") return fail(422, "enabled 必须是布尔值");
  const changedAt = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO account_service_settings (setting_key, enabled, changed_at, changed_by) VALUES ('global', ?, ?, ?) " +
    "ON CONFLICT(setting_key) DO UPDATE SET enabled = excluded.enabled, changed_at = excluded.changed_at, changed_by = excluded.changed_by"
  ).bind(body.enabled ? 1 : 0, changedAt, claims.sub).run();

  // Fan out over the already-open global node WebSocket hub. This is a one-off
  // push on state changes, not a polling loop or one request per account.
  let notified = 0;
  try {
    const stub = await nodeNetworkStub(env);
    const pushed = await stub.fetch("https://node-network.internal/account-service-state", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled: body.enabled, changed_at: changedAt })
    });
    if (pushed.ok) {
      const result = await pushed.json();
      notified = Number(result.delivered || 0);
    }
  } catch (error) {
    console.error("account-service-notification-error", error && error.message ? error.message : String(error));
  }
  return response({
    account_service: await getAccountServiceState(env),
    notification_delivered: notified
  });
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
  if (request.method === "GET" && url.pathname === "/health/deep") {
    const supplied = request.headers.get("x-effectcraft-health-token") || "";
    const expected = env.JWT_SECRET || "";
    if (!expected || !constantTimeEqual(encoder.encode(supplied), encoder.encode(expected))) {
      return new Response(null, { status: 404 });
    }
    let stage = "database";
    let connected = false;
    let passwordHashed = false;
    let passwordVerified = false;
    try {
      const probe = await env.DB.prepare("SELECT 1 AS connected").first();
      connected = Number(probe && probe.connected) === 1;
      if (!connected) {
        return fail(503, "数据库自检失败", { code: "database_unavailable", stage });
      }
      const challenge = "EffectCraft-Health-" + crypto.randomUUID() + "-A1!";
      stage = "password_hash";
      const hash = await passwordHash(env, challenge);
      passwordHashed = typeof hash === "string" && hash.length > 20;
      if (!passwordHashed) {
        return fail(503, "密码哈希自检失败", { code: "password_hash_failed", stage });
      }
      stage = "password_verify";
      passwordVerified = await verifyPassword(env, challenge, hash);
      if (!passwordVerified) {
        return fail(503, "密码验证自检失败", { code: "password_verify_failed", stage });
      }
      return response({
        ok: true,
        service: "Ae Cloud Account API",
        database: connected,
        password_service: true,
        password_hash: passwordHashed,
        password_verify: passwordVerified
      }, 200);
    } catch (error) {
      const detail = error && error.message ? error.message : String(error);
      console.error("deep-health-error", stage, detail);
      const diagnostic = error instanceof HttpError && error.diagnostic ? error.diagnostic : {};
      return fail(503, "密码计算服务自检失败", {
        code: "password_service_unavailable",
        stage,
        reason: error instanceof HttpError ? error.message : "internal_error",
        upstream_status: Number(diagnostic.upstream_status || 0),
        upstream_code: String(diagnostic.upstream_code || "unspecified"),
        upstream_error_name: String(diagnostic.upstream_error_name || ""),
        upstream_error_message: String(diagnostic.upstream_error_message || "")
      });
    }
  }
  if (request.method === "GET" && url.pathname === "/health") {
    if (!env.DB) {
      return response({ ok: false, service: "Ae Cloud Account API", database: false }, 503);
    }
    try {
      const probe = await env.DB.prepare("SELECT 1 AS connected").first();
      const connected = Number(probe && probe.connected) === 1;
      let passwordService = false;
      try {
        if (env.ACCOUNT_SESSIONS) {
          const id = env.ACCOUNT_SESSIONS.idFromName("__ae_password_crypto_health__");
          const stub = env.ACCOUNT_SESSIONS.get(id);
          const passwordProbe = await stub.fetch("https://account-session.internal/health");
          if (passwordProbe.ok) {
            const result = await passwordProbe.json();
            passwordService = result && result.ok === true;
          }
        }
      } catch (error) {
        console.error("health-password-service-error", error && error.message ? error.message : String(error));
      }
      // Keep database health separate so the existing admin app can still log in
      // and repair the password service if its Durable Object is unavailable.
      return response(
        {
          ok: connected,
          service: "Ae Cloud Account API",
          database: connected,
          password_service: passwordService
        },
        connected ? 200 : 503
      );
    } catch (error) {
      console.error("health-database-error", error && error.message ? error.message : String(error));
      return response(
        { ok: false, service: "Ae Cloud Account API", database: false, password_service: false },
        503
      );
    }
  }
  if (!env.DB) return fail(503, "云端数据库尚未绑定");
  try {
    if (url.pathname.startsWith("/v1/") && !url.pathname.startsWith("/v1/admin/")) {
      await requireAccountServiceEnabled(env);
    }
    if (request.method === "GET" && url.pathname === "/v1/events") return await accountEvents(request, env);
    if (request.method === "GET" && url.pathname === "/v1/nodes/network") return await nodeNetworkState(request, env);
    if (request.method === "GET" && url.pathname === "/v1/whitelist") return await publicWhitelist(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/whitelist") return await adminWhitelist(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/whitelist") return await adminAddWhitelist(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/whitelist/remove") return await adminRemoveWhitelist(request, env);

    if (request.method === "GET" && url.pathname === "/v1/nodes/events") return await nodeNetworkEvents(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/account-service") return await adminAccountServiceState(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/account-service") return await adminSetAccountServiceState(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/network") return await adminNetworkState(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/network") return await adminSetNetworkState(request, env);
    if (request.method === "GET" && url.pathname === "/v1/admin/network/nodes") return await adminNetworkNodes(request, env);
    if (request.method === "POST" && url.pathname === "/v1/register") return await register(request, env);
    if (request.method === "POST" && url.pathname === "/v1/login") return await login(request, env);
    if (request.method === "POST" && url.pathname === "/v1/admin/login") return await adminLogin(request, env);
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
