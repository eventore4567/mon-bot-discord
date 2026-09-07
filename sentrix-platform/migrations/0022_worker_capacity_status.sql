-- Aggregate worker capacity for the authenticated Hosting dashboard.
-- The app role still cannot SELECT from nodes and never receives node IDs.

CREATE OR REPLACE FUNCTION public.sentrix_configured_worker_count()
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT count(*)::bigint
    FROM public.nodes
    WHERE status IN ('active', 'draining');
$$;

REVOKE ALL ON FUNCTION public.sentrix_configured_worker_count() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sentrix_configured_worker_count() TO sentrix_app;
