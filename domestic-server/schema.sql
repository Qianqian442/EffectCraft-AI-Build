CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY, qq TEXT UNIQUE NOT NULL, wechat TEXT UNIQUE NOT NULL,
 name TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, avatar_url TEXT NOT NULL DEFAULT '',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), banned_until TIMESTAMPTZ, ban_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS admin_devices (
 device_id TEXT PRIMARY KEY, public_key TEXT NOT NULL, last_seen TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS admin_device_challenges (
 nonce TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES admin_devices(device_id) ON DELETE CASCADE, expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS network_state (
 id INTEGER PRIMARY KEY CHECK (id=1), enabled BOOLEAN NOT NULL DEFAULT TRUE, changed_at TIMESTAMPTZ, changed_by TEXT NOT NULL DEFAULT 'bootstrap'
);
INSERT INTO network_state(id,enabled,changed_by) VALUES(1,TRUE,'bootstrap') ON CONFLICT(id) DO NOTHING;
