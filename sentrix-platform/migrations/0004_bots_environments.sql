-- 0004 : bots et environnements.
--
-- Les FK sont COMPOSITES : (parent_id, org_id) -> parent(id, org_id).
-- Consequence : un bot de l'org A ne PEUT PAS referencer un projet de l'org B.
-- Ce n'est pas une verification que le code pense a faire, c'est une
-- impossibilite structurelle (violation 23503 au niveau PostgreSQL).

CREATE TABLE bots (
    id         uuid        PRIMARY KEY,
    org_id     uuid        NOT NULL REFERENCES organizations(id),
    project_id uuid        NOT NULL,
    name       text        NOT NULL,
    library    text        NOT NULL DEFAULT 'discordpy'
                           CHECK (library IN ('discordpy', 'discordjs', 'nextcord', 'disnake')),
    status     text        NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'deleted')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT bots_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT bots_project_fk FOREIGN KEY (project_id, org_id)
        REFERENCES projects (id, org_id)
);

CREATE INDEX bots_org_idx ON bots (org_id);
CREATE INDEX bots_project_idx ON bots (project_id);

CREATE TABLE environments (
    id                            uuid        PRIMARY KEY,
    org_id                        uuid        NOT NULL REFERENCES organizations(id),
    bot_id                        uuid        NOT NULL,
    kind                          text        NOT NULL
                                              CHECK (kind IN ('prod', 'canary')),

    -- Identifiant de l'application Discord. NULL tant que non declare.
    -- Une revendication NON VERIFIEE ne reserve jamais l'identifiant globalement :
    -- sinon un attaquant pourrait saisir l'application publique d'un tiers en
    -- premier et bloquer son proprietaire legitime (squatting / deni de service).
    -- L'unicite globale ne s'active qu'apres verification de propriete.
    discord_application_id        text,
    discord_application_verified_at timestamptz,

    cell_id                       uuid        NOT NULL REFERENCES cells(id),
    runtime_mode                  text        NOT NULL DEFAULT 'generic'
                                              CHECK (runtime_mode IN ('managed', 'generic')),
    secret_provider               text        NOT NULL DEFAULT 'env'
                                              CHECK (secret_provider IN ('tmpfs_file', 'env')),
    status                        text        NOT NULL DEFAULT 'active'
                                              CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at                    timestamptz NOT NULL DEFAULT now(),
    updated_at                    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT environments_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT environments_bot_kind_uniq UNIQUE (bot_id, kind),
    CONSTRAINT environments_bot_fk FOREIGN KEY (bot_id, org_id)
        REFERENCES bots (id, org_id),

    -- verified_at ne peut pas exister sans application declaree.
    CONSTRAINT environments_verified_requires_app CHECK (
        discord_application_verified_at IS NULL OR discord_application_id IS NOT NULL
    )
);

-- Unicite GLOBALE uniquement pour les applications VERIFIEES.
-- Deux tenants peuvent declarer le meme ID tant qu'aucun n'en a prouve la
-- propriete. Le passage a verified_at est l'operation atomique qui reserve
-- l'application ; une seconde verification du meme ID echoue en 23505.
CREATE UNIQUE INDEX environments_discord_app_verified_uniq
    ON environments (discord_application_id)
    WHERE discord_application_id IS NOT NULL
      AND discord_application_verified_at IS NOT NULL;

CREATE INDEX environments_org_idx ON environments (org_id);
CREATE INDEX environments_bot_idx ON environments (bot_id);
