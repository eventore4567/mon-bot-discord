-- 0002 : tenancy racine.

CREATE TABLE organizations (
    id          uuid        PRIMARY KEY,
    name        text        NOT NULL,
    slug        text        NOT NULL UNIQUE,
    plan        text        NOT NULL DEFAULT 'free'
                            CHECK (plan IN ('free', 'pro', 'enterprise')),
    status      text        NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Les utilisateurs sont GLOBAUX (un compte Discord peut appartenir a N orgs).
-- Cette table n'est donc volontairement PAS soumise a RLS par org_id.
CREATE TABLE users (
    id              uuid        PRIMARY KEY,
    discord_user_id text        NOT NULL UNIQUE,
    email           text,
    display_name    text        NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_login_at   timestamptz
);

-- Table de jonction : porte org_id, donc soumise a RLS.
CREATE TABLE org_members (
    org_id     uuid        NOT NULL REFERENCES organizations(id),
    user_id    uuid        NOT NULL REFERENCES users(id),
    role       text        NOT NULL DEFAULT 'member'
                           CHECK (role IN ('owner', 'admin', 'member')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

CREATE INDEX org_members_user_idx ON org_members (user_id);
