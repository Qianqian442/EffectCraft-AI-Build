import assert from "node:assert/strict";
import { PasswordCryptoHub } from "../../cloudflare-worker/src/password_crypto_hub.js";

const hub = new PasswordCryptoHub({ storage: {} }, {});
const LEGACY_PASSWORD = "Legacy-Credential-Check-2026!";
const LEGACY_HASH = "pbkdf2-sha256$210000$ABEiM0RVZneImaq7zN3u_w$uGMyIVWFJs6SvUbo81u_YADCCXkd_SdvDP5269iMbQI";

async function post(path, body) {
  const request = new Request("https://account-session.test" + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  const response = await hub.fetch(request);
  assert.equal(response.status, 200, path + " should return HTTP 200");
  return response.json();
}

const legacyValid = await post("/password/verify", {
  password: LEGACY_PASSWORD,
  stored: LEGACY_HASH
});
assert.equal(legacyValid.valid, true, "210000-round accounts must remain verifiable");

const legacyInvalid = await post("/password/verify", {
  password: "not-the-legacy-password",
  stored: LEGACY_HASH
});
assert.equal(legacyInvalid.valid, false, "wrong passwords must still be rejected");

const fresh = await post("/password/hash", { password: LEGACY_PASSWORD });
assert.match(fresh.hash, /^pbkdf2-sha256\$100000\$/);
const freshValid = await post("/password/verify", {
  password: LEGACY_PASSWORD,
  stored: fresh.hash
});
assert.equal(freshValid.valid, true, "new 100000-round hashes must remain verifiable");

console.log("PASS: legacy 210000-round accounts, current 100000-round accounts, and incorrect passwords are handled correctly.");
