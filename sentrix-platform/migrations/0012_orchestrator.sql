-- P4: durable deployment workflow, leases, attempts, fencing and idempotency.

CREATE TABLE deployments (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    environment_id uuid NOT NULL,
    release_id uuid NOT NULL,
    previous_release_id uuid,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','succeeded','rolled_back','failed','cancelled')),
    step text NOT NULL DEFAULT 'test',
    active_release_id uuid,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT deployments_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT deployments_environment_fk FOREIGN KEY (environment_id, org_id)
        REFERENCES environments(id, org_id),
    CONSTRAINT deployments_release_fk FOREIGN KEY (release_id, org_id)
        REFERENCES releases(id, org_id),
    CONSTRAINT deployments_previous_release_fk FOREIGN KEY (previous_release_id, org_id)
        REFERENCES releases(id, org_id),
    CONSTRAINT deployments_active_release_fk FOREIGN KEY (active_release_id, org_id)
        REFERENCES releases(id, org_id),
    CONSTRAINT deployments_attempt_identity UNIQUE (org_id, idempotency_key)
);

CREATE TABLE deployment_leases (
    deployment_id uuid PRIMARY KEY,
    org_id uuid NOT NULL,
    worker_id text NOT NULL,
    fencing_token bigint NOT NULL CHECK (fencing_token > 0),
    expires_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT deployment_leases_deployment_fk FOREIGN KEY (deployment_id, org_id)
        REFERENCES deployments(id, org_id) ON DELETE CASCADE
);

CREATE TABLE deployment_attempts (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    deployment_id uuid NOT NULL,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    worker_id text NOT NULL,
    fencing_token bigint NOT NULL CHECK (fencing_token > 0),
    step text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error text,
    CONSTRAINT deployment_attempts_deployment_fk FOREIGN KEY (deployment_id, org_id)
        REFERENCES deployments(id, org_id) ON DELETE CASCADE,
    CONSTRAINT deployment_attempts_no_uniq UNIQUE (deployment_id, attempt_no)
);

CREATE TABLE deployment_effects (
    deployment_id uuid NOT NULL,
    org_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    step text NOT NULL,
    fencing_token bigint NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (deployment_id, attempt_id, step),
    CONSTRAINT deployment_effects_deployment_fk FOREIGN KEY (deployment_id, org_id)
        REFERENCES deployments(id, org_id) ON DELETE CASCADE
);

ALTER TABLE deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployments FORCE ROW LEVEL SECURITY;
CREATE POLICY deployments_tenant ON deployments USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
ALTER TABLE deployment_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployment_leases FORCE ROW LEVEL SECURITY;
CREATE POLICY deployment_leases_tenant ON deployment_leases USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
ALTER TABLE deployment_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployment_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY deployment_attempts_tenant ON deployment_attempts USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
ALTER TABLE deployment_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployment_effects FORCE ROW LEVEL SECURITY;
CREATE POLICY deployment_effects_tenant ON deployment_effects USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());

GRANT SELECT, INSERT, UPDATE ON deployments, deployment_leases, deployment_attempts TO sentrix_app;
GRANT SELECT, INSERT ON deployment_effects TO sentrix_app;
