-- Keep long-running builds exclusively owned by the worker that claimed them.

CREATE OR REPLACE FUNCTION public.sentrix_builder_renew(
    p_worker_id uuid,
    p_token_sha256 bytea,
    p_build_id uuid,
    p_lease_attempt integer,
    p_lease_seconds integer DEFAULT 120
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_rows bigint := 0;
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

    UPDATE public.builds
       SET lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           updated_at = now()
     WHERE id = p_build_id
       AND lease_worker_id = p_worker_id
       AND attempt_no = p_lease_attempt
       AND status IN ('building', 'scanning');

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    IF v_rows = 0 THEN
        RAISE EXCEPTION 'stale or unowned build lease' USING ERRCODE = '42501';
    END IF;

    UPDATE public.control_workers
       SET last_seen_at = now(), updated_at = now()
     WHERE id = p_worker_id;

    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.sentrix_builder_renew(
    uuid, bytea, uuid, integer, integer
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.sentrix_builder_renew(
    uuid, bytea, uuid, integer, integer
) TO sentrix_app;
