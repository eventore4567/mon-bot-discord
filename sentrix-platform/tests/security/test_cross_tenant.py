"""Suite d'attaques cross-tenant - critere de sortie unique de P0.

Les cas 4, 5, 7 et 9 DOIVENT etre rejetes par PostgreSQL lui-meme. Les
assertions verifient le SQLSTATE exact, pas seulement "une erreur s'est
produite" : un test qui passerait grace a une verification applicative ne vaut
rien, c'est precisement ce qu'un futur refactor supprimera sans s'en apercevoir.

SQLSTATE attendus :
    23503  foreign_key_violation    (FK composite)
    23505  unique_violation
    42501  insufficient_privilege   (RLS WITH CHECK, GRANT manquant)
    42704  undefined_object         (app.current_org non pose)
"""

from __future__ import annotations

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from libs.db import Database
from libs.ids import uuid7
from services.api.auth import SessionCodec
from services.api.main import create_app
from tests.conftest import Tenant

pytestmark = [pytest.mark.security, pytest.mark.asyncio]

SESSION_SECRET = b"x" * 48


def _sqlstate(exc: BaseException) -> str | None:
    return getattr(exc, "sqlstate", None)


@pytest.fixture
def client_factory(app_db: Database):  # type: ignore[no-untyped-def]
    codec = SessionCodec(SESSION_SECRET)
    app = create_app(db=app_db, sessions=codec)

    def make(user_id):  # type: ignore[no-untyped-def]
        token = codec.issue(user_id)
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        )

    return make


# ============================================================ 1-2 : niveau API


