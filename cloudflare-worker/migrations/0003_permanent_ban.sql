-- Add an explicit permanent-ban marker without changing any existing timed bans.
-- Existing account rows stay unchanged (permanently_banned defaults to 0).
ALTER TABLE accounts
ADD COLUMN permanently_banned INTEGER NOT NULL DEFAULT 0
CHECK (permanently_banned IN (0, 1));
