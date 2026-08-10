-- P2: GitHub webhook de-duplication, build jobs and immutable releases.

CREATE TABLE webhook_deliveries (
    delivery_id text PRIMARY KEY CHECK (length(delivery_id) BETWEEN 1 AND 128),
    org_id uuid NOT NULL REFERENCES organizations(id),
    repository text NOT NULL CHECK (length(repository) BETWEEN 1 AND 512),
    event text NOT NULL CHECK (length(event) BETWEEN 1 AND 64),
    received_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT webhook_deliveries_id_org_uniq UNIQUE (delivery_id, org_id)
);

CREATE TABLE builds (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    environment_id uuid NOT NULL,
    delivery_id text,
    commit_sha text NOT NULL CHECK (commit_sha ~ '^[0-9a-f]{40}$'),
    cache_key text NOT NULL CHECK (cache_key ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','building','scanning','succeeded','rejected','failed')),
    image_digest text CHECK (image_digest IS NULL OR image_digest ~ '^sha256:[0-9a-f]{64}$'),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT builds_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT builds_environment_fk FOREIGN KEY (environment_id, org_id)
        REFERENCES environments(id, org_id),
    CONSTRAINT builds_delivery_fk FOREIGN KEY (delivery_id, org_id)
        REFERENCES webhook_deliveries(delivery_id, org_id),
    CONSTRAINT builds_cache_org_uniq UNIQUE (org_id, environment_id, cache_key)
);

CREATE TABLE releases (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    environment_id uuid NOT NULL,
    build_id uuid,
    image_digest text NOT NULL CHECK (image_digest ~ '^sha256:[0-9a-f]{64}$'),
    config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    secret_version bigint NOT NULL CHECK (secret_version >= 0),
    identity_key text NOT NULL CHECK (identity_key ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT releases_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT releases_environment_fk FOREIGN KEY (environment_id, org_id)
        REFERENCES environments(id, org_id),
    CONSTRAINT releases_build_fk FOREIGN KEY (build_id, org_id)
        REFERENCES builds(id, org_id),
    CONSTRAINT releases_identity_uniq UNIQUE (org_id, environment_id, identity_key)
);

CREATE INDEX builds_org_status_idx ON builds(org_id, status);
CREATE INDEX releases_org_env_idx ON releases(org_id, environment_id, created_at DESC);

ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY webhook_deliveries_tenant ON webhook_deliveries
    USING (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

ALTER TABLE builds ENABLE ROW LEVEL SECURITY;
ALTER TABLE builds FORCE ROW LEVEL SECURITY;
CREATE POLICY builds_tenant ON builds
    USING (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

ALTER TABLE releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE releases FORCE ROW LEVEL SECURITY;
CREATE POLICY releases_tenant ON releases
    USING (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

GRANT SELECT, INSERT ON webhook_deliveries TO sentrix_app;
GRANT SELECT, INSERT, UPDATE ON builds TO sentrix_app;
GRANT SELECT, INSERT ON releases TO sentrix_app;
REVOKE UPDATE, DELETE ON releases FROM sentrix_app;
