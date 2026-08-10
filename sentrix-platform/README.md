# sentrix-platform — V1 Platform (P0 + P1)

Plateforme d'hébergement spécialisée pour bots Discord.
**P0 est verrouille et P1 ajoute l'Execution Plane.** P1 apporte le node-agent pull-only, gVisor, cgroups, cache local, et isolation reseau. Voir `docs/RUNBOOK-P1.md`.

## Démarrage

```bash
# 1. PostgreSQL + PgBouncer (mode transaction)
docker compose -f ops/docker/docker-compose.yml up -d

# 2. Dépendances
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Rôles (une fois par cluster, en superutilisateur)
psql "postgresql://postgres:postgres@localhost:5432/sentrix" -f ops/bootstrap/roles.sql

# 4. Tests
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sentrix"
pytest tests/security -v -m security   # suite d'attaques (bloquante)
pytest tests/unit tests/integration -v
ruff check . && mypy libs services
```

Sans `TEST_DATABASE_URL`, les tests démarrent un PostgreSQL jetable via testcontainers (Docker requis).

## Les trois règles à ne jamais casser

**1. Contexte tenant uniquement via `libs/db`**
`set_config('app.current_org', $1, true)` dans une transaction explicite. Jamais de `SET` persistant : avec PgBouncer en mode transaction, il fuit vers le tenant suivant. Vérifié mécaniquement par `tests/unit/test_no_persistent_set.py`.

**2. Lecture tenant fail-closed via `public.sentrix_current_org()`**
PostgreSQL peut conserver un GUC custom vide après un `SET LOCAL` terminé. Le helper RLS traite donc **NULL et chaîne vide** comme un contexte absent et lève explicitement **42704**. Une connexion réutilisée ne doit jamais transformer un oubli de contexte en résultat silencieux.

**3. Toute table enfant utilise une FK composite `(parent_id, org_id)`**
C'est ce qui rend la référence cross-org structurellement impossible, plutôt que dépendante d'une vérification applicative qu'un refactor peut supprimer.

## Structure

| Chemin | Rôle |
|---|---|
| `libs/db/` | Pool, contexte tenant, runner de migrations |
| `libs/ids/` | UUIDv7 (RFC 9562) |
| `libs/models/` | Modèles Pydantic v2 |
| `libs/audit/` | Écriture du journal d'audit |
| `services/api/` | REST `/v1`, OAuth Discord, CRUD tenant |
| `migrations/` | SQL numéroté, forward-only, checksums |
| `tests/security/` | **Les 12 attaques cross-tenant** |
| `docs/adr/` | Décisions à sens unique |

Les répertoires des phases suivantes (`agents/`, `services/orchestrator/`…) sont créés vides volontairement, pour que le découpage reste visible.

## Critère de sortie P0

Les 12 attaques passent, dont les cas 4, 5, 7 et 9 rejetés par PostgreSQL avec le SQLSTATE vérifié dans l'assertion.

## Invariant Discord application ID

Un `discord_application_id` **non vérifié ne réserve jamais l'ID globalement**. L'unicité cross-tenant ne s'active qu'au passage `discord_application_verified_at IS NOT NULL`. Cela évite qu'un tenant connaissant un snowflake public puisse bloquer le propriétaire légitime avant la preuve de propriété de P3.
