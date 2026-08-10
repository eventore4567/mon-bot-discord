-- Roles = objets de CLUSTER, volontairement hors migrations.
-- A executer une fois par cluster, en tant que superutilisateur.
--
-- Regle de securite P0 : sentrix_app NE DOIT JAMAIS avoir BYPASSRLS.

-- Proprietaire du schema : execute le DDL et les migrations.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentrix_migrator') THEN
        CREATE ROLE sentrix_migrator LOGIN PASSWORD 'migrator_dev_only';
    END IF;
END
$$;

-- Role applicatif : utilise par tous les services. Aucun objet possede, PAS de BYPASSRLS.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentrix_app') THEN
        CREATE ROLE sentrix_app LOGIN PASSWORD 'app_dev_only';
    END IF;
END
$$;

-- Bris de glace. Usage manuel uniquement, audite hors bande.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentrix_admin') THEN
        CREATE ROLE sentrix_admin LOGIN PASSWORD 'admin_dev_only' BYPASSRLS;
    END IF;
END
$$;

-- Invariants explicites (defense en profondeur si un role preexistait).
ALTER ROLE sentrix_app      NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE sentrix_migrator NOBYPASSRLS NOSUPERUSER NOCREATEROLE;
ALTER ROLE sentrix_admin    BYPASSRLS   NOSUPERUSER;

-- sentrix_app ne doit pas pouvoir devenir migrator ni admin :
-- aucun GRANT d'appartenance n'est accorde, donc SET ROLE echouera (42501).
