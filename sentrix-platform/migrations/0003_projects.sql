-- 0003 : projets.
--
-- POINT CENTRAL DE P0 : la contrainte UNIQUE (id, org_id) parait redondante
-- (id est deja PK) mais elle est INDISPENSABLE : c'est la cible des cles
-- etrangeres composites des tables enfant. Sans elle, PostgreSQL refuse
-- FOREIGN KEY (project_id, org_id) REFERENCES projects (id, org_id).

CREATE TABLE projects (
    id                     uuid        PRIMARY KEY,
    org_id                 uuid        NOT NULL REFERENCES organizations(id),
    name                   text        NOT NULL,
    github_installation_id bigint,
    repo_full_name         text,
    default_branch         text        NOT NULL DEFAULT 'main',
    status                 text        NOT NULL DEFAULT 'active'
                                       CHECK (status IN ('active', 'deleted')),
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT projects_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT projects_org_name_uniq UNIQUE (org_id, name)
);

CREATE INDEX projects_org_idx ON projects (org_id);
