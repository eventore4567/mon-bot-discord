-- Hosting workers: authenticated build claims, immutable release publication,
-- automatic deployment queueing and DB-backed runtime reconciliation.

CREATE TABLE control_workers (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('builder', 'orchestrator')),
    name text NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 128),
    token_sha256 bytea NOT NULL CHECK (octet_length(token_sha256) = 32),
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    last_seen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

REVOKE ALL ON control_workers FROM PUBLIC;
REVOKE ALL ON control_workers FROM sentrix_app;

ALTER TABLE environments
    ADD COLUMN auto_deploy boolean NOT NULL DEFAULT true;

ALTER TABLE builds
    ADD COLUMN attempt_no integer NOT NULL DEFAULT 0 CHECK (attempt_no >= 0),
    ADD COLUMN lease_worker_id uuid REFERENCES control_workers(id),
    ADD COLUMN lease_expires_at timestamptz;

ALTER TABLE releases
    ADD COLUMN image_ref text CHECK (
        image_ref IS NULL OR length(image_ref) BETWEEN 1 AND 768
    );

ALTER TABLE deployments
    ADD COLUMN previous_image_ref text,
    ADD COLUMN target_generation bigint,
    ADD COLUMN health_deadline timestamptz;

CREATE INDEX builds_claim_idx
    ON builds (status, lease_expires_at, created_at);

CREATE UNIQUE INDEX deployment_effect_once_idx
    ON deployment_effects (deployment_id, step);

