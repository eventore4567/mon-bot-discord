#!/usr/bin/env python3
"""Audit de la matrice de permissions SentriX.

Ce gate ne tente aucune action Discord. Il charge le registre réel du bot et vérifie que
les commandes sensibles ne deviennent jamais publiques par erreur, que les verrous + et /
sont actifs et que les contrôles métier essentiels restent présents.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODERATION_SENSITIVE = {
    "ban", "unban", "kick", "mute", "unmute", "warn", "warnings", "clearwarnings",
    "clear", "lock", "unlock", "hide", "show", "quarantine", "unquarantine",
    "nickname", "resetnick", "move", "disconnect", "giverole", "removerole",
    "tempban", "unwarn", "case", "modhistory",
}
SECURITY_SENSITIVE = {
    "antiraid", "antinuke", "blacklist-add", "blacklist-users", "panic", "syncbl",
    "permission-audit", "server-backup", "server-restore", "role-snapshot", "role-restore",
    "lockdown-server", "unlock-server",
}
HIGH_RISK_LOCAL_CHECK = {
    "ban", "unban", "kick", "mute", "unmute", "warn", "clear", "lock", "unlock",
    "nickname", "resetnick", "giverole", "removerole",
}
OWNER_EXPECTED = {
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
    "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
}


def _source_checks(errors: list[str]) -> None:
    moderation = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")
    permission_guard = (ROOT / "cogs" / "permission_guard.py").read_text(encoding="utf-8")
    integrity = (ROOT / "cogs" / "integrity_hardening.py").read_text(encoding="utf-8")
    tickets = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    for marker in (
        "async def check_targetable",
        "checks.check_hierarchy",
        "checks.check_bot_hierarchy",
    ):
        if marker not in moderation:
            errors.append(f"contrôle hiérarchie modération absent: {marker}")

    for marker in (
        "fail-closed",
        "evaluate_command_access",
        "evaluate_interaction_access",
        "_sentrix_permission_guard_installed",
    ):
        if marker not in permission_guard:
            errors.append(f"garde permissions centrale incomplète: {marker}")

    for marker in (
        "_ticket_staff_allowed",
        "Cette action est réservée au staff du ticket.",
        "_sentrix_integrity_staff_target",
    ):
        if marker not in integrity:
            errors.append(f"protection ticket staff absente: {marker}")

    if "handle_control_button" not in tickets:
        errors.append("routeur de contrôles tickets introuvable")


async def _runtime_checks(errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="sentrix-permission-gate-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "permissions.db")

        import main
        from cogs import command_catalog_cleanup, permission_guard, slash_command_budget

        bot = main.BotAllInOne()
        await bot.db.connect()

        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
            except Exception as exc:
                errors.append(f"chargement {extension}: {type(exc).__name__}: {exc}")

        try:
            bot._prune_redundant_commands()
            command_catalog_cleanup.apply_surface(bot)
            slash_command_budget.finalize(bot)
            permission_guard.install(bot)
        except Exception as exc:
            errors.append(f"finalisation permissions: {type(exc).__name__}: {exc}")

        public = set(main.PUBLIC_COMMANDS)
        owner = set(main.OWNER_ONLY_COMMANDS)
        discord_permissions = set(main.DISCORD_PERMISSION_COMMANDS)
        categories = set().union(*(set(values) for values in main.CATEGORY_COMMANDS.values()))
        known_protected = owner | discord_permissions | categories | set(main.CUSTOM_PERMISSION_COMMANDS)

        overlap = sorted(public & owner)
        if overlap:
            errors.append("commandes à la fois publiques et owner-only: " + ", ".join(overlap))

        for name in sorted(MODERATION_SENSITIVE | SECURITY_SENSITIVE | OWNER_EXPECTED):
            if name in public:
                errors.append(f"commande sensible classée publique: {name}")

        for name in sorted(OWNER_EXPECTED):
            if name not in owner:
                errors.append(f"commande propriétaire non classée owner-only: {name}")

        # Une commande sensible absente de la matrice explicite reste certes fail-closed,
        # mais le gate l'interdit : la politique doit rester lisible et intentionnelle.
        for name in sorted(MODERATION_SENSITIVE | SECURITY_SENSITIVE):
            command = bot.get_command(name)
            if command is None:
                continue  # peut être volontairement fusionnée/retirée de la surface directe
            if name not in known_protected:
                errors.append(f"commande sensible dépend uniquement du fail-closed: {name}")

        for name in sorted(HIGH_RISK_LOCAL_CHECK):
            command = bot.get_command(name)
            if command is None:
                errors.append(f"commande critique absente: {name}")
                continue
            checks = getattr(command, "checks", ())
            if not checks:
                errors.append(f"commande critique sans check métier local: {name}")
            callback = getattr(command, "callback", None)
            if callback is None or not inspect.iscoroutinefunction(callback):
                errors.append(f"callback critique invalide: {name}")

        if not getattr(bot, "_sentrix_permission_guard_installed", False):
            errors.append("garde permissions centrale non installée")
        if not getattr(bot.tree.interaction_check, "_sentrix_permission_guard", False):
            errors.append("garde permissions slash non installée sur CommandTree")
        if not getattr(bot.global_permission_check, "_sentrix_permission_guard", False):
            errors.append("garde permissions préfixe non installée")

        # Aucune commande admin propriétaire ne doit consommer la surface slash globale.
        slash_roots = {str(item.name).casefold() for item in bot.tree.get_commands()}
        forbidden_slash = sorted(slash_roots & set(command_catalog_cleanup.ADMIN_DIRECT_COMMANDS))
        if forbidden_slash:
            errors.append("commandes admin/owner exposées en slash: " + ", ".join(forbidden_slash))

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        close = getattr(bot.db, "close", None)
        if close:
            result = close()
            if inspect.isawaitable(result):
                await result


def main_sync() -> int:
    errors: list[str] = []
    try:
        _source_checks(errors)
    except Exception as exc:
        errors.append(f"audit source impossible: {type(exc).__name__}: {exc}")
    asyncio.run(_runtime_checks(errors))

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC PERMISSIONS: {len(errors)} problème(s)")
        return 1
    print("OK PERMISSIONS: matrice +/slash, owner, modération, sécurité et tickets conformes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_sync())
