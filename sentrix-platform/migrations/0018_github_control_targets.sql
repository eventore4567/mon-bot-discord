-- GitHub webhooks arrive without a tenant session. Mirror only the minimum
-- routing metadata outside RLS; actual build creation still happens inside the
-- target tenant transaction.

CREATE TABLE github_control_repositories (
    project_id uuid PRIMARY KEY,
    org_id uuid NOT NULL,
    repository text NOT NULL CHECK (length(repository) BETWEEN 3 AND 512),
    default_branch text NOT NULL CHECK (length(default_branch) BETWEEN 1 AND 255),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX github_control_repository_unique
    ON github_control_repositories (lower(repository));

CREATE TABLE github_control_targets (
    environment_id uuid PRIMARY KEY,
    org_id uuid NOT NULL,
    project_id uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX github_control_targets_project_idx
    ON github_control_targets (project_id, org_id);

REVOKE ALL ON github_control_repositories, github_control_targets FROM PUBLIC;
REVOKE ALL ON github_control_repositories, github_control_targets FROM sentrix_app;

CREATE OR REPLACE FUNCTION public.sentrix_mirror_github_project()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
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
        DELETE FROM public.github_control_repositories WHERE project_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER projects_mirror_github_control
AFTER INSERT OR UPDATE OF repo_full_name, default_branch, status
ON projects
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
    IF NEW.status = 'active' THEN
        -- environments/bots are FORCE RLS. Infrastructure/bootstrap inserts can
        -- legitimately arrive without app.current_org, while tenant writes have
        -- already passed the environment WITH CHECK policy before this AFTER
        -- trigger runs. Scope the lookup to NEW.org_id, then restore the caller's
        -- original transaction-local context so this trigger never leaks tenant
        -- state into the rest of the transaction.
        v_previous_org := current_setting('app.current_org', true);
        PERFORM set_config('app.current_org', NEW.org_id::text, true);

        SELECT b.project_id INTO v_project_id
          FROM public.bots b
         WHERE b.id = NEW.bot_id AND b.org_id = NEW.org_id;

        PERFORM set_config(
            'app.current_org',
            COALESCE(v_previous_org, ''),
            true
        );

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
        END IF;
    ELSE
        DELETE FROM public.github_control_targets WHERE environment_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER environments_mirror_github_control
AFTER INSERT OR UPDATE OF bot_id, status
ON environments
FOR EACH ROW EXECUTE FUNCTION public.sentrix_mirror_github_environment();

CREATE OR REPLACE FUNCTION public.sentrix_refresh_github_control()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_org_id uuid;
    v_count integer := 0;
BEGIN
    v_org_id := public.sentrix_current_org();

    DELETE FROM public.github_control_targets WHERE org_id = v_org_id;
    DELETE FROM public.github_control_repositories WHERE org_id = v_org_id;

    INSERT INTO public.github_control_repositories (
        project_id, org_id, repository, default_branch
    )
    SELECT p.id, p.org_id, lower(p.repo_full_name), p.default_branch
      FROM public.projects p
     WHERE p.org_id = v_org_id
       AND p.status = 'active'
       AND p.repo_full_name IS NOT NULL;

    INSERT INTO public.github_control_targets (environment_id, org_id, project_id)
    SELECT e.id, e.org_id, b.project_id
      FROM public.environments e
      JOIN public.bots b ON b.id = e.bot_id AND b.org_id = e.org_id
     WHERE e.org_id = v_org_id
       AND e.status = 'active'
       AND b.status = 'active';

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.sentrix_github_targets(
    p_repository text,
    p_ref text
)
RETURNS TABLE (
    org_id uuid,
    environment_id uuid
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, public
AS $$
    SELECT r.org_id, t.environment_id
      FROM public.github_control_repositories r
      JOIN public.github_control_targets t
        ON t.project_id = r.project_id AND t.org_id = r.org_id
     WHERE r.repository = lower(p_repository)
       AND p_ref = 'refs/heads/' || r.default_branch
     ORDER BY t.environment_id
$$;

REVOKE ALL ON FUNCTION public.sentrix_mirror_github_project() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_mirror_github_environment() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_refresh_github_control() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_github_targets(text, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.sentrix_refresh_github_control() TO sentrix_app;
GRANT EXECUTE ON FUNCTION public.sentrix_github_targets(text, text) TO sentrix_app;
