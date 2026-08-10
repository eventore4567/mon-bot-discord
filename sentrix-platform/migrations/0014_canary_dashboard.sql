-- P6: canary/promotion records and explicit destructive-schema confirmation.

CREATE TABLE promotion_gates (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    prod_environment_id uuid NOT NULL,
    canary_environment_id uuid NOT NULL,
    release_id uuid NOT NULL,
    bake_seconds integer NOT NULL CHECK (bake_seconds >= 0),
    canary_healthy boolean NOT NULL DEFAULT false,
    destructive_schema boolean NOT NULL DEFAULT false,
    destructive_confirmed_by uuid,
    destructive_confirmed_at timestamptz,
    promoted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT promotion_gates_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT promotion_prod_fk FOREIGN KEY (prod_environment_id, org_id)
        REFERENCES environments(id, org_id),
    CONSTRAINT promotion_canary_fk FOREIGN KEY (canary_environment_id, org_id)
        REFERENCES environments(id, org_id),
    CONSTRAINT promotion_release_fk FOREIGN KEY (release_id, org_id)
        REFERENCES releases(id, org_id),
    CONSTRAINT promotion_confirmer_member_fk FOREIGN KEY (org_id, destructive_confirmed_by)
        REFERENCES org_members(org_id, user_id),
    CONSTRAINT distinct_canary_environment CHECK (prod_environment_id <> canary_environment_id),
    CONSTRAINT destructive_confirmation_complete CHECK (
        (destructive_confirmed_by IS NULL AND destructive_confirmed_at IS NULL)
        OR (destructive_confirmed_by IS NOT NULL AND destructive_confirmed_at IS NOT NULL)
    ),
    CONSTRAINT no_unconfirmed_destructive_promotion CHECK (
        promoted_at IS NULL OR NOT destructive_schema OR destructive_confirmed_at IS NOT NULL
    )
);

ALTER TABLE promotion_gates ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_gates FORCE ROW LEVEL SECURITY;
CREATE POLICY promotion_gates_tenant ON promotion_gates USING (org_id = public.sentrix_current_org()) WITH CHECK (org_id = public.sentrix_current_org());
GRANT SELECT, INSERT, UPDATE ON promotion_gates TO sentrix_app;
