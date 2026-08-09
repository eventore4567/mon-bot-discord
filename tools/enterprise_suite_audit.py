"""Audit CI de la suite Enterprise SentriX."""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
os.environ.setdefault("DATABASE_PATH", "/tmp/sentrix-enterprise-audit.db")
os.environ.pop("POSTGRES_URL", None)
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("S3_BUCKET", None)

import config
import main
from web import admin_only_dashboard, dashboard, enterprise_suite as web_enterprise


REQUIRED_TABLES = {
    "enterprise_guild_settings",
    "ban_appeals",
    "ban_appeal_messages",
    "modmail_threads",
    "modmail_messages",
    "modmail_sessions",
    "automation_rules",
    "automation_runs",
    "runtime_metrics_v2",
    "message_activity_hourly",
    "server_stat_snapshots_v2",
    "sentrix_recommendations_v2",
    "dashboard_section_roles",
    "external_backups_v2",
    "canary_checks_v2",
}

REQUIRED_ROUTES = {
    "/enterprise",
    "/appeal/{token}",
    "/api/appeal/{token}",
    "/api/guilds/{guild_id}/enterprise/summary",
    "/api/guilds/{guild_id}/enterprise/settings",
    "/api/guilds/{guild_id}/enterprise/appeals",
    "/api/guilds/{guild_id}/enterprise/appeals/{appeal_id}",
    "/api/guilds/{guild_id}/enterprise/modmail",
    "/api/guilds/{guild_id}/enterprise/modmail/{record_id}",
    "/api/guilds/{guild_id}/enterprise/automations",
    "/api/guilds/{guild_id}/enterprise/monitoring",
    "/api/guilds/{guild_id}/enterprise/canary",
    "/api/guilds/{guild_id}/enterprise/backups",
    "/api/guilds/{guild_id}/enterprise/analytics",
    "/api/guilds/{guild_id}/enterprise/recommendations",
    "/api/guilds/{guild_id}/enterprise/access",
}

REQUIRED_METHODS = {
    "create_appeal_for_ban",
    "appeal_from_token",
    "submit_appeal",
    "review_appeal",
    "select_modmail_guild",
    "modmail_staff_reply",
    "set_modmail_status",
    "save_automation",
    "list_automations",
    "monitoring_summary",
    "snapshot_guild",
    "refresh_recommendations",
    "analytics",
    "create_external_backup",
    "restore_external_backup",
    "run_canary",
    "dashboard_access",
    "set_dashboard_role",
}

EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")


def _route_paths(app) -> set[str]:
    return {getattr(route.resource, "canonical", str(route.resource)) for route in app.router.routes()}


async def _audit_preban_appeal_delivery(bot, service) -> None:
    """Reproduit le bug réel : le lien doit partir avant guild.ban(), pas après."""
    moderation = bot.get_cog("Moderation")
    assert moderation is not None, "Cog Moderation absent"
    assert getattr(type(moderation)._send_sanction_dm, "_sentrix_preban_appeal", False), (
        "le MP de ban n'est pas branché au recours pré-ban"
    )
    assert getattr(type(service).create_appeal_for_ban, "_sentrix_preban_reuse", False), (
        "on_member_ban recréerait encore un second recours"
    )

    class FakeGuild:
        id = 991001
        name = "Serveur CI"

    class FakeAuthor:
        id = 991002
        display_name = "Moderateur CI"

        def __str__(self):
            return self.display_name

    class FakeTarget:
        id = 991003
        display_name = "Membre CI"

        def __init__(self):
            self.messages = []

        def __str__(self):
            return self.display_name

        async def send(self, content, **kwargs):
            self.messages.append(str(content))
            return None

    class FakeContext:
        guild = FakeGuild()
        author = FakeAuthor()

    target = FakeTarget()
    delivered = await moderation._send_sanction_dm(
        FakeContext(), target, "ban", "Test lien de recours"
    )
    assert delivered is True
    assert len(target.messages) >= 2, "le MP de recours pré-ban n'a pas été envoyé"
    appeal_dm = target.messages[-1]
    assert "/appeal/" in appeal_dm, "le MP pré-ban ne contient aucun lien de recours"
    assert config.DASHBOARD_PUBLIC_URL in appeal_dm, "le lien de recours n'utilise pas le dashboard public"

    before = await bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ban_appeals WHERE guild_id=? AND user_id=? AND status='awaiting_user'",
        (FakeGuild.id, target.id),
    )
    assert int(before["n"]) == 1, "un recours unique doit exister avant le ban"

    # Simule l'événement Discord reçu juste après le ban. Il doit réutiliser le token déjà
    # remis au membre et surtout ne pas créer un deuxième recours inaccessible.
    await service.create_appeal_for_ban(FakeGuild(), target)
    after = await bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ban_appeals WHERE guild_id=? AND user_id=? AND status='awaiting_user'",
        (FakeGuild.id, target.id),
    )
    assert int(after["n"]) == 1, "on_member_ban a dupliqué le recours pré-ban"


