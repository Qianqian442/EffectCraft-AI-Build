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
