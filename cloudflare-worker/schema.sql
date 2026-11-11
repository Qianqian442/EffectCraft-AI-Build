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

-- A display name is a registration identifier too. Triggers avoid a unique-index
-- migration failure if older databases already contain duplicate legacy names.
CREATE TRIGGER IF NOT EXISTS accounts_unique_name_insert
BEFORE INSERT ON accounts
WHEN EXISTS (SELECT 1 FROM accounts WHERE lower(trim(name)) = lower(trim(NEW.name)))
BEGIN
  SELECT RAISE(ABORT, '账号名字已被注册');
END;
CREATE TRIGGER IF NOT EXISTS accounts_unique_name_update
BEFORE UPDATE OF name ON accounts
WHEN EXISTS (SELECT 1 FROM accounts WHERE id <> OLD.id AND lower(trim(name)) = lower(trim(NEW.name)))
BEGIN
  SELECT RAISE(ABORT, '账号名字已被注册');
END;

-- One authorized administrator phone. Its Android Keystore private key never leaves the device.
CREATE TABLE IF NOT EXISTS admin_devices (
  device_id TEXT PRIMARY KEY,
  public_key TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '管理员手机',
  created_at TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_device_challenges (
  nonce TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_device_challenges_expiry
  ON admin_device_challenges(expires_at);
