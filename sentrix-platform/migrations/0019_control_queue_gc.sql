-- Control-plane routing rows intentionally have no FK to FORCE-RLS tenant tables:
-- global workers must be able to inspect the tiny queue without bypassing RLS.
-- That means deletion has to be mirrored explicitly and claims must tolerate any
-- stale row left by an interrupted/manual maintenance operation.

CREATE OR REPLACE FUNCTION public.sentrix_mirror_build_control()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.build_control_queue WHERE build_id = OLD.id;
        RETURN OLD;
    END IF;

    IF NEW.status IN ('queued','building','scanning') THEN
        INSERT INTO public.build_control_queue (
            build_id, org_id, status, lease_worker_id, lease_expires_at
        ) VALUES (
            NEW.id, NEW.org_id, NEW.status, NEW.lease_worker_id, NEW.lease_expires_at
        )
        ON CONFLICT (build_id) DO UPDATE SET
            org_id = EXCLUDED.org_id,
            status = EXCLUDED.status,
            lease_worker_id = EXCLUDED.lease_worker_id,
            lease_expires_at = EXCLUDED.lease_expires_at,
            updated_at = now();
    ELSE
        DELETE FROM public.build_control_queue WHERE build_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS builds_mirror_control_queue ON public.builds;
CREATE TRIGGER builds_mirror_control_queue
AFTER INSERT OR DELETE OR UPDATE OF status, lease_worker_id, lease_expires_at
ON public.builds
FOR EACH ROW EXECUTE FUNCTION public.sentrix_mirror_build_control();

CREATE OR REPLACE FUNCTION public.sentrix_mirror_deployment_control()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.deployment_control_queue WHERE deployment_id = OLD.id;
        RETURN OLD;
    END IF;

    IF NEW.status IN ('pending','running') THEN
        INSERT INTO public.deployment_control_queue (
            deployment_id, org_id, status
        ) VALUES (
            NEW.id, NEW.org_id, NEW.status
        )
        ON CONFLICT (deployment_id) DO UPDATE SET
            org_id = EXCLUDED.org_id,
            status = EXCLUDED.status,
            updated_at = now();
    ELSE
        DELETE FROM public.deployment_control_queue WHERE deployment_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS deployments_mirror_control_queue ON public.deployments;
CREATE TRIGGER deployments_mirror_control_queue
AFTER INSERT OR DELETE OR UPDATE OF status
ON public.deployments
FOR EACH ROW EXECUTE FUNCTION public.sentrix_mirror_deployment_control();

-- A deleted tenant row can never wedge the global builder. Claims discard stale
-- queue entries and keep looking in the same transaction. Invalid source routing
-- is rejected explicitly instead of occupying a lease forever.
CREATE OR REPLACE FUNCTION public.sentrix_builder_claim(
    p_worker_id uuid,
    p_token_sha256 bytea,
    p_lease_seconds integer DEFAULT 300
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
DECLARE
    v_build_id uuid;
    v_org_id uuid;
    v_claimed_id uuid;
    v_returned bigint;
BEGIN
    IF p_lease_seconds < 30 OR p_lease_seconds > 1800 THEN
        RAISE EXCEPTION 'invalid build lease' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.control_workers w
        WHERE w.id = p_worker_id
          AND w.kind = 'builder'
          AND w.status = 'active'
          AND w.token_sha256 = p_token_sha256
    ) THEN
        RAISE EXCEPTION 'builder authentication failed' USING ERRCODE = '42501';
    END IF;

    LOOP
        v_build_id := NULL;
        v_org_id := NULL;
        v_claimed_id := NULL;

        SELECT q.build_id, q.org_id
          INTO v_build_id, v_org_id
          FROM public.build_control_queue q
         WHERE q.status = 'queued'
            OR (
                q.status IN ('building','scanning')
                AND q.lease_expires_at IS NOT NULL
                AND q.lease_expires_at <= now()
            )
         ORDER BY q.created_at, q.build_id
         FOR UPDATE SKIP LOCKED
         LIMIT 1;

        IF v_build_id IS NULL OR v_org_id IS NULL THEN
            UPDATE public.control_workers
               SET last_seen_at = now(), updated_at = now()
             WHERE id = p_worker_id;
            RETURN;
        END IF;

        PERFORM set_config('app.current_org', v_org_id::text, true);

        UPDATE public.builds b
           SET status = 'building',
               attempt_no = b.attempt_no + 1,
               lease_worker_id = p_worker_id,
               lease_expires_at = now() + make_interval(secs => p_lease_seconds),
               error = NULL,
               updated_at = now()
         WHERE b.id = v_build_id
           AND b.org_id = v_org_id
           AND (
                b.status = 'queued'
                OR (
                    b.status IN ('building','scanning')
                    AND b.lease_expires_at IS NOT NULL
                    AND b.lease_expires_at <= now()
                )
           )
        RETURNING b.id INTO v_claimed_id;

        IF v_claimed_id IS NULL THEN
            -- Orphan/stale mirror row. It is infrastructure metadata, so it is
            -- safe to remove without touching another tenant's data.
            DELETE FROM public.build_control_queue q
             WHERE q.build_id = v_build_id AND q.org_id = v_org_id;
            CONTINUE;
        END IF;

        UPDATE public.control_workers
           SET last_seen_at = now(), updated_at = now()
         WHERE id = p_worker_id;

        RETURN QUERY
        SELECT b.id,
               b.org_id,
               b.environment_id,
               p.repo_full_name,
               b.commit_sha,
               bot.library,
               e.runtime_mode,
               b.attempt_no
          FROM public.builds b
          JOIN public.environments e
            ON e.id = b.environment_id AND e.org_id = b.org_id
          JOIN public.bots bot
            ON bot.id = e.bot_id AND bot.org_id = e.org_id
          JOIN public.projects p
            ON p.id = bot.project_id AND p.org_id = bot.org_id
         WHERE b.id = v_build_id
           AND b.org_id = v_org_id
           AND p.repo_full_name IS NOT NULL
           AND p.status = 'active'
           AND bot.status = 'active'
           AND e.status = 'active';

        GET DIAGNOSTICS v_returned = ROW_COUNT;
        IF v_returned > 0 THEN
            RETURN;
        END IF;

        UPDATE public.builds b
           SET status = 'rejected',
               error = 'build source metadata unavailable',
               lease_worker_id = NULL,
               lease_expires_at = NULL,
               updated_at = now()
         WHERE b.id = v_build_id AND b.org_id = v_org_id;
        -- The mirror trigger removes the queue row; continue to the next job.
    END LOOP;