async def test_01_read_other_org_project_returns_404(
    tenants: tuple[Tenant, Tenant],
    client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A lit le projet de B -> 404 (pas 403 : ne pas reveler l'existence)."""
    a, b = tenants
    async with client_factory(a.user_id) as client:
        # Via l'org de A (RLS masque le projet de B).
        response = await client.get(f"/v1/orgs/{a.org_id}/projects/{b.project_id}")
        assert response.status_code == 404

        # Via l'org de B (A n'est pas membre) -> 404 aussi, jamais 403.
        response = await client.get(f"/v1/orgs/{b.org_id}/projects/{b.project_id}")
        assert response.status_code == 404


async def test_02_create_bot_with_foreign_project_rejected(
    tenants: tuple[Tenant, Tenant],
    client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A cree un bot pointant vers le projet de B -> rejet (FK composite -> 404)."""
    a, b = tenants
    async with client_factory(a.user_id) as client:
        response = await client.post(
            f"/v1/orgs/{a.org_id}/bots",
            json={"project_id": str(b.project_id), "name": "vol", "library": "discordpy"},
        )
        assert response.status_code == 404


# ======================================================= 3-7 : niveau PostgreSQL


async def test_03_select_scoped_to_current_org(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """Avec current_org=A, aucune ligne de B n'est visible."""
    a, b = tenants
    async with app_db.tenant_tx(a.org_id) as conn:
        rows = await conn.fetch("SELECT id, org_id FROM projects")
        ids = {r["id"] for r in rows}
        assert a.project_id in ids
        assert b.project_id not in ids
        assert all(r["org_id"] == a.org_id for r in rows)


async def test_04_composite_fk_blocks_cross_org_reference(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """CAS BASE : INSERT bots(org_id=A, project_id=<projet de B>) -> 23503.

    C'est la preuve que la protection est STRUCTURELLE : meme avec le contexte
    tenant correct et un INSERT direct, PostgreSQL refuse le lien cross-org.
    """
    a, b = tenants
    async with app_db.tenant_tx(a.org_id) as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError) as excinfo:
            await conn.execute(
                "INSERT INTO bots (id, org_id, project_id, name) VALUES ($1, $2, $3, $4)",
                uuid7(),
                a.org_id,
                b.project_id,
                "bot-vole",
            )
    assert _sqlstate(excinfo.value) == "23503"
    assert "bots_project_fk" in str(excinfo.value)


async def test_05_rls_with_check_blocks_insert_for_other_org(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """CAS BASE : INSERT projects(org_id=B) avec current_org=A -> 42501.

    Sans WITH CHECK, cette insertion reussirait et A ecrirait chez B sans
    jamais pouvoir le relire.
    """
    a, b = tenants
    async with app_db.tenant_tx(a.org_id) as conn:
        with pytest.raises(asyncpg.PostgresError) as excinfo:
            await conn.execute(
                "INSERT INTO projects (id, org_id, name) VALUES ($1, $2, $3)",
                uuid7(),
                b.org_id,
                "projet-injecte",
            )
    assert _sqlstate(excinfo.value) == "42501"


async def test_06_update_cannot_move_row_to_other_org(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """UPDATE projects SET org_id=B sur une ligne de A -> 42501."""
    a, b = tenants
    async with app_db.tenant_tx(a.org_id) as conn:
        with pytest.raises(asyncpg.PostgresError) as excinfo:
            await conn.execute(
                "UPDATE projects SET org_id = $1 WHERE id = $2", b.org_id, a.project_id
            )
    assert _sqlstate(excinfo.value) == "42501"


async def test_07_missing_tenant_context_raises_not_silent_empty(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """CAS BASE : requete SANS app.current_org -> 42704, jamais un jeu vide.

    Defaillance FERMEE. Un bug qui oublie de poser le contexte tenant doit
    produire une erreur bruyante, pas une fuite silencieuse ni un resultat vide
    trompeur.
    """
    async with app_db.admin_tx() as conn:
        with pytest.raises(asyncpg.PostgresError) as excinfo:
            await conn.fetch("SELECT id FROM projects")
    assert _sqlstate(excinfo.value) == "42704"
    assert "app.current_org" in str(excinfo.value)


# ================================================= 8-9 : privileges du role app


async def test_08_app_role_cannot_escalate(app_db: Database) -> None:
    """sentrix_app ne peut pas SET ROLE, et n'a pas BYPASSRLS.

    Chaque tentative SET ROLE vit dans sa propre transaction : une erreur SQL
    place la transaction courante en etat aborted. Tester les deux cibles dans
    la meme transaction donnerait 25P02 au second essai au lieu de prouver 42501.
    """
    async with app_db.admin_tx() as conn:
        assert await conn.fetchval("SELECT current_user") == "sentrix_app"

        bypass = await conn.fetchval(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        assert bypass is False, "sentrix_app ne doit JAMAIS avoir BYPASSRLS"

        superuser = await conn.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        assert superuser is False

    for target in ("sentrix_admin", "sentrix_migrator"):
        with pytest.raises(asyncpg.PostgresError) as excinfo:
            async with app_db.admin_tx() as conn:
                await conn.execute(f"SET ROLE {target}")
        assert _sqlstate(excinfo.value) == "42501"


async def test_09_audit_log_is_append_only(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """CAS BASE : UPDATE et DELETE sur audit_log -> 42501 (GRANT absent)."""
    a, _ = tenants
    async with app_db.tenant_tx(a.org_id) as conn:
        entry_id = uuid7()
        await conn.execute(
            """
            INSERT INTO audit_log (id, org_id, actor_user_id, action, target_type)
            VALUES ($1, $2, $3, 'test.write', 'test')
            """,
            entry_id,
            a.org_id,
            a.user_id,
        )

    async with app_db.tenant_tx(a.org_id) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError) as excinfo:
            await conn.execute("UPDATE audit_log SET action = 'falsifie' WHERE id = $1", entry_id)
    assert _sqlstate(excinfo.value) == "42501"

    async with app_db.tenant_tx(a.org_id) as conn:
        with pytest.raises(asyncpg.InsufficientPrivilegeError) as excinfo:
            await conn.execute("DELETE FROM audit_log WHERE id = $1", entry_id)
    assert _sqlstate(excinfo.value) == "42501"


# ============================================ 10 : fuite de contexte via pooling


async def test_10_set_local_does_not_leak_across_transactions(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """Le contexte tenant ne survit pas a la transaction, meme connexion reutilisee.

    C'est LE test du piege PgBouncer en mode transaction : avec un SET
    persistant, la seconde transaction verrait encore l'org de la premiere.

    Pool volontairement limite a une seule connexion physique, pour garantir que
    la meme connexion est bien reutilisee.
    """
    a, b = tenants
    single = Database(app_db._dsn, min_size=1, max_size=1)  # noqa: SLF001
    await single.connect()
    try:
        async with single.pool.acquire() as conn:
            backend_pid = await conn.fetchval("SELECT pg_backend_pid()")

        # Transaction 1 : contexte A.
        async with single.tenant_tx(a.org_id) as conn:
            assert await conn.fetchval("SELECT pg_backend_pid()") == backend_pid
            assert await conn.fetchval("SELECT current_setting('app.current_org')") == str(a.org_id)

        # Transaction 2 sur la MEME connexion, sans contexte. PostgreSQL peut
        # conserver le placeholder d'un GUC custom avec la valeur vide apres un
        # SET LOCAL termine. Ce n'est PAS une fuite de tenant : la valeur de A
        # doit avoir disparu. Le helper RLS transforme NULL/'' en 42704 de facon
        # deterministe, donc une vraie requete tenant echoue bruyamment.
        async with single.pool.acquire() as conn:
            assert await conn.fetchval("SELECT pg_backend_pid()") == backend_pid
            raw = await conn.fetchval("SELECT current_setting('app.current_org', true)")
            assert raw in (None, ""), f"FUITE DE CONTEXTE : valeur residuelle {raw!r}"

            with pytest.raises(asyncpg.PostgresError) as excinfo:
                await conn.fetch("SELECT id FROM projects")
            assert _sqlstate(excinfo.value) == "42704"

        # Transaction 3 : contexte B, aucune contamination par A.
        async with single.tenant_tx(b.org_id) as conn:
            assert await conn.fetchval("SELECT current_setting('app.current_org')") == str(b.org_id)
            rows = await conn.fetch("SELECT id FROM projects")
            ids = {r["id"] for r in rows}
            assert b.project_id in ids
            assert a.project_id not in ids
    finally:
        await single.close()


# ==================================================== 11-12 : session et unicite


async def test_11_session_replay_on_other_org_rejected(
    tenants: tuple[Tenant, Tenant],
    client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Le jeton de A, rejoue sur une ressource de B, est rejete (404)."""
    a, b = tenants
    async with client_factory(a.user_id) as client:
        for path in (
            f"/v1/orgs/{b.org_id}/projects",
            f"/v1/orgs/{b.org_id}/projects/{b.project_id}",
            f"/v1/orgs/{b.org_id}/bots/{b.bot_id}",
        ):
            response = await client.get(path)
            assert response.status_code == 404, path

        response = await client.post(f"/v1/orgs/{b.org_id}/projects", json={"name": "intrusion"})
        assert response.status_code == 404


async def test_12_unverified_discord_app_cannot_squat_verified_owner(
    tenants: tuple[Tenant, Tenant], app_db: Database
) -> None:
    """Un claim NON verifie ne peut pas bloquer le proprietaire legitime.

    Deux orgs peuvent declarer le meme application_id tant que la propriete n'a
    pas ete verifiee. La premiere verification atomique reserve l'ID ; toute
    seconde verification du meme ID echoue en 23505. Cela evite le squatting
    "premier arrive, premier servi" tout en preparant la preuve Discord de P3.
    """
    a, b = tenants
    app_id = "123456789012345678"
    cell = "01920000-0000-7000-8000-000000000001"
    env_a, env_b = uuid7(), uuid7()

    # A declare l'ID sans preuve : il ne doit PAS le reserver globalement.
    async with app_db.tenant_tx(a.org_id) as conn:
        await conn.execute(
            """
            INSERT INTO environments (id, org_id, bot_id, kind, discord_application_id, cell_id)
            VALUES ($1, $2, $3, 'prod', $4, $5)
            """,
            env_a,
            a.org_id,
            a.bot_id,
            app_id,
            cell,
        )

    # B peut declarer le meme ID tant qu'aucune preuve n'existe : pas de DoS
    # par simple connaissance d'un snowflake public.
    async with app_db.tenant_tx(b.org_id) as conn:
        await conn.execute(
            """
            INSERT INTO environments (id, org_id, bot_id, kind, discord_application_id, cell_id)
            VALUES ($1, $2, $3, 'prod', $4, $5)
            """,
            env_b,
            b.org_id,
            b.bot_id,
            app_id,
            cell,
        )

    # A prouve sa propriete (le service Discord verifiera cette transition en P3).
    async with app_db.tenant_tx(a.org_id) as conn:
        await conn.execute(
            "UPDATE environments SET discord_application_verified_at = now() WHERE id = $1",
            env_a,
        )

    # B ne peut plus devenir proprietaire verifie du meme application_id.
    with pytest.raises(asyncpg.UniqueViolationError) as excinfo:
        async with app_db.tenant_tx(b.org_id) as conn:
            await conn.execute(
                "UPDATE environments SET discord_application_verified_at = now() WHERE id = $1",
                env_b,
            )
    assert _sqlstate(excinfo.value) == "23505"
    assert "environments_discord_app_verified_uniq" in str(excinfo.value)
