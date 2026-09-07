-- 0023 : annuaire global minimal pour l'onboarding authentifie.
--
-- organizations/org_members sont sous FORCE RLS et exigent app.current_org.
-- La page d'accueil doit pourtant pouvoir lister les organisations d'un
-- utilisateur AVANT d'avoir choisi une organisation courante.
--
-- On maintient donc deux miroirs globaux minimaux, inaccessibles directement a
-- sentrix_app :
--   * org_directory : metadonnees publiques necessaires au selecteur d'org
--   * user_org_directory : appartenance user -> org + role
--
-- Les triggers n'effectuent AUCUNE lecture des tables RLS : ils recopient
-- uniquement NEW/OLD, ce qui preserve les fixtures superuser et la defaillance
-- fermee des politiques tenant.

CREATE TABLE org_directory (
    org_id      uuid        PRIMARY KEY,
    name        text        NOT NULL,
    slug        text        NOT NULL,
    status      text        NOT NULL CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at  timestamptz NOT NULL
);

CREATE TABLE user_org_directory (
    user_id     uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id      uuid        NOT NULL,
    role        text        NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, org_id)
);

CREATE INDEX user_org_directory_org_idx ON user_org_directory (org_id);

REVOKE ALL ON org_directory FROM PUBLIC;
REVOKE ALL ON org_directory FROM sentrix_app;
REVOKE ALL ON user_org_directory FROM PUBLIC;
REVOKE ALL ON user_org_directory FROM sentrix_app;

CREATE OR REPLACE FUNCTION public.sentrix_sync_user_org_directory()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.user_org_directory
         WHERE user_id = OLD.user_id
           AND org_id = OLD.org_id;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND (OLD.user_id, OLD.org_id) IS DISTINCT FROM (NEW.user_id, NEW.org_id) THEN
        DELETE FROM public.user_org_directory
         WHERE user_id = OLD.user_id
           AND org_id = OLD.org_id;
    END IF;

    INSERT INTO public.user_org_directory (user_id, org_id, role, created_at)
    VALUES (NEW.user_id, NEW.org_id, NEW.role, NEW.created_at)
    ON CONFLICT (user_id, org_id) DO UPDATE SET
        role = EXCLUDED.role;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.sentrix_sync_user_org_directory() FROM PUBLIC;

CREATE TRIGGER org_members_sync_user_org_directory
AFTER INSERT OR UPDATE OR DELETE ON org_members
FOR EACH ROW EXECUTE FUNCTION public.sentrix_sync_user_org_directory();

CREATE OR REPLACE FUNCTION public.sentrix_sync_org_directory_metadata()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.org_directory WHERE org_id = OLD.id;
        DELETE FROM public.user_org_directory WHERE org_id = OLD.id;
        RETURN OLD;
    END IF;

    INSERT INTO public.org_directory (org_id, name, slug, status, created_at)
    VALUES (NEW.id, NEW.name, NEW.slug, NEW.status, NEW.created_at)
    ON CONFLICT (org_id) DO UPDATE SET
        name = EXCLUDED.name,
        slug = EXCLUDED.slug,
        status = EXCLUDED.status;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.sentrix_sync_org_directory_metadata() FROM PUBLIC;

CREATE TRIGGER organizations_sync_user_org_directory
AFTER INSERT OR UPDATE OF name, slug, status OR DELETE ON organizations
FOR EACH ROW EXECUTE FUNCTION public.sentrix_sync_org_directory_metadata();

CREATE OR REPLACE FUNCTION public.sentrix_list_user_organizations(p_user_id uuid)
RETURNS TABLE (
    id uuid,
    name text,
    slug text,
    role text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT o.org_id, o.name, o.slug, m.role
      FROM public.user_org_directory m
      JOIN public.org_directory o ON o.org_id = m.org_id
     WHERE m.user_id = p_user_id
       AND o.status = 'active'
     ORDER BY o.created_at ASC, o.org_id ASC
$$;

REVOKE ALL ON FUNCTION public.sentrix_list_user_organizations(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sentrix_list_user_organizations(uuid) TO sentrix_app;
