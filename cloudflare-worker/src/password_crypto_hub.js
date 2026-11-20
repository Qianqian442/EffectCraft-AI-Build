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

// Cloudflare WebCrypto rejects PBKDF2 iteration counts above 100000.
// Legacy account hashes used 210000 rounds, so verify those with a compact
// SHA-256/HMAC implementation inside this dedicated Durable Object.
const SHA256_K = Uint32Array.from([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
]);
const SHA256_INIT = Uint32Array.from([
  0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
  0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19
]);
function rotr32(value, count) {
  return (value >>> count) | (value << (32 - count));
}
function sha256(bytes) {
  const length = bytes.length;
  const paddedLength = Math.ceil((length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[length] = 0x80;
  const view = new DataView(padded.buffer);
  const bitLength = length * 8;
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);

  const state = Uint32Array.from(SHA256_INIT);
  const words = new Uint32Array(64);
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let i = 0; i < 16; i++) words[i] = view.getUint32(offset + i * 4, false);
    for (let i = 16; i < 64; i++) {
      const x = words[i - 15], y = words[i - 2];
      const s0 = rotr32(x, 7) ^ rotr32(x, 18) ^ (x >>> 3);
      const s1 = rotr32(y, 17) ^ rotr32(y, 19) ^ (y >>> 10);
      words[i] = (words[i - 16] + s0 + words[i - 7] + s1) >>> 0;
    }
    let a=state[0], b=state[1], c=state[2], d=state[3];
    let e=state[4], f=state[5], g=state[6], h=state[7];
    for (let i = 0; i < 64; i++) {
      const s1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + choice + SHA256_K[i] + words[i]) >>> 0;
      const s0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + majority) >>> 0;
      h=g; g=f; f=e; e=(d + temp1) >>> 0;
      d=c; c=b; b=a; a=(temp1 + temp2) >>> 0;
    }
    state[0]=(state[0]+a)>>>0; state[1]=(state[1]+b)>>>0;
    state[2]=(state[2]+c)>>>0; state[3]=(state[3]+d)>>>0;
    state[4]=(state[4]+e)>>>0; state[5]=(state[5]+f)>>>0;
    state[6]=(state[6]+g)>>>0; state[7]=(state[7]+h)>>>0;
  }
  const out = new Uint8Array(32);
  const outView = new DataView(out.buffer);
  for (let i = 0; i < 8; i++) outView.setUint32(i * 4, state[i], false);
  return out;
}
function createHmacSha256(key) {
  let normalized = key;
  if (normalized.length > 64) normalized = sha256(normalized);
  const innerPad = new Uint8Array(64);
  const outerPad = new Uint8Array(64);
  for (let i = 0; i < 64; i++) {
    const value = i < normalized.length ? normalized[i] : 0;
    innerPad[i] = value ^ 0x36;
    outerPad[i] = value ^ 0x5c;
  }
  return (message) => {
    const inner = new Uint8Array(64 + message.length);
    inner.set(innerPad);
    inner.set(message, 64);
    const innerHash = sha256(inner);
    const outer = new Uint8Array(96);
    outer.set(outerPad);
    outer.set(innerHash, 64);
    return sha256(outer);
  };
}
function pbkdf2Sha256Legacy(passwordBytes, salt, iterations) {
  const hmac = createHmacSha256(passwordBytes);
  const firstInput = new Uint8Array(salt.length + 4);
  firstInput.set(salt);
  firstInput[firstInput.length - 1] = 1;
  let u = hmac(firstInput);
  const result = Uint8Array.from(u);
  for (let round = 1; round < iterations; round++) {
    u = hmac(u);
    for (let i = 0; i < result.length; i++) result[i] ^= u[i];
  }
  return result;
}

async function passwordVerify(password, stored, options = {}) {
  const upgradeLegacy = options.upgradeLegacy === true;
  const newPassword = String(options.newPassword || "");
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
    const digest = iterations > PASSWORD_ITERATIONS
      ? pbkdf2Sha256Legacy(encoder.encode(password), salt, iterations)
      : new Uint8Array(await crypto.subtle.deriveBits(
          { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
          await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]),
          256
        ));
    const actual = "pbkdf2-sha256$" + iterations + "$" + bytesToB64Url(salt) + "$" + bytesToB64Url(digest);
    const valid = constantTimeEqual(encoder.encode(actual), encoder.encode(stored));
    const result = { valid, reason: "digest_checked", iterations };
    if (valid && newPassword) {
      if (newPassword.length < 8 || newPassword.length > 128) {
        return { valid: false, reason: "invalid_new_password_length" };
      }
      result.replacement_hash = await passwordHash(newPassword);
    } else if (valid && upgradeLegacy && iterations > PASSWORD_ITERATIONS) {
      // Migrate legacy accounts inside the same Durable Object invocation.
      result.upgraded_hash = await passwordHash(password);
    }
    return result;
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
        const newPassword = String(body.new_password || "");
        if (!password || !stored) return Response.json({ valid: false, reason: "missing_input" });
        if (newPassword && (newPassword.length < 8 || newPassword.length > 128)) {
          return Response.json({ valid: false, reason: "invalid_new_password_length" }, { status: 422 });
        }
        return Response.json(await passwordVerify(password, stored, {
          upgradeLegacy: body.upgrade_legacy === true,
          newPassword
        }));
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