CREATE OR REPLACE FUNCTION public.sentrix_builder_claim(
    p_worker_id uuid,
    p_token_sha256 bytea,
    p_lease_seconds integer DEFAULT 120
)
RETURNS TABLE (
    build_id uuid,
    org_id uuid,
    environment_id uuid,
    repository text,
    commit_sha text,
    library text,
    runtime_mode text,
    lease_attempt integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_lease_seconds < 30 OR p_lease_seconds > 1800 THEN
        RAISE EXCEPTION 'invalid build lease' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.control_workers w
         WHERE w.id = p_worker_id
           AND w.kind = 'builder'
           AND w.status = 'active'
           AND w.token_sha256 = p_token_sha256
    ) THEN
        RAISE EXCEPTION 'builder authentication failed' USING ERRCODE = '42501';
    END IF;

    UPDATE public.control_workers
       SET last_seen_at = now(), updated_at = now()
     WHERE id = p_worker_id;

    RETURN QUERY
    WITH candidate AS (
        SELECT b.id
          FROM public.builds b
          JOIN public.environments e ON e.id = b.environment_id AND e.org_id = b.org_id
          JOIN public.bots bot ON bot.id = e.bot_id AND bot.org_id = e.org_id
          JOIN public.projects p ON p.id = bot.project_id AND p.org_id = bot.org_id
         WHERE p.repo_full_name IS NOT NULL
           AND p.status = 'active'
           AND bot.status = 'active'
           AND e.status = 'active'
           AND (
                b.status = 'queued'
                OR (
                    b.status IN ('building', 'scanning')
                    AND b.lease_expires_at IS NOT NULL
                    AND b.lease_expires_at <= now()
                )
           )
         ORDER BY b.created_at, b.id
         FOR UPDATE OF b SKIP LOCKED
         LIMIT 1
    ), claimed AS (
        UPDATE public.builds b
           SET status = 'building',
               attempt_no = b.attempt_no + 1,
               lease_worker_id = p_worker_id,
               lease_expires_at = now() + make_interval(secs => p_lease_seconds),
               error = NULL,
               updated_at = now()
          FROM candidate c
         WHERE b.id = c.id
        RETURNING b.id, b.org_id, b.environment_id, b.commit_sha, b.attempt_no
    )
    SELECT c.id,
           c.org_id,
           c.environment_id,
           p.repo_full_name,
           c.commit_sha,
           bot.library,
           e.runtime_mode,
           c.attempt_no
      FROM claimed c
      JOIN public.environments e ON e.id = c.environment_id AND e.org_id = c.org_id
      JOIN public.bots bot ON bot.id = e.bot_id AND bot.org_id = e.org_id
      JOIN public.projects p ON p.id = bot.project_id AND p.org_id = bot.org_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.sentrix_builder_report(
    p_worker_id uuid,
    p_token_sha256 bytea,
    p_build_id uuid,
    p_lease_attempt integer,
    p_outcome text,
    p_image_ref text,
    p_image_digest text,
    p_error text,
    p_release_id uuid,
    p_deployment_id uuid
)
RETURNS TABLE (
    release_id uuid,
    deployment_id uuid,
    final_status text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_build public.builds%ROWTYPE;
    v_config_hash text;
    v_secret_version bigint;
    v_identity_key text;
    v_release_id uuid;
    v_deployment_id uuid;
    v_auto_deploy boolean;
    v_runtime_mode text;
    v_secret_provider text;
    v_library text;
BEGIN
    IF p_outcome NOT IN ('succeeded', 'rejected', 'failed') THEN
        RAISE EXCEPTION 'invalid build outcome' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.control_workers w
         WHERE w.id = p_worker_id
           AND w.kind = 'builder'
           AND w.status = 'active'
           AND w.token_sha256 = p_token_sha256
    ) THEN
        RAISE EXCEPTION 'builder authentication failed' USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_build
      FROM public.builds
     WHERE id = p_build_id
     FOR UPDATE;

    IF v_build.id IS NULL
       OR v_build.lease_worker_id IS DISTINCT FROM p_worker_id
       OR v_build.attempt_no <> p_lease_attempt
       OR v_build.status NOT IN ('building', 'scanning') THEN
        RAISE EXCEPTION 'stale or unowned build lease' USING ERRCODE = '42501';
    END IF;

    IF p_outcome <> 'succeeded' THEN
        UPDATE public.builds
           SET status = p_outcome,
               error = left(COALESCE(p_error, 'build failed'), 4000),
               lease_worker_id = NULL,
               lease_expires_at = NULL,
               updated_at = now()
         WHERE id = p_build_id;

        RETURN QUERY SELECT NULL::uuid, NULL::uuid, p_outcome;
        RETURN;
    END IF;

    IF p_image_digest IS NULL
       OR p_image_digest !~ '^sha256:[0-9a-f]{64}$'
       OR p_image_ref IS NULL
       OR position('@' || p_image_digest IN p_image_ref) = 0 THEN
        RAISE EXCEPTION 'immutable image reference required' USING ERRCODE = '22023';
    END IF;

    SELECT e.auto_deploy,
           e.runtime_mode,
           e.secret_provider,
           bot.library
      INTO v_auto_deploy, v_runtime_mode, v_secret_provider, v_library
      FROM public.environments e
      JOIN public.bots bot ON bot.id = e.bot_id AND bot.org_id = e.org_id
     WHERE e.id = v_build.environment_id
       AND e.org_id = v_build.org_id;

    v_config_hash := encode(
        sha256(
            convert_to(
                concat_ws(':', v_runtime_mode, v_secret_provider, v_library),
                'UTF8'
            )
        ),
        'hex'
    );

    SELECT COALESCE(sum(latest.version), 0)::bigint
      INTO v_secret_version
      FROM (
          SELECT max(es.version) AS version
            FROM public.environment_secrets es
           WHERE es.environment_id = v_build.environment_id
             AND es.org_id = v_build.org_id
           GROUP BY es.name
      ) AS latest;

    v_identity_key := encode(
        sha256(
            convert_to(
                substring(p_image_digest FROM 8)
                || ':' || v_config_hash
                || ':' || v_secret_version::text,
                'UTF8'
            )
        ),
        'hex'
    );

    INSERT INTO public.releases (
        id, org_id, environment_id, build_id, image_digest, image_ref,
        config_hash, secret_version, identity_key
    ) VALUES (
        p_release_id, v_build.org_id, v_build.environment_id, v_build.id,
        p_image_digest, p_image_ref, v_config_hash, v_secret_version,
        v_identity_key
    )
    ON CONFLICT (org_id, environment_id, identity_key) DO NOTHING;

    SELECT r.id INTO v_release_id
      FROM public.releases r
     WHERE r.org_id = v_build.org_id
       AND r.environment_id = v_build.environment_id
       AND r.identity_key = v_identity_key;

    UPDATE public.builds
       SET status = 'succeeded',
           image_digest = p_image_digest,
           error = NULL,
           lease_worker_id = NULL,
           lease_expires_at = NULL,
           updated_at = now()
     WHERE id = p_build_id;

    IF v_auto_deploy THEN
        INSERT INTO public.deployments (
            id, org_id, environment_id, release_id, previous_release_id,
            idempotency_key
        )
        SELECT p_deployment_id,
               v_build.org_id,
               v_build.environment_id,
               v_release_id,
               (
                   SELECT d.active_release_id
                     FROM public.deployments d
                    WHERE d.org_id = v_build.org_id
                      AND d.environment_id = v_build.environment_id
                      AND d.status = 'succeeded'
                      AND d.active_release_id IS NOT NULL
                    ORDER BY d.updated_at DESC
                    LIMIT 1
               ),
               'auto:' || v_build.environment_id::text || ':' || v_release_id::text
        ON CONFLICT (org_id, idempotency_key) DO NOTHING;

        SELECT d.id INTO v_deployment_id
          FROM public.deployments d
         WHERE d.org_id = v_build.org_id
           AND d.idempotency_key =
               'auto:' || v_build.environment_id::text || ':' || v_release_id::text;
    END IF;

    RETURN QUERY SELECT v_release_id, v_deployment_id, 'succeeded'::text;
