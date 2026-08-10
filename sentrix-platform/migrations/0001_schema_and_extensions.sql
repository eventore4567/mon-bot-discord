-- 0001 : socle. Table de suivi des migrations + cellules.
-- Forward-only : ce fichier est immuable une fois applique (checksum verifie).

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text        PRIMARY KEY,
    checksum    text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Cellule = unite de placement. Une seule en V1, mais adressee des le depart
-- pour que cell_id soit une vraie cle etrangere (porte a sens unique n.2).
CREATE TABLE IF NOT EXISTS cells (
    id          uuid        PRIMARY KEY,
    name        text        NOT NULL UNIQUE,
    region      text        NOT NULL,
    status      text        NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'draining', 'disabled')),
    created_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO cells (id, name, region, status)
VALUES ('01920000-0000-7000-8000-000000000001', 'cell-eu-1', 'eu-west', 'active')
ON CONFLICT (id) DO NOTHING;
