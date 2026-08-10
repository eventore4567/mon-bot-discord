-- 0006 : Row Level Security.
--
-- Trois details portent toute la securite du dispositif :
--
-- 1. FORCE ROW LEVEL SECURITY
--    Sans FORCE, le PROPRIETAIRE de la table (sentrix_migrator) contourne RLS.
--    C'est l'oubli classique.
--
-- 2. public.sentrix_current_org() centralise la lecture du GUC tenant.
--    PostgreSQL conserve un placeholder de GUC personnalise avec la valeur vide
--    apres un SET LOCAL termine sur certaines versions. Se fier uniquement a
--    current_setting(... sans missing_ok) rend donc le SQLSTATE dependant de
--    l'historique de la connexion. Le helper traite NULL ET '' comme contexte
--    absent et leve explicitement 42704 : defaillance fermee deterministe.
--
-- 3. WITH CHECK autant que USING
--    USING filtre la LECTURE, WITH CHECK empeche l'ECRITURE d'une ligne
--    appartenant a une autre org. Sans WITH CHECK, un tenant peut inserer chez
--    son voisin sans jamais pouvoir le relire.

-- Lecture fail-closed du tenant courant. SECURITY INVOKER par defaut.
-- missing_ok=true n'est utilise qu'ici pour pouvoir distinguer proprement :
--   * GUC jamais cree -> NULL
--   * GUC deja utilise avec SET LOCAL puis restaure -> chaine vide
-- Dans les deux cas, on leve le meme SQLSTATE 42704.
CREATE OR REPLACE FUNCTION public.sentrix_current_org()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    raw_org text;
BEGIN
    raw_org := current_setting('app.current_org', true);
    IF raw_org IS NULL OR raw_org = '' THEN
        RAISE EXCEPTION 'app.current_org non positionne'
            USING ERRCODE = '42704';
    END IF;
    RETURN raw_org::uuid;
END
$$;

-- organizations : un tenant ne voit que la sienne (id = org courante).
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON organizations
    USING      (id = public.sentrix_current_org())
    WITH CHECK (id = public.sentrix_current_org());

ALTER TABLE org_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_members FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON org_members
    USING      (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON projects
    USING      (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

ALTER TABLE bots ENABLE ROW LEVEL SECURITY;
ALTER TABLE bots FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON bots
    USING      (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

ALTER TABLE environments ENABLE ROW LEVEL SECURITY;
ALTER TABLE environments FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON environments
    USING      (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON audit_log
    USING      (org_id = public.sentrix_current_org())
    WITH CHECK (org_id = public.sentrix_current_org());

-- users et cells sont volontairement HORS RLS :
--   users : entite globale (un compte Discord appartient a N orgs)
--   cells : referentiel d'infrastructure, non tenant
-- L'acces y est restreint par les GRANT de la migration 0007.
