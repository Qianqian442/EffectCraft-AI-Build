const encoder = new TextEncoder();
const PASSWORD_ITERATIONS = 100000;
const SUPPORTED_PASSWORD_ITERATIONS = new Set([100000, 210000]);

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

function constantTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function derivePasswordHash(password, salt, iterations) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    key,
    256
  );
  return "pbkdf2-sha256$" + iterations + "$" + bytesToB64Url(salt) + "$" + bytesToB64Url(new Uint8Array(bits));
}

async function passwordHash(password) {
  return derivePasswordHash(password, crypto.getRandomValues(new Uint8Array(16)), PASSWORD_ITERATIONS);
}

async function passwordVerify(password, stored) {
  const parts = String(stored || "").split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2-sha256") {
    return { valid: false, reason: "unsupported_hash_format" };
  }
  const iterations = Number(parts[1]);
  if (!SUPPORTED_PASSWORD_ITERATIONS.has(iterations)) {
    return { valid: false, reason: "unsupported_iteration_count" };
  }
  let salt;
  let expected;
  try {
    salt = b64UrlToBytes(parts[2]);
    expected = b64UrlToBytes(parts[3]);
  } catch (_) {
    return { valid: false, reason: "invalid_base64url" };
  }
  if (salt.length !== 16 || expected.length !== 32) {
    return { valid: false, reason: "invalid_hash_dimensions" };
  }
  try {
    const actual = await derivePasswordHash(password, salt, iterations);
    return {
      valid: constantTimeEqual(encoder.encode(actual), encoder.encode(stored)),
      reason: "digest_checked",
      iterations
    };
  } catch (error) {
    const name = error && error.name ? String(error.name).slice(0, 80) : "Error";
    const message = error && error.message ? String(error.message).slice(0, 180) : "unknown_error";
    console.error("password-crypto-verify-failed", iterations, name, message);
    return { valid: false, reason: "derive_failed", error_name: name, error_message: message };
  }
}

export class PasswordCryptoHub {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ ok: true, service: "password-crypto-v2" });
    }
    if (request.method !== "POST") {
      return Response.json({ error: "method_not_allowed" }, { status: 405 });
    }
    if (url.pathname === "/password/hash") {
      let stage = "parse";
      try {
        const body = await request.json();
        const password = String(body.password || "");
        if (password.length < 8 || password.length > 128) {
          return Response.json({ error: "invalid_password_length", code: "invalid_password_length" }, { status: 422 });
        }
        stage = "pbkdf2_hash";
        const hash = await passwordHash(password);
        return Response.json({ hash });
      } catch (error) {
        const name = error && error.name ? String(error.name).slice(0, 80) : "Error";
        const message = error && error.message ? String(error.message).slice(0, 180) : "unknown_error";
        console.error("password-crypto-hash-failed", stage, name, message);
        return Response.json({ error: "password_hash_failed", code: "password_hash_failed" }, { status: 500 });
      }
    }
    if (url.pathname === "/password/verify") {
      try {
        const body = await request.json();
        const password = String(body.password || "");
        const stored = String(body.stored || "");
        if (!password || !stored) return Response.json({ valid: false, reason: "missing_input" });
        return Response.json(await passwordVerify(password, stored));
      } catch (error) {
        const name = error && error.name ? String(error.name).slice(0, 80) : "Error";
        const message = error && error.message ? String(error.message).slice(0, 180) : "unknown_error";
        console.error("password-crypto-verify-handler-failed", name, message);
        return Response.json({ valid: false, reason: "handler_failed" }, { status: 500 });
      }
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  }
}
