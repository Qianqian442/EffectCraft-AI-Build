package com.qianqian.effectcraftadmin;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.List;

/**
 * Local signing and verification primitive for administrator-signed mesh events.
 *
 * This class deliberately does not transmit events or grant trust to a key.
 * The caller must provision the trusted admin public key out of band and must
 * persist/replicate verified envelopes before acknowledging them to a peer.
 */
final class SignedAdminEvent {
    private static final String KEY_ALIAS = "effectcraft-admin-authority-v1";
    private static final String PREFS = "effectcraft_signed_events_v1";
    private static final String SEQUENCE_KEY = "admin_sequence";

    private SignedAdminEvent() { }

    static synchronized JSONObject create(Context context, String eventType,
                                          String subjectKey, JSONObject payload) throws Exception {
        if (!("account.ban".equals(eventType) || "account.unban".equals(eventType)
                || "mesh.state".equals(eventType))) {
            throw new IllegalArgumentException("Unsupported administrator event type");
        }
        if (payload == null) throw new IllegalArgumentException("payload is required");

        KeyStore store = loadKeyStore();
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyPairGenerator generator = KeyPairGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore"
            );
            KeyGenParameterSpec spec = new KeyGenParameterSpec.Builder(
                KEY_ALIAS, KeyProperties.PURPOSE_SIGN | KeyProperties.PURPOSE_VERIFY
            ).setAlgorithmParameterSpec(new ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256).build();
            generator.initialize(spec);
            generator.generateKeyPair();
            store = loadKeyStore();
        }

        byte[] publicBytes = store.getCertificate(KEY_ALIAS).getPublicKey().getEncoded();
        String issuerKey = b64Url(publicBytes);
        SharedPreferences prefs = context.getApplicationContext()
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long sequence = prefs.getLong(SEQUENCE_KEY, 0L) + 1L;
        if (sequence <= 0L || !prefs.edit().putLong(SEQUENCE_KEY, sequence).commit()) {
            throw new IllegalStateException("Could not persist administrator event sequence");
        }

        JSONObject idMaterial = new JSONObject();
        idMaterial.put("event_type", eventType);
        idMaterial.put("issuer_key", issuerKey);
        idMaterial.put("sequence", sequence);
        idMaterial.put("subject_key", subjectKey == null ? "" : subjectKey);
        idMaterial.put("payload", payload);
        String eventId = hex(MessageDigest.getInstance("SHA-256")
            .digest(canonical(idMaterial).getBytes(StandardCharsets.UTF_8)));

        JSONObject signed = new JSONObject();
        signed.put("event_type", eventType);
        signed.put("event_id", eventId);
        signed.put("issuer_key", issuerKey);
        signed.put("sequence", sequence);
        signed.put("issued_at", java.time.Instant.now().toString());
        signed.put("expires_at", JSONObject.NULL);
        signed.put("subject_key", subjectKey == null ? "" : subjectKey);
        signed.put("payload", payload);

        Signature signer = Signature.getInstance("SHA256withECDSA");
        signer.initSign((PrivateKey) store.getKey(KEY_ALIAS, null));
        signer.update(canonical(signed).getBytes(StandardCharsets.UTF_8));
        String signature = b64Url(signer.sign());

        JSONObject envelope = new JSONObject();
        envelope.put("version", 1);
        envelope.put("signed", signed);
        envelope.put("signature", signature);
        return envelope;
    }

    static boolean verify(JSONObject envelope, String trustedAdminPublicKey) {
        try {
            if (envelope == null || envelope.optInt("version", -1) != 1) return false;
            JSONObject signed = envelope.optJSONObject("signed");
            if (signed == null || !"".equals(signed.optString("subject_key", "")) &&
                    !signed.has("subject_key")) return false;
            String type = signed.optString("event_type", "");
            if (!("account.ban".equals(type) || "account.unban".equals(type)
                    || "mesh.state".equals(type))) return false;
            String issuer = signed.optString("issuer_key", "");
            if (issuer.isEmpty() || !issuer.equals(trustedAdminPublicKey)) return false;
            long sequence = signed.optLong("sequence", 0L);
            if (sequence < 1L || signed.optString("event_id", "").length() != 64) return false;

            JSONObject idMaterial = new JSONObject();
            idMaterial.put("event_type", type);
            idMaterial.put("issuer_key", issuer);
            idMaterial.put("sequence", sequence);
            idMaterial.put("subject_key", signed.optString("subject_key", ""));
            idMaterial.put("payload", signed.optJSONObject("payload"));
            String expectedId = hex(MessageDigest.getInstance("SHA-256")
                .digest(canonical(idMaterial).getBytes(StandardCharsets.UTF_8)));
            if (!expectedId.equals(signed.optString("event_id", ""))) return false;

            byte[] encodedKey = Base64.decode(issuer,
                Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
            PublicKey publicKey = KeyFactory.getInstance("EC")
                .generatePublic(new X509EncodedKeySpec(encodedKey));
            Signature verifier = Signature.getInstance("SHA256withECDSA");
            verifier.initVerify(publicKey);
            verifier.update(canonical(signed).getBytes(StandardCharsets.UTF_8));
            byte[] signature = Base64.decode(envelope.optString("signature", ""),
                Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
            return verifier.verify(signature);
        } catch (Exception invalid) {
            return false;
        }
    }

    static String publicKey(Context context) throws Exception {
        KeyStore store = loadKeyStore();
        if (!store.containsAlias(KEY_ALIAS)) {
            throw new IllegalStateException("Administrator signing key has not been created");
        }
        return b64Url(store.getCertificate(KEY_ALIAS).getPublicKey().getEncoded());
    }

    private static KeyStore loadKeyStore() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        return store;
    }

    private static String canonical(JSONObject object) throws Exception {
        StringBuilder out = new StringBuilder();
        appendCanonical(out, object);
        return out.toString();
    }

    private static void appendCanonical(StringBuilder out, Object value) throws Exception {
        if (value == null || value == JSONObject.NULL) {
            out.append("null");
        } else if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value;
            List<String> keys = new ArrayList<>();
            Iterator<String> iterator = object.keys();
            while (iterator.hasNext()) keys.add(iterator.next());
            Collections.sort(keys);
            out.append('{');
            boolean first = true;
            for (String key : keys) {
                if (!first) out.append(',');
                first = false;
                out.append(JSONObject.quote(key)).append(':');
                appendCanonical(out, object.get(key));
            }
            out.append('}');
        } else if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value;
            out.append('[');
            for (int i = 0; i < array.length(); i++) {
                if (i > 0) out.append(',');
                appendCanonical(out, array.get(i));
            }
            out.append(']');
        } else if (value instanceof String) {
            out.append(JSONObject.quote((String) value));
        } else if (value instanceof Number || value instanceof Boolean) {
            out.append(JSONObject.numberToString(value instanceof Number
                ? (Number) value : Integer.valueOf((Boolean) value ? 1 : 0)));
            if (value instanceof Boolean) {
                int start = out.length() - 1;
                out.replace(start, out.length(), (Boolean) value ? "true" : "false");
            }
        } else {
            throw new IllegalArgumentException("Unsupported JSON value");
        }
    }

    private static String b64Url(byte[] bytes) {
        return Base64.encodeToString(bytes,
            Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) out.append(String.format(java.util.Locale.ROOT,
            "%02x", value & 0xff));
        return out.toString();
    }
}
