-- P3: IDENTIFY budgets and reservation state machine.

CREATE TABLE identify_budgets (
    discord_application_id text PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    total integer NOT NULL CHECK (total > 0),
    remaining_local integer NOT NULL CHECK (remaining_local >= 0),
    reset_after_ms bigint NOT NULL CHECK (reset_after_ms >= 0),
    max_concurrency integer NOT NULL CHECK (max_concurrency > 0),
    rollback_reserve integer NOT NULL DEFAULT 2 CHECK (rollback_reserve >= 0),
    floor integer NOT NULL DEFAULT 5 CHECK (floor >= 0),
    reconciled_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT identify_budgets_app_org_uniq UNIQUE (discord_application_id, org_id)
);

CREATE TABLE identify_reservations (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    discord_application_id text NOT NULL,
    deployment_id uuid,
    shard_id integer NOT NULL CHECK (shard_id >= 0),
    bucket integer NOT NULL CHECK (bucket >= 0),
    state text NOT NULL CHECK (state IN ('held','identify_sent','ready','released','failed_after_identify')),
    identify_sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT identify_reservations_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT identify_reservations_budget_fk FOREIGN KEY (discord_application_id, org_id)
        REFERENCES identify_budgets(discord_application_id, org_id),
    CONSTRAINT identify_release_before_send CHECK (
        (state = 'released' AND identify_sent_at IS NULL)
        OR state <> 'released'
    ),
    CONSTRAINT identify_consumed_has_timestamp CHECK (
        state NOT IN ('identify_sent','ready','failed_after_identify') OR identify_sent_at IS NOT NULL
    )
);

CREATE INDEX identify_reservation_bucket_idx
    ON identify_reservations(discord_application_id, bucket, created_at DESC);

CREATE TABLE identify_breakers (
    discord_application_id text PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    tripped boolean NOT NULL DEFAULT false,
    failure_count integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    last_failure_at timestamptz,
    human_reset_at timestamptz,
    CONSTRAINT identify_breakers_budget_fk FOREIGN KEY (discord_application_id, org_id)
        REFERENCES identify_budgets(discord_application_id, org_id)
);

ALTER TABLE identify_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE identify_budgets FORCE ROW LEVEL SECURITY;
CREATE POLICY identify_budgets_tenant ON identify_budgets
    USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
ALTER TABLE identify_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE identify_reservations FORCE ROW LEVEL SECURITY;
CREATE POLICY identify_reservations_tenant ON identify_reservations
    USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
ALTER TABLE identify_breakers ENABLE ROW LEVEL SECURITY;
ALTER TABLE identify_breakers FORCE ROW LEVEL SECURITY;
CREATE POLICY identify_breakers_tenant ON identify_breakers
    USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());

GRANT SELECT, INSERT, UPDATE ON identify_budgets, identify_reservations, identify_breakers TO sentrix_app;
