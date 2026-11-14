-- Upgrade existing account records to support QQ-only or WeChat-only accounts.
-- Preserve all existing account IDs, password hashes, profile fields and ban state.
DROP TABLE IF EXISTS accounts_optional_ids_rebuild;
CREATE TABLE accounts_optional_ids_rebuild (
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
INSERT INTO accounts_optional_ids_rebuild
  (id, qq, wechat, name, password_hash, avatar_url, created_at, banned_until, ban_reason)
SELECT
  id, NULLIF(qq, ''), NULLIF(wechat, ''), name, password_hash,
  COALESCE(avatar_url, ''), created_at, banned_until, COALESCE(ban_reason, '')
FROM accounts;
DROP TABLE accounts;
ALTER TABLE accounts_optional_ids_rebuild RENAME TO accounts;
CREATE INDEX IF NOT EXISTS idx_accounts_created_at ON accounts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name COLLATE NOCASE);
