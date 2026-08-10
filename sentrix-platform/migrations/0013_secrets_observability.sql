-- P5: envelope-encrypted secrets and durable metering samples.

CREATE TABLE environment_secrets (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    environment_id uuid NOT NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 128),
    provider text NOT NULL CHECK (provider IN ('tmpfs_file','env')),
    version bigint NOT NULL CHECK (version > 0),
    ciphertext bytea NOT NULL,
    wrapped_dek bytea NOT NULL,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{16}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    rotated_at timestamptz,
    CONSTRAINT environment_secrets_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT environment_secrets_env_fk FOREIGN KEY (environment_id, org_id)
        REFERENCES environments(id, org_id),
    CONSTRAINT environment_secrets_version_uniq UNIQUE (environment_id, name, version)
);

CREATE TABLE usage_samples (
    org_id uuid NOT NULL REFERENCES organizations(id),
    environment_id uuid NOT NULL,
    sampled_at timestamptz NOT NULL,
    cpu_millis bigint NOT NULL CHECK (cpu_millis >= 0),
    memory_bytes bigint NOT NULL CHECK (memory_bytes >= 0),
    egress_bytes bigint NOT NULL CHECK (egress_bytes >= 0),
    log_bytes bigint NOT NULL CHECK (log_bytes >= 0),
    CONSTRAINT usage_samples_env_fk FOREIGN KEY (environment_id, org_id)
        REFERENCES environments(id, org_id),
    PRIMARY KEY (environment_id, sampled_at)
);

CREATE TABLE log_quota_state (
    org_id uuid PRIMARY KEY REFERENCES organizations(id),
    window_started_at timestamptz NOT NULL,
    bytes_accepted bigint NOT NULL DEFAULT 0 CHECK (bytes_accepted >= 0),
    bytes_dropped bigint NOT NULL DEFAULT 0 CHECK (bytes_dropped >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE environment_secrets ENABLE ROW LEVEL SECURITY;
ALTER TABLE environment_secrets FORCE ROW LEVEL SECURITY;
CREATE POLICY environment_secrets_tenant ON environment_secrets USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
ALTER TABLE usage_samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_samples FORCE ROW LEVEL SECURITY;
CREATE POLICY usage_samples_tenant ON usage_samples USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
ALTER TABLE log_quota_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE log_quota_state FORCE ROW LEVEL SECURITY;
CREATE POLICY log_quota_state_tenant ON log_quota_state USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());

-- The public app can create/rotate ciphertext but never receives a generic
-- clear-text value column because none exists in the schema.
GRANT SELECT, INSERT ON environment_secrets TO sentrix_app;
GRANT SELECT, INSERT ON usage_samples TO sentrix_app;
GRANT SELECT, INSERT, UPDATE ON log_quota_state TO sentrix_app;
