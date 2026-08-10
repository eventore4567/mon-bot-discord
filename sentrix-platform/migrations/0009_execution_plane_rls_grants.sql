-- 0009 : RLS et privileges P1.

ALTER TABLE instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE instances FORCE ROW LEVEL SECURITY;
CREATE POLICY instances_tenant_policy ON instances
    USING (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

ALTER TABLE instance_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE instance_status FORCE ROW LEVEL SECURITY;
CREATE POLICY instance_status_tenant_policy ON instance_status
    USING (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

GRANT SELECT, INSERT, UPDATE ON instances TO sentrix_app;
GRANT SELECT ON instance_status TO sentrix_app;

-- Le role applicatif ne peut jamais lire la table de noeuds ni le miroir agent.
REVOKE ALL ON nodes, agent_desired_state FROM PUBLIC;
REVOKE ALL ON nodes, agent_desired_state FROM sentrix_app;

REVOKE ALL ON FUNCTION public.sentrix_sync_agent_desired() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_agent_pull(uuid, bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentrix_agent_report_instance(
    uuid, bytea, uuid, text, text, bigint, integer, text, text
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.sentrix_agent_pull(uuid, bytea) TO sentrix_app;
GRANT EXECUTE ON FUNCTION public.sentrix_agent_report_instance(
    uuid, bytea, uuid, text, text, bigint, integer, text, text
) TO sentrix_app;
