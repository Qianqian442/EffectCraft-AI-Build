CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  qq TEXT UNIQUE,
  wechat TEXT COLLATE NOCASE UNIQUE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  avatar_url TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  banned_until TEXT,
  ban_reason TEXT NOT NULL DEFAULT '',
  CHECK (qq IS NOT NULL OR wechat IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_accounts_created_at ON accounts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name COLLATE NOCASE);


CREATE TABLE IF NOT EXISTS account_service_settings (
  setting_key TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  changed_at TEXT,
  changed_by TEXT NOT NULL DEFAULT 'bootstrap'
);
INSERT OR IGNORE INTO account_service_settings (setting_key, enabled, changed_by)
VALUES ('global', 1, 'bootstrap');

CREATE TABLE IF NOT EXISTS account_whitelist (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('qq', 'wechat')),
  value TEXT NOT NULL,
  normalized_value TEXT NOT NULL,
  created_at TEXT NOT NULL,
  changed_by TEXT NOT NULL DEFAULT 'admin',
  UNIQUE(kind, normalized_value)
);
CREATE INDEX IF NOT EXISTS idx_account_whitelist_kind_value ON account_whitelist(kind, normalized_value);


CREATE TABLE IF NOT EXISTS account_identity_bans (
  identity_hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('qq', 'wechat')),
  created_at TEXT NOT NULL,
  ban_reason TEXT NOT NULL DEFAULT ''
);
