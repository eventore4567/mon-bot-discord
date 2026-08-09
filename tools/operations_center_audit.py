"""Audit CI ciblé du centre Operations SentriX."""
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
os.environ.setdefault("DATABASE_PATH", "/tmp/sentrix-operations-audit.db")

import main
from web import admin_only_dashboard, dashboard, operations_center as web_operations


REQUIRED_TABLES = {
    "module_role_permissions",
    "staff_notes",
    "moderation_case_events",
    "automod_scope_rules",
    "custom_commands_v2",
    "dashboard_audit_log",
    "ticket_transcripts_v2",
    "runtime_errors",
    "component_checks",
    "raid_events_v2",
    "raid_lockdowns_v2",
}

REQUIRED_ROUTES = {
    "/operations",
    "/api/guilds/{guild_id}/ops/summary",
    "/api/guilds/{guild_id}/ops/access",
    "/api/guilds/{guild_id}/ops/member/{user_id}",
    "/api/guilds/{guild_id}/ops/cases/{case_number}",
    "/api/guilds/{guild_id}/ops/automod-scopes",
    "/api/guilds/{guild_id}/ops/backups",
    "/api/guilds/{guild_id}/ops/custom-commands",
    "/api/guilds/{guild_id}/ops/ticket-forms",
    "/api/guilds/{guild_id}/ops/transcripts",
    "/api/guilds/{guild_id}/ops/diagnostics",
}

EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")


async def run() -> None:
    db_path = os.environ["DATABASE_PATH"]
    try:
        os.remove(db_path)
    except FileNotFoundError:
        pass

    bot = main.BotAllInOne()
    await bot.db.connect()
    loaded = 0
    try:
        for extension in main.EXTENSIONS:
            await bot.load_extension(extension)
            loaded += 1

        service = bot.get_cog("OperationsCenter")
        assert service is not None, "OperationsCenter n'a pas été installé"
        assert getattr(bot, "sentrix_operations", None) is service
        assert getattr(bot, "_sentrix_module_role_check", False), "check permissions modules absent"

        automod = bot.get_cog("Automod")
        assert automod is not None
        assert getattr(automod, "_sentrix_ops_scope", False), "scope AutoMod salon/catégorie non branché"

        rows = await bot.db.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table'",
        )
        tables = {str(row["name"]) for row in rows}
        missing_tables = REQUIRED_TABLES - tables
        assert not missing_tables, f"tables Operations manquantes: {sorted(missing_tables)}"

        # Le centre ne doit pas recréer une forêt de commandes publiques.
        names = {command.name for command in bot.commands}
        assert "operations" not in names and "member-profile" not in names

        app = dashboard.build_app(bot)
        paths = {getattr(route.resource, "canonical", str(route.resource)) for route in app.router.routes()}
        missing_routes = REQUIRED_ROUTES - paths
        assert not missing_routes, f"routes Operations manquantes: {sorted(missing_routes)}"
        assert "/operations" in admin_only_dashboard._PRIVATE_PAGE_PATHS
        assert 'id="sentrix-operations-link"' in dashboard.INDEX_HTML
        assert "sentrixGlobalSearch" in dashboard.INDEX_HTML

        # Le nouvel écran suit la politique visuelle actuelle : pas d'emoji décoratif.
        assert not EMOJI_RE.search(web_operations.OPERATIONS_HTML), "emoji décoratif dans Operations"

        # Vérifie les briques fonctionnelles demandées dans le runtime et le dashboard.
        for method in (
            "module_permission_check", "member_profile", "add_staff_note", "case_details",
            "create_rich_backup", "restore_backup_part", "run_diagnostics",
            "generate_ticket_transcript", "activate_raid_lockdown", "restore_raid_lockdown",
        ):
            assert hasattr(service, method), f"fonction Operations absente: {method}"

        for marker in (
            "Permissions par module", "Profil membre complet", "Dossiers de modération",
            "AutoMod par salon et catégorie", "Sauvegardes partielles",
            "Commandes personnalisées", "Tickets avancés et transcripts HTML",
            "Santé et diagnostic", "Journal du dashboard",
        ):
            assert marker in web_operations.OPERATIONS_HTML, f"section dashboard absente: {marker}"

        print(f"Operations audit: {loaded}/{len(main.EXTENSIONS)} extensions chargées")
        print("OK: permissions modules, profils, dossiers, AutoMod scoped, backups, custom commands, tickets, santé, anti-raid et dashboard branchés")
    finally:
        service = bot.get_cog("OperationsCenter")
        if service is not None:
            try:
                service.maintenance_loop.cancel()
            except Exception:
                pass
        await bot.db.close()


if __name__ == "__main__":
    asyncio.run(run())
