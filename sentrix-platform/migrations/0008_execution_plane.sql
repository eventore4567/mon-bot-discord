-- 0008 : Execution Plane P1 - etat desire, noeuds, miroir agent et statut observe.
--
-- Les tables tenant restent sous RLS. Le node-agent ne recoit JAMAIS un droit
-- SQL direct sur ces tables : il passe par des fonctions SECURITY DEFINER qui
-- verifient son token et n'exposent que son etat desire.

ALTER TABLE environments
    ADD CONSTRAINT environments_id_org_cell_uniq UNIQUE (id, org_id, cell_id);

CREATE TABLE nodes (
    id                 uuid        PRIMARY KEY,
    cell_id            uuid        NOT NULL REFERENCES cells(id),
    name               text        NOT NULL UNIQUE,
    agent_token_sha256 bytea       NOT NULL CHECK (octet_length(agent_token_sha256) = 32),
    status             text        NOT NULL DEFAULT 'active'
                                  CHECK (status IN ('active', 'draining', 'disabled')),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT nodes_id_cell_uniq UNIQUE (id, cell_id)
);

CREATE TABLE instances (
    id             uuid        PRIMARY KEY,
    org_id         uuid        NOT NULL REFERENCES organizations(id),
    env_id         uuid        NOT NULL,
    cell_id        uuid        NOT NULL,
    node_id        uuid        NOT NULL,
    desired_state  text        NOT NULL DEFAULT 'running'
                               CHECK (desired_state IN ('running', 'stopped')),
    image_ref      text        NOT NULL CHECK (length(image_ref) BETWEEN 1 AND 512),
    command        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    cpu_millis     integer     NOT NULL DEFAULT 500 CHECK (cpu_millis BETWEEN 50 AND 16000),
    memory_mb      integer     NOT NULL DEFAULT 256 CHECK (memory_mb BETWEEN 32 AND 65536),
    pids_limit     integer     NOT NULL DEFAULT 128 CHECK (pids_limit BETWEEN 16 AND 4096),
    generation     bigint      NOT NULL DEFAULT 1 CHECK (generation > 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT instances_id_org_uniq UNIQUE (id, org_id),
    CONSTRAINT instances_env_uniq UNIQUE (env_id),
    CONSTRAINT instances_env_fk FOREIGN KEY (env_id, org_id, cell_id)
        REFERENCES environments (id, org_id, cell_id),
    CONSTRAINT instances_node_fk FOREIGN KEY (node_id, cell_id)
        REFERENCES nodes (id, cell_id),
    CONSTRAINT instances_command_array CHECK (jsonb_typeof(command) = 'array')
);

CREATE INDEX instances_org_idx ON instances (org_id);
CREATE INDEX instances_node_idx ON instances (node_id);

-- Miroir prive pour le plan d'execution. Il n'est JAMAIS accorde a sentrix_app.
-- Cela permet au node-agent de tirer son etat sans desactiver FORCE RLS sur la
-- table tenant `instances`.
CREATE TABLE agent_desired_state (
    instance_id    uuid        PRIMARY KEY,
    org_id         uuid        NOT NULL,
    node_id        uuid        NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    desired_state  text        NOT NULL CHECK (desired_state IN ('running', 'stopped')),
    image_ref      text        NOT NULL,
    command        jsonb       NOT NULL,
    cpu_millis     integer     NOT NULL,
    memory_mb      integer     NOT NULL,
    pids_limit     integer     NOT NULL,
    generation     bigint      NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_desired_node_idx ON agent_desired_state (node_id);

CREATE TABLE instance_status (
    instance_id    uuid        PRIMARY KEY,
    org_id         uuid        NOT NULL,
    observed_state text        NOT NULL CHECK (observed_state IN ('running', 'stopped', 'failed', 'unknown')),
    container_id   text,
    generation     bigint      NOT NULL,
    exit_code      integer,
    health         text        NOT NULL DEFAULT 'unknown'
                               CHECK (health IN ('healthy', 'unhealthy', 'unknown')),
    detail         text,
    changed_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT instance_status_instance_fk FOREIGN KEY (instance_id, org_id)
        REFERENCES instances (id, org_id) ON DELETE CASCADE
);
CREATE INDEX instance_status_org_idx ON instance_status (org_id);

CREATE OR REPLACE FUNCTION public.sentrix_sync_agent_desired()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    INSERT INTO public.agent_desired_state (
        instance_id, org_id, node_id, desired_state, image_ref, command,
        cpu_millis, memory_mb, pids_limit, generation, updated_at
    ) VALUES (
        NEW.id, NEW.org_id, NEW.node_id, NEW.desired_state, NEW.image_ref, NEW.command,
        NEW.cpu_millis, NEW.memory_mb, NEW.pids_limit, NEW.generation, now()
    )
    ON CONFLICT (instance_id) DO UPDATE SET
        org_id = EXCLUDED.org_id,
        node_id = EXCLUDED.node_id,
        desired_state = EXCLUDED.desired_state,
        image_ref = EXCLUDED.image_ref,
        command = EXCLUDED.command,
        cpu_millis = EXCLUDED.cpu_millis,
        memory_mb = EXCLUDED.memory_mb,
        pids_limit = EXCLUDED.pids_limit,
        generation = EXCLUDED.generation,
        updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER instances_sync_agent_desired
AFTER INSERT OR UPDATE OF node_id, desired_state, image_ref, command,
                           cpu_millis, memory_mb, pids_limit, generation
ON instances
FOR EACH ROW EXECUTE FUNCTION public.sentrix_sync_agent_desired();

CREATE OR REPLACE FUNCTION public.sentrix_agent_pull(
    p_node_id uuid,
    p_token_sha256 bytea
)
RETURNS TABLE (
    instance_id uuid,
    desired_state text,
    image_ref text,
    command jsonb,
    cpu_millis integer,
    memory_mb integer,
    pids_limit integer,
    generation bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.nodes n
        WHERE n.id = p_node_id
          AND n.status IN ('active', 'draining')
          AND n.agent_token_sha256 = p_token_sha256
    ) THEN
        RAISE EXCEPTION 'node authentication failed' USING ERRCODE = '42501';
    END IF;

    RETURN QUERY
    SELECT d.instance_id, d.desired_state, d.image_ref, d.command,
           d.cpu_millis, d.memory_mb, d.pids_limit, d.generation
    FROM public.agent_desired_state d
    WHERE d.node_id = p_node_id
    ORDER BY d.instance_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.sentrix_agent_report_instance(
    p_node_id uuid,
    p_token_sha256 bytea,
    p_instance_id uuid,
    p_observed_state text,
    p_container_id text,
    p_generation bigint,
    p_exit_code integer,
    p_health text,
    p_detail text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_org_id uuid;
    v_rows bigint := 0;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.nodes n
        WHERE n.id = p_node_id
          AND n.status IN ('active', 'draining')
          AND n.agent_token_sha256 = p_token_sha256
    ) THEN
        RAISE EXCEPTION 'node authentication failed' USING ERRCODE = '42501';
    END IF;

    SELECT d.org_id INTO v_org_id
    FROM public.agent_desired_state d
    WHERE d.instance_id = p_instance_id
      AND d.node_id = p_node_id;

    IF v_org_id IS NULL THEN
        RAISE EXCEPTION 'instance not assigned to node' USING ERRCODE = '42501';
    END IF;

    PERFORM set_config('app.current_org', v_org_id::text, true);

    INSERT INTO public.instance_status (
        instance_id, org_id, observed_state, container_id, generation,
        exit_code, health, detail, changed_at, updated_at
    ) VALUES (
        p_instance_id, v_org_id, p_observed_state, p_container_id, p_generation,
        p_exit_code, p_health, left(p_detail, 2000), now(), now()
    )
    ON CONFLICT (instance_id) DO UPDATE SET
        observed_state = EXCLUDED.observed_state,
        container_id = EXCLUDED.container_id,
        generation = EXCLUDED.generation,
        exit_code = EXCLUDED.exit_code,
        health = EXCLUDED.health,
        detail = EXCLUDED.detail,
        changed_at = now(),
        updated_at = now()
    WHERE public.instance_status.observed_state IS DISTINCT FROM EXCLUDED.observed_state
       OR public.instance_status.container_id IS DISTINCT FROM EXCLUDED.container_id
       OR public.instance_status.generation IS DISTINCT FROM EXCLUDED.generation
       OR public.instance_status.exit_code IS DISTINCT FROM EXCLUDED.exit_code
       OR public.instance_status.health IS DISTINCT FROM EXCLUDED.health
       OR public.instance_status.detail IS DISTINCT FROM EXCLUDED.detail;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows > 0;
END;
$$;
