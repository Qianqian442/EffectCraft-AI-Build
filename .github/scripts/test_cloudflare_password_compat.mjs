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

const migratedLegacy = await post("/password/verify", {
  password: LEGACY_PASSWORD,
  stored: LEGACY_HASH,
  upgrade_legacy: true
});
assert.equal(migratedLegacy.valid, true, "legacy account verification must succeed");
assert.match(migratedLegacy.upgraded_hash, /^pbkdf2-sha256\\$100000\\$/, "legacy migration must create a current hash in the same call");
const migratedLegacyValid = await post("/password/verify", {
  password: LEGACY_PASSWORD,
  stored: migratedLegacy.upgraded_hash
});
assert.equal(migratedLegacyValid.valid, true, "migrated legacy hash must verify");

const wrongLegacyMigration = await post("/password/verify", {
  password: "incorrect",
  stored: LEGACY_HASH,
  upgrade_legacy: true
});
assert.equal(wrongLegacyMigration.valid, false);
assert.equal(wrongLegacyMigration.upgraded_hash, undefined, "wrong passwords must not produce replacement hashes");

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

const changedPassword = "New-Password-2026!";
const passwordChange = await post("/password/verify", {
  password: LEGACY_PASSWORD,
  stored: fresh.hash,
  new_password: changedPassword
});
assert.equal(passwordChange.valid, true, "current password must be checked before password replacement");
assert.match(passwordChange.replacement_hash, /^pbkdf2-sha256\\$100000\\$/);
const changedPasswordValid = await post("/password/verify", {
  password: changedPassword,
  stored: passwordChange.replacement_hash
});
assert.equal(changedPasswordValid.valid, true, "replacement password hash must verify");

console.log("PASS: legacy 210000-round accounts, current 100000-round accounts, and incorrect passwords are handled correctly.");
