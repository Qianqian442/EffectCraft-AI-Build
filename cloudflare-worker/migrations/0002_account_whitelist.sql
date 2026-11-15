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

-- Preserve every already-registered identity as initially whitelisted so existing
-- users are not locked out when whitelist enforcement is first enabled.
INSERT OR IGNORE INTO account_whitelist (id, kind, value, normalized_value, created_at, changed_by)
SELECT lower(hex(randomblob(16))), 'qq', qq, qq, created_at, 'migration'
FROM accounts WHERE qq IS NOT NULL AND trim(qq) <> '';
INSERT OR IGNORE INTO account_whitelist (id, kind, value, normalized_value, created_at, changed_by)
SELECT lower(hex(randomblob(16))), 'wechat', wechat, lower(wechat), created_at, 'migration'
FROM accounts WHERE wechat IS NOT NULL AND trim(wechat) <> '';
