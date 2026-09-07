-- P7/V1 hoster: authorize a trusted node for one assigned instance before
-- exposing that instance's encrypted secret rows through the normal RLS path.
-- The function never returns plaintext and never bypasses node authentication.

CREATE OR REPLACE FUNCTION public.sentrix_agent_authorize_instance(
    p_node_id uuid,
    p_token_sha256 bytea,
    p_instance_id uuid
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_org_id uuid;
    v_env_id uuid;
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

    -- Local to the caller transaction. This makes the following ordinary
    -- sentrix_app query obey the same FORCE RLS policies as every tenant path.
    PERFORM set_config('app.current_org', v_org_id::text, true);

    SELECT i.env_id INTO v_env_id
    FROM public.instances i
    WHERE i.id = p_instance_id;

    IF v_env_id IS NULL THEN
        RAISE EXCEPTION 'instance not found' USING ERRCODE = '42501';
    END IF;

    RETURN v_env_id;
END;
$$;

REVOKE ALL ON FUNCTION public.sentrix_agent_authorize_instance(uuid, bytea, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sentrix_agent_authorize_instance(uuid, bytea, uuid) TO sentrix_app;
