# Runbook P0 — passer la suite au vert

Objectif : exécuter les 12 attaques cross-tenant contre un PostgreSQL réel.
Durée estimée : 10 minutes si tout va bien.

Je n'ai pas pu exécuter cette suite (pas de PostgreSQL, pas de Docker, pas de réseau dans mon environnement). Ce runbook est fait pour que vous obteniez le verdict, avec les échecs probables déjà identifiés et leur correctif.

---

## Étapes

```bash
cd sentrix-platform

# 1. PostgreSQL (PgBouncer optionnel à ce stade)
docker compose -f ops/docker/docker-compose.yml up -d postgres

# 2. Environnement Python 3.12+
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Rôles (une fois par cluster, en superutilisateur)
psql "postgresql://postgres:postgres@localhost:5432/sentrix" -f ops/bootstrap/roles.sql

# 4. LA suite
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/sentrix"
pytest tests/security -v -m security --tb=short
```

Puis, si elle passe :

```bash
pytest tests/unit tests/integration -v
ruff check . && ruff format --check . && mypy libs services
```

Envoyez-moi la sortie complète, y compris les tracebacks. Je corrige.

---

## Corrections déjà appliquées après relecture

Plusieurs bugs ont été trouvés par relecture avant l’exécution PostgreSQL. Deux corrections supplémentaires ont ensuite été ajoutées pendant la revue croisée : la sémantique réelle des GUC transaction-local réutilisés et le squatting de `discord_application_id`.

| # | Bug | Effet | Correctif |
|---|---|---|---|
| 1 | `httpx.ASGITransport` n'exécute pas le lifespan | `app.state.app_state` jamais posé → `AttributeError` sur **chaque** test d'API | `create_app()` pose l'état immédiatement quand les dépendances sont injectées |
| 2 | `require_org()` lisait `org_members` en `admin_tx` | `org_members` est sous RLS → **42704** sur chaque requête authentifiée, au lieu d'un 404 | Lecture en `tenant_tx(org_id)` |
| 3 | Modèles de sortie en `extra="forbid"` | `model_validate(dict(row))` rejetait les colonnes non exposées (`updated_at`…) → `ValidationError` sur chaque réponse | `_In` (forbid) pour l'entrée, `_Out` (ignore) pour la sortie |
| 4 | Fixture async de portée session sans `loop_scope` | pytest-asyncio ≥ 0.24 → `ScopeMismatch` ou boucle fermée | `loop_scope="session"` + `asyncio_default_fixture_loop_scope` |
| 5 | Deux `SET ROLE` refusés testés dans la même transaction | le premier 42501 met la transaction en échec ; le second retourne 25P02 | une transaction indépendante par tentative d’escalade |
| 6 | Hypothèse « après SET LOCAL, `current_setting()` redevient toujours inconnu » | PostgreSQL peut conserver un placeholder vide sur la même connexion | helper RLS `sentrix_current_org()` : NULL/`''` → 42704 explicite |
| 7 | Unicité globale d’un `discord_application_id` non vérifié | squatting : un tiers peut bloquer le propriétaire légitime en déclarant l’ID le premier | unicité globale **uniquement après** `discord_application_verified_at` |

Le bug n°2 est le plus intéressant : c'est la règle de défaillance fermée qui se retourne contre le code. Exactement ce qu'elle est censée faire — échouer bruyamment plutôt que fuir en silence.

---

## Échecs restants que j'anticipe

Je n'ai pas pu les exercer. Par ordre de probabilité :

**1. Transfert de propriété des tables (`conftest.py`, fixture `prepared_db`)**
Les migrations tournent en superutilisateur, puis les tables passent à `sentrix_migrator` pour refléter la production et prouver que `FORCE ROW LEVEL SECURITY` s'applique bien au propriétaire. Si `ALTER TABLE ... OWNER TO` échoue, c'est que le rôle n'existe pas encore — vérifier que l'étape 3 (`roles.sql`) a bien été jouée **avant** pytest.

**2. Authentification de `sentrix_app`**
Les tests se connectent avec `sentrix_app` / `app_dev_only`. Si `pg_hba.conf` exige `scram-sha-256` et que le mot de passe a été créé sous un autre encodage, la connexion est refusée. Symptôme : `InvalidPasswordError` sur toute la suite. Correctif : rejouer `roles.sql`, ou `ALTER ROLE sentrix_app PASSWORD 'app_dev_only';`.

**3. Exécution du script multi-instructions**
`roles.sql` est passé à `conn.execute()` d'un bloc (blocs `DO $$`, `ALTER ROLE`). asyncpg le gère en protocole simple, mais si ça coince, l'exécuter via `psql` (étape 3) suffit — la fixture le rejoue de façon idempotente.

**4. Générique `asyncpg.Pool[asyncpg.Record]` sous mypy strict**
Peut nécessiter un `# type: ignore` selon la version des stubs. N'affecte pas les tests, seulement l'étape `mypy`.

**5. Nettoyage entre tests**
La fixture `tenants` supprime dans l'ordre des FK (environments → bots → projects → org_members → users → organizations). Si un test laisse une ligne inattendue, la suppression de l'org échoue en 23503. Symptôme : erreurs en cascade au *teardown*, pas dans les tests eux-mêmes.

---

## Ce qui prouve l'absence de fuite entre tenants

Le test `test_10_set_local_does_not_leak_across_transactions` est celui qui compte pour la règle PgBouncer. Sa construction :

1. Pool forcé à `max_size=1` → une seule connexion physique, garantissant sa réutilisation.
2. `pg_backend_pid()` relevé, puis **réasserté** dans chaque transaction — sans ça, le test pourrait passer simplement parce qu'une autre connexion a été prise.
3. Transaction 1 : contexte A posé, `current_setting` renvoie bien A.
4. Transaction 2, **même connexion, sans contexte** : le GUC brut peut être `NULL` ou `''`, mais il ne doit jamais contenir A. Une requête RLS doit lever **42704** via `public.sentrix_current_org()`.
5. Transaction 3 : contexte B, et vérification qu'aucun projet de A n'est visible.

Complément statique : `tests/unit/test_no_persistent_set.py` analyse l'AST du dépôt et échoue si `app.current_org` est référencé hors de `libs/db`, ou si `set_config` est appelé sans `is_local=true`. Ces garde-fous passent (vérifié).

---

## Ce que j'ai réellement exécuté

Environnement sans PostgreSQL : seule la partie hors base a pu tourner.

| Vérification | Résultat |
|---|---|
| Syntaxe des fichiers Python | vérifiée par `compileall` |
| UUIDv7 (version, variant, horodatage, ordre, 10 000 uniques) | 6/6 |
| Gardes statiques SET/RLS/GRANT + unicité vérifiée | incluses dans `tests/unit` |
| Migrator (ordre, checksums, dérive, nom invalide) | 4/4 |
| SessionCodec (aller-retour, falsification, clé croisée, expiration) | 5/5 |

**Les 12 attaques cross-tenant restent le gate final.** Elles doivent tourner contre PostgreSQL réel dans GitHub Actions avant de déclarer P0 terminé.
