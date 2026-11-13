CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  qq TEXT NOT NULL UNIQUE,
  wechat TEXT NOT NULL COLLATE NOCASE UNIQUE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  avatar_url TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  banned_until TEXT,
  ban_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_accounts_created_at ON accounts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS account_service_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT 'system'
);
INSERT OR IGNORE INTO account_service_state (id, enabled, updated_at, updated_by)
VALUES (1, 1, datetime('now'), 'system');
