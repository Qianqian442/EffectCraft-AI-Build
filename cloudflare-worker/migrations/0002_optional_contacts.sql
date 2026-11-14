-- Preserve every existing account while allowing QQ OR WeChat as the one required identifier.
-- NULL values do not collide with SQLite UNIQUE constraints.
DROP TABLE IF EXISTS accounts_optional_contacts;
CREATE TABLE accounts_optional_contacts (
  id TEXT PRIMARY KEY,
  qq TEXT UNIQUE,
  wechat TEXT COLLATE NOCASE UNIQUE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  avatar_url TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  banned_until TEXT,
  ban_reason TEXT NOT NULL DEFAULT ''
);
INSERT INTO accounts_optional_contacts
  (id, qq, wechat, name, password_hash, avatar_url, created_at, banned_until, ban_reason)
SELECT id, NULLIF(qq, ''), NULLIF(wechat, ''), name, password_hash, avatar_url, created_at, banned_until, ban_reason
FROM accounts;
DROP TABLE accounts;
ALTER TABLE accounts_optional_contacts RENAME TO accounts;
CREATE INDEX IF NOT EXISTS idx_accounts_created_at ON accounts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name COLLATE NOCASE);
