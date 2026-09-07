-- PL/pgSQL exposes RETURNS TABLE column names as variables. The orchestrator
-- returns `deployment_id`, so unqualified SQL references to a column with the
-- same name are ambiguous at runtime. Replace the function with fully qualified
-- queue/lease predicates and use the lease primary-key constraint explicitly.

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
    v_dep_id uuid;
    v_org_id uuid;
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
        SELECT 1 FROM public.control_workers w
        WHERE w.id = p_worker_id
          AND w.kind = 'orchestrator'
          AND w.status = 'active'
          AND w.token_sha256 = p_token_sha256
    ) THEN
        RAISE EXCEPTION 'orchestrator authentication failed' USING ERRCODE = '42501';
    END IF;

    SELECT q.deployment_id, q.org_id
      INTO v_dep_id, v_org_id
      FROM public.deployment_control_queue q
     WHERE q.status IN ('pending','running')
       AND (
            q.lease_worker_id IS NULL
            OR q.lease_worker_id = p_worker_id
            OR q.lease_expires_at <= now()
       )
     ORDER BY CASE WHEN q.status = 'pending' THEN 0 ELSE 1 END,
              q.created_at,
              q.deployment_id
     FOR UPDATE SKIP LOCKED
     LIMIT 1;

    IF v_dep_id IS NULL OR v_org_id IS NULL THEN
        UPDATE public.control_workers w
           SET last_seen_at = now(), updated_at = now()
         WHERE w.id = p_worker_id;
        RETURN;
    END IF;

    UPDATE public.deployment_control_queue q
       SET fencing_token = CASE
               WHEN q.lease_worker_id = p_worker_id
                AND q.lease_expires_at > now()
               THEN q.fencing_token
               ELSE q.fencing_token + 1
           END,
           lease_worker_id = p_worker_id,
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           updated_at = now()
     WHERE q.deployment_id = v_dep_id
    RETURNING q.fencing_token INTO v_token;

    PERFORM set_config('app.current_org', v_org_id::text, true);

    SELECT d.* INTO v_dep
      FROM public.deployments d
     WHERE d.id = v_dep_id AND d.org_id = v_org_id
     FOR UPDATE;

    IF v_dep.id IS NULL OR v_dep.status NOT IN ('pending','running') THEN
        DELETE FROM public.deployment_control_queue q
         WHERE q.deployment_id = v_dep_id;
        RETURN;
    END IF;

    INSERT INTO public.deployment_leases (
        deployment_id, org_id, worker_id, fencing_token, expires_at
    ) VALUES (
        v_dep.id, v_org_id, p_worker_id::text, v_token,
        now() + make_interval(secs => p_lease_seconds)
    )
    ON CONFLICT ON CONSTRAINT deployment_leases_pkey DO UPDATE SET
        worker_id = EXCLUDED.worker_id,
        fencing_token = EXCLUDED.fencing_token,
        expires_at = EXCLUDED.expires_at,
        updated_at = now();

    UPDATE public.deployments d
       SET status = 'running', updated_at = now()
     WHERE d.id = v_dep.id AND d.status = 'pending';

    SELECT COALESCE(max(a.attempt_no), 0) + 1
      INTO v_attempt_no
      FROM public.deployment_attempts a
     WHERE a.deployment_id = v_dep.id;

    INSERT INTO public.deployment_attempts (
        id, org_id, deployment_id, attempt_no, worker_id,
        fencing_token, step, finished_at
    ) VALUES (
        p_attempt_id, v_org_id, v_dep.id, v_attempt_no,
        p_worker_id::text, v_token, v_dep.step, now()
    );

    UPDATE public.control_workers w
       SET last_seen_at = now(), updated_at = now()
     WHERE w.id = p_worker_id;

    IF v_dep.step = 'test' THEN
        SELECT r.image_ref INTO v_image_ref
          FROM public.releases r
         WHERE r.id = v_dep.release_id AND r.org_id = v_org_id;
        IF v_image_ref IS NULL THEN
            UPDATE public.deployments d
               SET status = 'failed',
                   error = 'release has no immutable image_ref',
                   updated_at = now()
             WHERE d.id = v_dep.id;
            RETURN QUERY
                SELECT v_dep.id, 'failed'::text, 'test'::text,
                       'release has no immutable image_ref'::text;
            RETURN;
        END IF;
        UPDATE public.deployments d
           SET step = 'prewarm', error = NULL, updated_at = now()
         WHERE d.id = v_dep.id;
        RETURN QUERY
            SELECT v_dep.id, 'running'::text, 'prewarm'::text, 'release verified'::text;
        RETURN;
    END IF;

    IF v_dep.step = 'prewarm' THEN
        SELECT e.cell_id INTO v_cell_id
          FROM public.environments e
         WHERE e.id = v_dep.environment_id
           AND e.org_id = v_org_id
           AND e.status = 'active';
        SELECT n.id INTO v_node_id
          FROM public.nodes n
         WHERE n.cell_id = v_cell_id AND n.status = 'active'
         ORDER BY n.name, n.id
         LIMIT 1;
        IF v_node_id IS NULL THEN
            UPDATE public.deployments d
               SET error = 'no active node in environment cell', updated_at = now()
             WHERE d.id = v_dep.id;
            RETURN QUERY
                SELECT v_dep.id, 'running'::text, 'prewarm'::text,
                       'waiting for an active node'::text;
            RETURN;
        END IF;
        UPDATE public.deployments d
           SET step = 'handover', error = NULL, updated_at = now()
         WHERE d.id = v_dep.id;
        RETURN QUERY
            SELECT v_dep.id, 'running'::text, 'handover'::text, 'node selected'::text;
        RETURN;
    END IF;

    IF v_dep.step = 'handover' THEN
        SELECT r.image_ref INTO v_image_ref
          FROM public.releases r
         WHERE r.id = v_dep.release_id AND r.org_id = v_org_id;
        SELECT e.cell_id INTO v_cell_id
          FROM public.environments e
         WHERE e.id = v_dep.environment_id AND e.org_id = v_org_id;
        SELECT n.id INTO v_node_id
          FROM public.nodes n
         WHERE n.cell_id = v_cell_id AND n.status = 'active'
         ORDER BY n.name, n.id
         LIMIT 1;
        IF v_node_id IS NULL OR v_image_ref IS NULL THEN
            UPDATE public.deployments d
               SET error = 'handover prerequisites unavailable', updated_at = now()
             WHERE d.id = v_dep.id;
            RETURN QUERY
                SELECT v_dep.id, 'running'::text, 'handover'::text,
                       'waiting for handover prerequisites'::text;
            RETURN;
        END IF;

        SELECT i.* INTO v_instance
          FROM public.instances i
         WHERE i.env_id = v_dep.environment_id AND i.org_id = v_org_id
         FOR UPDATE;

        IF v_instance.id IS NULL THEN
            INSERT INTO public.instances (
                id, org_id, env_id, cell_id, node_id, desired_state, image_ref, generation
            ) VALUES (
                p_instance_id, v_org_id, v_dep.environment_id, v_cell_id,
                v_node_id, 'running', v_image_ref, 1
            );
            UPDATE public.deployments d
               SET previous_image_ref = NULL,
                   target_generation = 1,
                   health_deadline = now() + make_interval(secs => p_health_seconds),
                   step = 'health',
                   error = NULL,
                   updated_at = now()
             WHERE d.id = v_dep.id;
        ELSE
            UPDATE public.instances i
               SET node_id = v_node_id,
                   desired_state = 'running',
                   image_ref = v_image_ref,
                   generation = i.generation + 1,
                   updated_at = now()
             WHERE i.id = v_instance.id;
            UPDATE public.deployments d
               SET previous_image_ref = v_instance.image_ref,
                   target_generation = v_instance.generation + 1,
                   health_deadline = now() + make_interval(secs => p_health_seconds),
                   step = 'health',
                   error = NULL,
                   updated_at = now()
             WHERE d.id = v_dep.id;
        END IF;

        INSERT INTO public.deployment_effects (
            deployment_id, org_id, attempt_id, step, fencing_token
        ) VALUES (v_dep.id, v_org_id, p_attempt_id, 'handover', v_token)
        ON CONFLICT DO NOTHING;
        RETURN QUERY
            SELECT v_dep.id, 'running'::text, 'health'::text, 'handover requested'::text;
        RETURN;
    END IF;

    IF v_dep.step = 'health' THEN
        SELECT i.* INTO v_instance
          FROM public.instances i
         WHERE i.env_id = v_dep.environment_id AND i.org_id = v_org_id;
        IF v_instance.id IS NOT NULL THEN
            SELECT s.* INTO v_status
              FROM public.instance_status s
             WHERE s.instance_id = v_instance.id AND s.org_id = v_org_id;
        END IF;

        IF v_status.instance_id IS NOT NULL
           AND v_status.generation = v_dep.target_generation
           AND v_status.observed_state = 'running'
           AND v_status.health = 'healthy' THEN
            UPDATE public.deployments d
               SET status = 'succeeded',
                   step = 'done',
                   active_release_id = v_dep.release_id,
                   error = NULL,
                   updated_at = now()
             WHERE d.id = v_dep.id;
            RETURN QUERY
                SELECT v_dep.id, 'succeeded'::text, 'done'::text, 'instance healthy'::text;
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
                UPDATE public.instances i
                   SET desired_state = 'running',
                       image_ref = v_dep.previous_image_ref,
                       generation = i.generation + 1,
                       updated_at = now()
                 WHERE i.id = v_instance.id;
                UPDATE public.deployments d
                   SET status = 'rolled_back',
                       step = 'done',
                       active_release_id = v_dep.previous_release_id,
                       error = v_reason,
                       updated_at = now()
                 WHERE d.id = v_dep.id;
                INSERT INTO public.deployment_effects (
                    deployment_id, org_id, attempt_id, step, fencing_token
                ) VALUES (v_dep.id, v_org_id, p_attempt_id, 'rollback', v_token)
                ON CONFLICT DO NOTHING;
                RETURN QUERY
                    SELECT v_dep.id, 'rolled_back'::text, 'done'::text, v_reason;
                RETURN;
            END IF;

            IF v_instance.id IS NOT NULL THEN
                UPDATE public.instances i
                   SET desired_state = 'stopped',
                       generation = i.generation + 1,
                       updated_at = now()
                 WHERE i.id = v_instance.id;
            END IF;
            UPDATE public.deployments d
               SET status = 'failed', step = 'done', error = v_reason, updated_at = now()
             WHERE d.id = v_dep.id;
            RETURN QUERY SELECT v_dep.id, 'failed'::text, 'done'::text, v_reason;
            RETURN;
        END IF;

        UPDATE public.deployment_control_queue q
           SET lease_expires_at = now() + make_interval(secs => p_lease_seconds),
               updated_at = now()
         WHERE q.deployment_id = v_dep.id
           AND q.lease_worker_id = p_worker_id;
        UPDATE public.deployment_leases l
           SET expires_at = now() + make_interval(secs => p_lease_seconds),
               updated_at = now()
         WHERE l.deployment_id = v_dep.id
           AND l.worker_id = p_worker_id::text
           AND l.fencing_token = v_token;
        RETURN QUERY
            SELECT v_dep.id, 'running'::text, 'health'::text, 'waiting for health'::text;
        RETURN;
    END IF;

    UPDATE public.deployments d
       SET status = 'failed', error = 'unknown deployment step', updated_at = now()
     WHERE d.id = v_dep.id;
    RETURN QUERY
        SELECT v_dep.id, 'failed'::text, v_dep.step, 'unknown deployment step'::text;
END;
$$;