async def run() -> None:
    db_path = Path(os.environ["DATABASE_PATH"])
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(db_path) + suffix).unlink()
        except FileNotFoundError:
            pass

    bot = main.BotAllInOne()
    await bot.db.connect()
    loaded = 0
    service = None
    try:
        for extension in main.EXTENSIONS:
            await bot.load_extension(extension)
            loaded += 1

        service = bot.get_cog("EnterpriseSuite")
        assert service is not None, "EnterpriseSuite n'a pas été installé"
        assert getattr(bot, "sentrix_enterprise", None) is service
        assert getattr(bot, "sentrix_infra", None) is service.infra

        for method in REQUIRED_METHODS:
            assert hasattr(service, method), f"fonction Enterprise absente: {method}"

        rows = await bot.db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {str(row["name"]) for row in rows}
        missing_tables = REQUIRED_TABLES - tables
        assert not missing_tables, f"tables Enterprise manquantes: {sorted(missing_tables)}"

        # Régression ciblée : le membre doit recevoir son URL de recours AVANT d'être
        # réellement banni, puis on_member_ban doit réutiliser ce même recours.
        await _audit_preban_appeal_delivery(bot, service)

        # La suite ne doit pas regonfler le catalogue de commandes publiques.
        names = {command.name for command in bot.commands}
        assert "enterprise" not in names
        assert "appeal" not in names
        assert "modmail" not in names
        assert "automation" not in names

        infra_health = await service.infra.health()
        assert infra_health["postgres_configured"] is False
        assert infra_health["redis_configured"] is False
        assert infra_health["postgres_online"] is False
        assert infra_health["redis_online"] is False

        # Le canary sans serveur configuré doit rester un contrôle non destructif.
        canary = await service.run_canary()
        assert canary["status"] == "ok"
        assert "extensions" in {item["name"] for item in canary["checks"]}
        assert "shards" in {item["name"] for item in canary["checks"]}

        app = dashboard.build_app(bot)
        paths = _route_paths(app)
        missing_routes = REQUIRED_ROUTES - paths
        assert not missing_routes, f"routes Enterprise manquantes: {sorted(missing_routes)}"
        assert "/enterprise" in admin_only_dashboard._PRIVATE_PAGE_PATHS
        assert "/appeal/{token}" not in admin_only_dashboard._PRIVATE_PAGE_PATHS
        assert 'id="sentrix-enterprise-link"' in dashboard.INDEX_HTML

        assert not EMOJI_RE.search(web_enterprise.ENTERPRISE_HTML), "emoji décoratif dans Enterprise"
        assert not EMOJI_RE.search(web_enterprise.APPEAL_HTML), "emoji décoratif dans la page de recours"
        for marker in (
            "Recours de bannissement",
            "Modmail",
            "Automatisations",
            "Monitoring",
            "Sauvegarde catastrophe",
            "Statistiques et recommandations",
            "Permissions dashboard par section",
        ):
            assert marker in web_enterprise.ENTERPRISE_HTML, f"section Enterprise absente: {marker}"

        railway_source = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
        assert "commands.AutoShardedBot" in railway_source
        assert "commands.Bot = SentriXAutoShardedBot" in railway_source
        assert "SHARD_COUNT" in railway_source

        req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for package in ("asyncpg", "redis", "boto3"):
            assert package in req, f"dépendance Enterprise absente: {package}"

        assert hasattr(config, "POSTGRES_URL")
        assert hasattr(config, "REDIS_URL")
        assert hasattr(config, "SHARD_COUNT")
        assert hasattr(config, "CANARY_MODE")
        assert hasattr(config, "CANARY_GUILD_ID")

        print(f"Enterprise audit: {loaded}/{len(main.EXTENSIONS)} extensions chargées")
        print("OK: recours pré-ban, modmail, sharding, PostgreSQL/Redis optionnels, monitoring, backups, canary, automatisations, analytics, recommandations et permissions dashboard validés")
    finally:
        if service is None:
            service = bot.get_cog("EnterpriseSuite")
        if service is not None:
            for name in ("metrics_loop", "automation_loop", "analytics_loop", "backup_loop"):
                try:
                    getattr(service, name).cancel()
                except Exception:
                    pass
            try:
                await service.infra.close()
            except Exception:
                pass
        operations = bot.get_cog("OperationsCenter")
        if operations is not None:
            try:
                operations.maintenance_loop.cancel()
            except Exception:
                pass
        await bot.db.close()


if __name__ == "__main__":
    asyncio.run(run())
