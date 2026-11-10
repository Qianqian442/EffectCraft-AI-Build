package com.qianqian.effectcraftadmin;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteConstraintException;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.time.Instant;

/**
 * Durable, verified administrator event log.
 *
 * Events are verified before they enter the database. A unique issuer/sequence
 * constraint prevents replay and equivocation (two different events at one
 * sequence). This class is storage only; it does not discover peers or claim
 * that an event has reached another device.
 */
final class AdminEventStore extends SQLiteOpenHelper {
    private static final String DB_NAME = "effectcraft_admin_events.db";
    private static final int DB_VERSION = 1;
    private static final String TABLE = "verified_events";
    private static final int MAX_EVENT_BYTES = 64 * 1024;

    static final int INSERTED = 1;
    static final int DUPLICATE = 0;
    static final int REJECTED = -1;
    static final int SEQUENCE_CONFLICT = -2;

    AdminEventStore(Context context) {
        super(context.getApplicationContext(), DB_NAME, null, DB_VERSION);
        setWriteAheadLoggingEnabled(true);
    }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE " + TABLE + " (" +
            "event_id TEXT PRIMARY KEY NOT NULL," +
            "issuer_key TEXT NOT NULL," +
            "issuer_sequence INTEGER NOT NULL CHECK(issuer_sequence > 0)," +
            "event_type TEXT NOT NULL," +
            "subject_key TEXT NOT NULL," +
            "issued_at TEXT NOT NULL," +
            "envelope_json TEXT NOT NULL," +
            "accepted_at INTEGER NOT NULL," +
            "UNIQUE(issuer_key, issuer_sequence))");
        db.execSQL("CREATE INDEX idx_events_subject_sequence ON " + TABLE +
            "(subject_key, issuer_sequence)");
        db.execSQL("CREATE INDEX idx_events_issuer_sequence ON " + TABLE +
            "(issuer_key, issuer_sequence)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // Versioned migrations must preserve the append-only event history.
        throw new IllegalStateException("No migration path from database version " + oldVersion);
    }

