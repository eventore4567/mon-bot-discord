-- SentriX Cloud Hoster V1: persisted runtime configuration plus controlled
-- operator node registration. Tenant runtime configuration remains under RLS.

CREATE TABLE hosting_runtime_config (
    environment_id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations(id),
    command jsonb NOT NULL DEFAULT '["python","main.py"]'::jsonb,
    cpu_millis integer NOT NULL DEFAULT 500 CHECK (cpu_millis BETWEEN 50 AND 4000),
    memory_mb integer NOT NULL DEFAULT 256 CHECK (memory_mb BETWEEN 64 AND 4096),
    pids_limit integer NOT NULL DEFAULT 128 CHECK (pids_limit BETWEEN 16 AND 1024),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT hosting_runtime_env_fk FOREIGN KEY (environment_id, org_id)
        REFERENCES environments(id, org_id),
    CONSTRAINT hosting_runtime_command_array CHECK (jsonb_typeof(command) = 'array')
);

ALTER TABLE hosting_runtime_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE hosting_runtime_config FORCE ROW LEVEL SECURITY;
CREATE POLICY hosting_runtime_tenant ON hosting_runtime_config
    USING (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());
GRANT SELECT, INSERT, UPDATE ON hosting_runtime_config TO sentrix_app;

-- The public application role still gets no table privileges on `nodes`.
-- Registration is possible only through this narrow SECURITY DEFINER function,
-- and the HTTP route invoking it is separately protected by the operator token.
CREATE OR REPLACE FUNCTION public.sentrix_operator_register_node(
    p_node_id uuid,
    p_cell_id uuid,
    p_name text,
    p_token_sha256 bytea
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF length(p_name) < 1 OR length(p_name) > 100 THEN
        RAISE EXCEPTION 'invalid node name' USING ERRCODE = '22023';
    END IF;
    IF octet_length(p_token_sha256) <> 32 THEN
        RAISE EXCEPTION 'invalid node token digest' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.nodes (id, cell_id, name, agent_token_sha256, status)
    VALUES (p_node_id, p_cell_id, p_name, p_token_sha256, 'active')
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        agent_token_sha256 = EXCLUDED.agent_token_sha256,
        status = 'active',
        updated_at = now();
END;
$$;

REVOKE ALL ON FUNCTION public.sentrix_operator_register_node(uuid, uuid, text, bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sentrix_operator_register_node(uuid, uuid, text, bytea) TO sentrix_app;
