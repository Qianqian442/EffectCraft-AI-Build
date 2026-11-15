CREATE TABLE IF NOT EXISTS account_identity_bans (
  identity_hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('qq', 'wechat')),
  created_at TEXT NOT NULL,
  ban_reason TEXT NOT NULL DEFAULT ''
);