    /**
     * Returns INSERTED, DUPLICATE, REJECTED, or SEQUENCE_CONFLICT.
     * The caller must supply an admin key enrolled through a trusted channel.
     */
    synchronized int acceptAdminEvent(JSONObject envelope, String trustedAdminPublicKey) {
        if (envelope == null || trustedAdminPublicKey == null || trustedAdminPublicKey.isEmpty()) {
            return REJECTED;
        }
        String json = envelope.toString();
        if (json.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > MAX_EVENT_BYTES) {
            return REJECTED;
        }
        if (!SignedAdminEvent.verify(envelope, trustedAdminPublicKey)) return REJECTED;

        JSONObject signed = envelope.optJSONObject("signed");
        if (signed == null) return REJECTED;
        String eventId = signed.optString("event_id", "");
        String issuer = signed.optString("issuer_key", "");
        long sequence = signed.optLong("sequence", 0L);
        String type = signed.optString("event_type", "");
        String subject = signed.optString("subject_key", "");
        String issuedAt = signed.optString("issued_at", "");
        if (eventId.length() != 64 || issuer.isEmpty() || sequence < 1L ||
                type.isEmpty() || issuedAt.isEmpty()) return REJECTED;

        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            Cursor existingId = db.query(TABLE, new String[]{"event_id"},
                "event_id=?", new String[]{eventId}, null, null, null, "1");
            try {
                if (existingId.moveToFirst()) {
                    db.setTransactionSuccessful();
                    return DUPLICATE;
                }
            } finally {
                existingId.close();
            }

            Cursor existingSequence = db.query(TABLE, new String[]{"event_id"},
                "issuer_key=? AND issuer_sequence=?",
                new String[]{issuer, Long.toString(sequence)}, null, null, null, "1");
            try {
                if (existingSequence.moveToFirst()) {
                    db.setTransactionSuccessful();
                    return SEQUENCE_CONFLICT;
                }
            } finally {
                existingSequence.close();
            }

            ContentValues values = new ContentValues();
            values.put("event_id", eventId);
            values.put("issuer_key", issuer);
            values.put("issuer_sequence", sequence);
            values.put("event_type", type);
            values.put("subject_key", subject);
            values.put("issued_at", issuedAt);
            values.put("envelope_json", json);
            values.put("accepted_at", System.currentTimeMillis());
            if (db.insertOrThrow(TABLE, null, values) == -1L) return REJECTED;
            db.setTransactionSuccessful();
            return INSERTED;
        } catch (SQLiteConstraintException conflict) {
            return SEQUENCE_CONFLICT;
        } catch (Exception invalid) {
            return REJECTED;
        } finally {
            db.endTransaction();
        }
    }

    synchronized JSONArray eventsAfter(String issuerKey, long sequenceExclusive, int limit) {
        JSONArray result = new JSONArray();
        if (issuerKey == null || issuerKey.isEmpty()) return result;
        int boundedLimit = Math.max(1, Math.min(limit, 200));
        SQLiteDatabase db = getReadableDatabase();
        Cursor cursor = db.query(TABLE, new String[]{"envelope_json"},
            "issuer_key=? AND issuer_sequence>?",
            new String[]{issuerKey, Long.toString(Math.max(0L, sequenceExclusive))},
            null, null, "issuer_sequence ASC", Integer.toString(boundedLimit));
        try {
            while (cursor.moveToNext()) result.put(new JSONObject(cursor.getString(0)));
        } catch (Exception ignored) {
            // Return only complete envelopes that could be parsed.
        } finally {
            cursor.close();
        }
        return result;
    }

    synchronized long highestSequence(String issuerKey) {
        if (issuerKey == null || issuerKey.isEmpty()) return 0L;
        Cursor cursor = getReadableDatabase().rawQuery(
            "SELECT MAX(issuer_sequence) FROM " + TABLE + " WHERE issuer_key=?",
            new String[]{issuerKey});
        try {
            return cursor.moveToFirst() && !cursor.isNull(0) ? cursor.getLong(0) : 0L;
        } finally {
            cursor.close();
        }
    }

    synchronized JSONObject activeBan(String subjectKey) {
        if (subjectKey == null || subjectKey.isEmpty()) return null;
        SQLiteDatabase db = getReadableDatabase();
        Cursor cursor = db.query(TABLE, new String[]{"envelope_json"},
            "subject_key=? AND event_type IN ('account.ban','account.unban')",
            new String[]{subjectKey}, null, null, "accepted_at ASC, issuer_sequence ASC");
        JSONObject active = null;
        String activeBanId = "";
        try {
            while (cursor.moveToNext()) {
                JSONObject envelope = new JSONObject(cursor.getString(0));
                JSONObject signed = envelope.optJSONObject("signed");
                if (signed == null) continue;
                String type = signed.optString("event_type", "");
                JSONObject payload = signed.optJSONObject("payload");
                if (payload == null) continue;
                if ("account.ban".equals(type)) {
                    active = envelope;
                    activeBanId = signed.optString("event_id", "");
                } else if ("account.unban".equals(type) &&
                        activeBanId.equals(payload.optString("ban_event_id", ""))) {
                    active = null;
                    activeBanId = "";
                }
            }
        } catch (Exception ignored) {
            return null;
        } finally {
            cursor.close();
        }
        if (active == null) return null;

        JSONObject signed = active.optJSONObject("signed");
        JSONObject payload = signed == null ? null : signed.optJSONObject("payload");
        if (payload == null) return null;
        Object expiry = payload.opt("expires_at");
        if (expiry instanceof String && !((String) expiry).isEmpty()) {
            try {
                if (Instant.now().isAfter(Instant.parse((String) expiry))) return null;
            } catch (Exception invalidExpiry) {
                // Fail closed: malformed expiry cannot silently clear a ban.
                return active;
            }
        }
        return active;
    }

    synchronized int eventCount() {
        Cursor cursor = getReadableDatabase().rawQuery(
            "SELECT COUNT(*) FROM " + TABLE, null);
        try {
            return cursor.moveToFirst() ? cursor.getInt(0) : 0;
        } finally {
            cursor.close();
        }
    }
}
