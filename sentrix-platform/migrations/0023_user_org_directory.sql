-- 0023 : annuaire global minimal pour l'onboarding authentifie.
--
-- organizations/org_members sont sous FORCE RLS et exigent app.current_org.
-- La page d'accueil, elle, doit pouvoir lister les organisations d'un utilisateur
-- AVANT d'avoir choisi une organisation courante. On garde donc un miroir global
-- minimal, non-tenant, inaccessible directement a sentrix_app. Seule une fonction
-- SECURITY DEFINER parametree par l'UUID de session peut le lire.

CREATE TABLE user_org_directory (
    user_id     uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id      uuid        NOT NULL,
    name        text        NOT NULL,
    slug        text        NOT NULL,
    role        text        NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    status      text        NOT NULL CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, org_id)
);

CREATE INDEX user_org_directory_org_idx ON user_org_directory (org_id);

REVOKE ALL ON user_org_directory FROM PUBLIC;
REVOKE ALL ON user_org_directory FROM sentrix_app;

CREATE OR REPLACE FUNCTION public.sentrix_sync_user_org_directory()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_name text;
    v_slug text;
    v_status text;
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

    SELECT name, slug, status
      INTO v_name, v_slug, v_status
      FROM public.organizations
     WHERE id = NEW.org_id;

    IF v_name IS NULL THEN
        RAISE EXCEPTION 'organization directory sync failed' USING ERRCODE = '23503';
    END IF;

    INSERT INTO public.user_org_directory (
        user_id, org_id, name, slug, role, status, created_at
    ) VALUES (
        NEW.user_id, NEW.org_id, v_name, v_slug, NEW.role, v_status, NEW.created_at
    )
    ON CONFLICT (user_id, org_id) DO UPDATE SET
        name = EXCLUDED.name,
        slug = EXCLUDED.slug,
        role = EXCLUDED.role,
        status = EXCLUDED.status;

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
        DELETE FROM public.user_org_directory WHERE org_id = OLD.id;
        RETURN OLD;
    END IF;

    UPDATE public.user_org_directory
       SET name = NEW.name,
           slug = NEW.slug,
           status = NEW.status
     WHERE org_id = NEW.id;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.sentrix_sync_org_directory_metadata() FROM PUBLIC;

CREATE TRIGGER organizations_sync_user_org_directory
AFTER UPDATE OF name, slug, status OR DELETE ON organizations
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
    SELECT d.org_id, d.name, d.slug, d.role
      FROM public.user_org_directory d
     WHERE d.user_id = p_user_id
       AND d.status = 'active'
     ORDER BY d.created_at ASC, d.org_id ASC
$$;

REVOKE ALL ON FUNCTION public.sentrix_list_user_organizations(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sentrix_list_user_organizations(uuid) TO sentrix_app;