END;
$$;

CREATE OR REPLACE FUNCTION public.sentrix_orchestrator_tick(
    p_worker_id uuid,
    p_token_sha256 bytea,
    p_instance_id uuid,
    p_attempt_id uuid,
    p_lease_seconds integer DEFAULT 30,
    p_health_seconds integer DEFAULT 90
)
RETURNS TABLE (
    deployment_id uuid,
    deployment_status text,
    deployment_step text,
    detail text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_dep public.deployments%ROWTYPE;
    v_token bigint;
    v_attempt_no integer;
    v_node_id uuid;
    v_cell_id uuid;
    v_image_ref text;
    v_instance public.instances%ROWTYPE;
    v_status public.instance_status%ROWTYPE;
    v_reason text;
BEGIN
    IF p_lease_seconds < 10 OR p_lease_seconds > 300
       OR p_health_seconds < 15 OR p_health_seconds > 900 THEN
        RAISE EXCEPTION 'invalid orchestrator timing' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.control_workers w
         WHERE w.id = p_worker_id
           AND w.kind = 'orchestrator'
           AND w.status = 'active'
           AND w.token_sha256 = p_token_sha256
    ) THEN
        RAISE EXCEPTION 'orchestrator authentication failed' USING ERRCODE = '42501';
    END IF;

    UPDATE public.control_workers
       SET last_seen_at = now(), updated_at = now()
     WHERE id = p_worker_id;

    SELECT d.* INTO v_dep
      FROM public.deployments d
      LEFT JOIN public.deployment_leases l ON l.deployment_id = d.id
     WHERE d.status IN ('pending', 'running')
       AND (
            l.deployment_id IS NULL
            OR l.worker_id = p_worker_id
            OR l.expires_at <= now()
       )
     ORDER BY d.created_at, d.id
     FOR UPDATE OF d SKIP LOCKED
     LIMIT 1;

    IF v_dep.id IS NULL THEN
        RETURN;
    END IF;

    INSERT INTO public.deployment_leases (
        deployment_id, org_id, worker_id, fencing_token, expires_at
    ) VALUES (
        v_dep.id, v_dep.org_id, p_worker_id, 1,
        now() + make_interval(secs => p_lease_seconds)
    )
    ON CONFLICT (deployment_id) DO UPDATE SET
        worker_id = EXCLUDED.worker_id,
        fencing_token = CASE
            WHEN public.deployment_leases.worker_id = EXCLUDED.worker_id
             AND public.deployment_leases.expires_at > now()
            THEN public.deployment_leases.fencing_token
            ELSE public.deployment_leases.fencing_token + 1
        END,
        expires_at = EXCLUDED.expires_at,
        updated_at = now()
    WHERE public.deployment_leases.worker_id = EXCLUDED.worker_id
       OR public.deployment_leases.expires_at <= now()
    RETURNING fencing_token INTO v_token;

    IF v_token IS NULL THEN
        RETURN;
    END IF;

    UPDATE public.deployments
       SET status = 'running', updated_at = now()
     WHERE id = v_dep.id
       AND status = 'pending';

    SELECT COALESCE(max(a.attempt_no), 0) + 1
      INTO v_attempt_no
      FROM public.deployment_attempts a
     WHERE a.deployment_id = v_dep.id;

    INSERT INTO public.deployment_attempts (
        id, org_id, deployment_id, attempt_no, worker_id,
        fencing_token, step, finished_at
    ) VALUES (
        p_attempt_id, v_dep.org_id, v_dep.id, v_attempt_no,
        p_worker_id::text, v_token, v_dep.step, now()
    );

    IF v_dep.step = 'test' THEN
        SELECT r.image_ref INTO v_image_ref
          FROM public.releases r
         WHERE r.id = v_dep.release_id
           AND r.org_id = v_dep.org_id;

        IF v_image_ref IS NULL THEN
            UPDATE public.deployments
               SET status = 'failed',
                   error = 'release has no immutable image_ref',
                   updated_at = now()
             WHERE id = v_dep.id;
            DELETE FROM public.deployment_leases WHERE deployment_id = v_dep.id;
            RETURN QUERY
                SELECT v_dep.id, 'failed'::text, 'test'::text,
                       'release has no immutable image_ref'::text;
            RETURN;
        END IF;

        UPDATE public.deployments
           SET step = 'prewarm', error = NULL, updated_at = now()
         WHERE id = v_dep.id;
        RETURN QUERY SELECT v_dep.id, 'running'::text, 'prewarm'::text, 'release verified'::text;
        RETURN;
    END IF;

    IF v_dep.step = 'prewarm' THEN
        SELECT e.cell_id INTO v_cell_id
          FROM public.environments e
         WHERE e.id = v_dep.environment_id
           AND e.org_id = v_dep.org_id
           AND e.status = 'active';

        SELECT n.id INTO v_node_id
          FROM public.nodes n
         WHERE n.cell_id = v_cell_id
           AND n.status = 'active'
         ORDER BY n.name, n.id
         LIMIT 1;

        IF v_node_id IS NULL THEN
            UPDATE public.deployments
               SET error = 'no active node in environment cell', updated_at = now()
             WHERE id = v_dep.id;
            RETURN QUERY
                SELECT v_dep.id, 'running'::text, 'prewarm'::text,
                       'waiting for an active node'::text;
            RETURN;
        END IF;

        UPDATE public.deployments
           SET step = 'handover', error = NULL, updated_at = now()
         WHERE id = v_dep.id;
        RETURN QUERY SELECT v_dep.id, 'running'::text, 'handover'::text, 'node selected'::text;
        RETURN;
    END IF;

    IF v_dep.step = 'handover' THEN
        SELECT r.image_ref INTO v_image_ref
          FROM public.releases r
         WHERE r.id = v_dep.release_id
           AND r.org_id = v_dep.org_id;

        SELECT e.cell_id INTO v_cell_id
          FROM public.environments e
         WHERE e.id = v_dep.environment_id
           AND e.org_id = v_dep.org_id;

        SELECT n.id INTO v_node_id
          FROM public.nodes n
         WHERE n.cell_id = v_cell_id
           AND n.status = 'active'
         ORDER BY n.name, n.id
         LIMIT 1;

        IF v_node_id IS NULL OR v_image_ref IS NULL THEN
            UPDATE public.deployments
               SET error = 'handover prerequisites unavailable', updated_at = now()
             WHERE id = v_dep.id;
            RETURN QUERY
                SELECT v_dep.id, 'running'::text, 'handover'::text,
                       'waiting for handover prerequisites'::text;
            RETURN;
        END IF;

        SELECT i.* INTO v_instance
          FROM public.instances i
         WHERE i.env_id = v_dep.environment_id
           AND i.org_id = v_dep.org_id
         FOR UPDATE;

        IF v_instance.id IS NULL THEN
            INSERT INTO public.instances (
                id, org_id, env_id, cell_id, node_id,
                desired_state, image_ref, generation
            ) VALUES (
                p_instance_id, v_dep.org_id, v_dep.environment_id,
                v_cell_id, v_node_id, 'running', v_image_ref, 1
            );

            UPDATE public.deployments
               SET previous_image_ref = NULL,
                   target_generation = 1,
                   health_deadline = now() + make_interval(secs => p_health_seconds),
                   step = 'health',
                   error = NULL,
                   updated_at = now()
             WHERE id = v_dep.id;
        ELSE
            UPDATE public.instances
               SET node_id = v_node_id,
                   desired_state = 'running',
                   image_ref = v_image_ref,
                   generation = generation + 1,
                   updated_at = now()
             WHERE id = v_instance.id;

            UPDATE public.deployments
               SET previous_image_ref = v_instance.image_ref,
                   target_generation = v_instance.generation + 1,
                   health_deadline = now() + make_interval(secs => p_health_seconds),
                   step = 'health',
                   error = NULL,
                   updated_at = now()
             WHERE id = v_dep.id;
        END IF;

        INSERT INTO public.deployment_effects (
            deployment_id, org_id, attempt_id, step, fencing_token
        ) VALUES (
            v_dep.id, v_dep.org_id, p_attempt_id, 'handover', v_token
        ) ON CONFLICT DO NOTHING;

        RETURN QUERY SELECT v_dep.id, 'running'::text, 'health'::text, 'handover requested'::text;
        RETURN;
    END IF;

    IF v_dep.step = 'health' THEN
        SELECT i.* INTO v_instance
          FROM public.instances i
         WHERE i.env_id = v_dep.environment_id
           AND i.org_id = v_dep.org_id;

        IF v_instance.id IS NOT NULL THEN
            SELECT s.* INTO v_status
              FROM public.instance_status s
             WHERE s.instance_id = v_instance.id
               AND s.org_id = v_dep.org_id;
        END IF;

        IF v_status.instance_id IS NOT NULL
           AND v_status.generation = v_dep.target_generation
           AND v_status.observed_state = 'running'
           AND v_status.health = 'healthy' THEN
            UPDATE public.deployments
               SET status = 'succeeded',
                   step = 'done',
                   active_release_id = v_dep.release_id,
                   error = NULL,
                   updated_at = now()
             WHERE id = v_dep.id;
            DELETE FROM public.deployment_leases WHERE deployment_id = v_dep.id;
            RETURN QUERY SELECT v_dep.id, 'succeeded'::text, 'done'::text, 'instance healthy'::text;
            RETURN;
        END IF;

        IF (
            v_status.instance_id IS NOT NULL
            AND v_status.generation = v_dep.target_generation
            AND (v_status.observed_state = 'failed' OR v_status.health = 'unhealthy')
        ) OR (v_dep.health_deadline IS NOT NULL AND v_dep.health_deadline <= now()) THEN
            v_reason := CASE
                WHEN v_dep.health_deadline IS NOT NULL AND v_dep.health_deadline <= now()
                THEN 'health deadline exceeded'
                ELSE 'instance reported unhealthy'
            END;

            IF v_dep.previous_image_ref IS NOT NULL AND v_instance.id IS NOT NULL THEN
                UPDATE public.instances
                   SET desired_state = 'running',
                       image_ref = v_dep.previous_image_ref,
                       generation = generation + 1,
                       updated_at = now()
                 WHERE id = v_instance.id;

                UPDATE public.deployments
                   SET status = 'rolled_back',
                       step = 'done',
                       active_release_id = v_dep.previous_release_id,
                       error = v_reason,
                       updated_at = now()
                 WHERE id = v_dep.id;

                INSERT INTO public.deployment_effects (
                    deployment_id, org_id, attempt_id, step, fencing_token
                ) VALUES (
                    v_dep.id, v_dep.org_id, p_attempt_id, 'rollback', v_token
                ) ON CONFLICT DO NOTHING;

                DELETE FROM public.deployment_leases WHERE deployment_id = v_dep.id;
                RETURN QUERY
                    SELECT v_dep.id, 'rolled_back'::text, 'done'::text, v_reason;
                RETURN;
            END IF;

            IF v_instance.id IS NOT NULL THEN
                UPDATE public.instances
                   SET desired_state = 'stopped',
                       generation = generation + 1,
                       updated_at = now()
                 WHERE id = v_instance.id;
            END IF;

            UPDATE public.deployments
               SET status = 'failed',
                   step = 'done',
                   error = v_reason,
                   updated_at = now()
             WHERE id = v_dep.id;
            DELETE FROM public.deployment_leases WHERE deployment_id = v_dep.id;
            RETURN QUERY SELECT v_dep.id, 'failed'::text, 'done'::text, v_reason;
            RETURN;
        END IF;

        UPDATE public.deployment_leases
           SET expires_at = now() + make_interval(secs => p_lease_seconds),
               updated_at = now()
         WHERE deployment_id = v_dep.id
           AND worker_id = p_worker_id
           AND fencing_token = v_token;
        RETURN QUERY SELECT v_dep.id, 'running'::text, 'health'::text, 'waiting for health'::text;
        RETURN;
    END IF;

    UPDATE public.deployments
       SET status = 'failed', error = 'unknown deployment step', updated_at = now()
     WHERE id = v_dep.id;
    DELETE FROM public.deployment_leases WHERE deployment_id = v_dep.id;
    RETURN QUERY SELECT v_dep.id, 'failed'::text, v_dep.step, 'unknown deployment step'::text;
END;
$$;

REVOKE ALL ON FUNCTION public.sentrix_builder_claim(uuid, bytea, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_builder_report(
    uuid, bytea, uuid, integer, text, text, text, text, uuid, uuid
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_orchestrator_tick(
    uuid, bytea, uuid, uuid, integer, integer
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.sentrix_builder_claim(uuid, bytea, integer) TO sentrix_app;
GRANT EXECUTE ON FUNCTION public.sentrix_builder_report(
    uuid, bytea, uuid, integer, text, text, text, text, uuid, uuid
) TO sentrix_app;
GRANT EXECUTE ON FUNCTION public.sentrix_orchestrator_tick(
    uuid, bytea, uuid, uuid, integer, integer
) TO sentrix_app;
