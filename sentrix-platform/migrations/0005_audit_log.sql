-- 0005 : journal d'audit APPEND-ONLY.
--
-- L'immuabilite ne repose PAS sur la discipline du code : le role applicatif
-- ne recoit tout simplement jamais UPDATE ni DELETE (migration 0007).
-- Une tentative echoue en 42501 (insufficient_privilege).

CREATE TABLE audit_log (
    id            uuid        PRIMARY KEY,
    -- NULL = action plateforme (hors tenant). Ces lignes ne sont jamais
    -- visibles par un tenant : la politique RLS compare org_id a app.current_org,
    -- et NULL = <valeur> est toujours NULL, donc faux.
    org_id        uuid        REFERENCES organizations(id),
    actor_user_id uuid        REFERENCES users(id),
    action        text        NOT NULL,
    target_type   text        NOT NULL,
    target_id     uuid,
    metadata      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    source_ip     inet,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_org_created_idx ON audit_log (org_id, created_at DESC);
CREATE INDEX audit_log_target_idx ON audit_log (target_type, target_id);
