-- 0007 : privileges du role applicatif.
--
-- audit_log : INSERT + SELECT uniquement. Pas d'UPDATE, pas de DELETE.
-- C'est ce qui rend le journal reellement append-only (cas d'attaque n.9).

GRANT USAGE ON SCHEMA public TO sentrix_app;

-- Le helper RLS est le seul point de lecture du contexte tenant. Retirer le
-- droit implicite PUBLIC evite qu'il devienne une surface inutile pour d'autres
-- roles du cluster ; le role applicatif le recoit explicitement.
REVOKE ALL ON FUNCTION public.sentrix_current_org() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sentrix_current_org() TO sentrix_app;

GRANT SELECT, INSERT, UPDATE ON organizations TO sentrix_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON org_members TO sentrix_app;
GRANT SELECT, INSERT, UPDATE ON users        TO sentrix_app;
GRANT SELECT, INSERT, UPDATE ON projects     TO sentrix_app;
GRANT SELECT, INSERT, UPDATE ON bots         TO sentrix_app;
GRANT SELECT, INSERT, UPDATE ON environments TO sentrix_app;

GRANT SELECT ON cells TO sentrix_app;

-- APPEND-ONLY : volontairement pas d'UPDATE ni de DELETE.
GRANT SELECT, INSERT ON audit_log TO sentrix_app;

-- Aucun droit sur schema_migrations (reserve au migrator).
REVOKE ALL ON schema_migrations FROM sentrix_app;

-- Pas de suppression physique des entites tenant : le statut 'deleted' est
-- utilise a la place, afin de ne jamais casser la chaine d'audit.
REVOKE DELETE ON organizations, projects, bots, environments FROM sentrix_app;