END;
$$;

-- GitHub routing mirrors follow the same lifecycle rule. Deleted projects and
-- environments cannot remain routable from an unauthenticated webhook request.
CREATE OR REPLACE FUNCTION public.sentrix_mirror_github_project()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.github_control_targets WHERE project_id = OLD.id;
        DELETE FROM public.github_control_repositories WHERE project_id = OLD.id;
        RETURN OLD;
    END IF;

    IF NEW.status = 'active' AND NEW.repo_full_name IS NOT NULL THEN
        INSERT INTO public.github_control_repositories (
            project_id, org_id, repository, default_branch
        ) VALUES (
            NEW.id, NEW.org_id, lower(NEW.repo_full_name), NEW.default_branch
        )
        ON CONFLICT (project_id) DO UPDATE SET
            org_id = EXCLUDED.org_id,
            repository = EXCLUDED.repository,
            default_branch = EXCLUDED.default_branch,
            updated_at = now();
    ELSE
        DELETE FROM public.github_control_targets WHERE project_id = NEW.id;
        DELETE FROM public.github_control_repositories WHERE project_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS projects_mirror_github_control ON public.projects;
CREATE TRIGGER projects_mirror_github_control
AFTER INSERT OR DELETE OR UPDATE OF repo_full_name, default_branch, status
ON public.projects
FOR EACH ROW EXECUTE FUNCTION public.sentrix_mirror_github_project();

CREATE OR REPLACE FUNCTION public.sentrix_mirror_github_environment()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_project_id uuid;
    v_previous_org text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.github_control_targets WHERE environment_id = OLD.id;
        RETURN OLD;
    END IF;

    IF NEW.status = 'active' THEN
        v_previous_org := current_setting('app.current_org', true);
        PERFORM set_config('app.current_org', NEW.org_id::text, true);

        SELECT b.project_id INTO v_project_id
          FROM public.bots b
         WHERE b.id = NEW.bot_id AND b.org_id = NEW.org_id;

        PERFORM set_config('app.current_org', COALESCE(v_previous_org, ''), true);

        IF v_project_id IS NOT NULL THEN
            INSERT INTO public.github_control_targets (
                environment_id, org_id, project_id
            ) VALUES (
                NEW.id, NEW.org_id, v_project_id
            )
            ON CONFLICT (environment_id) DO UPDATE SET
                org_id = EXCLUDED.org_id,
                project_id = EXCLUDED.project_id,
                updated_at = now();
        ELSE
            DELETE FROM public.github_control_targets WHERE environment_id = NEW.id;
        END IF;
    ELSE
        DELETE FROM public.github_control_targets WHERE environment_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS environments_mirror_github_control ON public.environments;
CREATE TRIGGER environments_mirror_github_control
AFTER INSERT OR DELETE OR UPDATE OF bot_id, status
ON public.environments
FOR EACH ROW EXECUTE FUNCTION public.sentrix_mirror_github_environment();

REVOKE ALL ON FUNCTION public.sentrix_mirror_build_control() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_mirror_deployment_control() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_mirror_github_project() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_mirror_github_environment() FROM PUBLIC;
