-- 0024: make SentriX Hosting provider-neutral (no Discord dependency required).

ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_subject text;
UPDATE users
SET auth_subject = 'legacy:' || discord_user_id
WHERE auth_subject IS NULL;
ALTER TABLE users ALTER COLUMN auth_subject SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS users_auth_subject_uniq ON users(auth_subject);
ALTER TABLE users ALTER COLUMN discord_user_id DROP NOT NULL;

ALTER TABLE bots DROP CONSTRAINT IF EXISTS bots_library_check;
ALTER TABLE bots
    ADD CONSTRAINT bots_library_check
    CHECK (library IN ('python', 'node', 'docker', 'discordpy', 'discordjs', 'nextcord', 'disnake'));
