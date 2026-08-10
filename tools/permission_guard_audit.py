#!/usr/bin/env python3
"""Audit de la matrice de permissions SentriX sans connexion a Discord.

Ce test charge le vrai registre de commandes et les vrais runtimes, puis verifie les
frontieres de securite qui doivent rester invariantes : aide publique, commandes membres
publiques, administration protegee, blacklist owner-only et fail-closed pour toute future
commande oubliee. Les deux chemins prefixe et slash doivent utiliser le meme garde.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _close_runtime(bot) -> None:
    current = asyncio.current_task()
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not current and not task.done()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    close_db = getattr(bot.db, "close", None)
    if close_db:
        result = close_db()
        if inspect.isawaitable(result):
            await result


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-permission-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-permissions.db")

        import main
        from cogs import permission_guard
        from database.db import PRIMARY_CREATOR_ID

        bot = main.BotAllInOne()
        await bot.db.connect()

        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
            except Exception as exc:
                errors.append(
                    f"extension {extension}: {type(exc).__name__}: {exc}"
                )

        bot._prune_redundant_commands()

        if not getattr(bot, "_sentrix_permission_guard_installed", False):
            errors.append("le garde de permissions n'est pas installe sur le bot")
        if not getattr(bot.global_permission_check, "_sentrix_permission_guard", False):
            errors.append("le chemin prefixe n'utilise pas le garde central")
        if not getattr(bot.tree.interaction_check, "_sentrix_permission_guard", False):
            errors.append("le chemin slash n'utilise pas le garde central")

        help_command = bot.get_command("help")
        if help_command is None:
            errors.append("+help est absent du registre")
        else:
            if "help" not in main.PUBLIC_COMMANDS:
                errors.append("help n'est pas classe public")
            if not getattr(help_command, "_sentrix_help_public", False):
                errors.append("help n'est pas marque public par le garde final")
            if list(getattr(help_command, "checks", ())):
                errors.append("help conserve un check local qui peut bloquer les membres")
            app_command = getattr(help_command, "app_command", None)
            if app_command is not None and list(getattr(app_command, "checks", ())):
                errors.append("/help conserve un check local qui peut bloquer les membres")

        critical_owner_only = {"bl", "blinfo", "unbl", "editbl"}
        missing_owner_only = sorted(critical_owner_only - main.OWNER_ONLY_COMMANDS)
        if missing_owner_only:
            errors.append(
                "commandes blacklist globales non owner-only: "
                + ", ".join(missing_owner_only)
            )

        privileged_roots = set(main.OWNER_ONLY_COMMANDS)
        privileged_roots.update(main.DISCORD_PERMISSION_COMMANDS)
        for names in main.CATEGORY_COMMANDS.values():
            privileged_roots.update(names)
        privileged_roots.update(main.CUSTOM_PERMISSION_COMMANDS)

        public_privileged = sorted(main.PUBLIC_COMMANDS & privileged_roots)
        if public_privileged:
            errors.append(
                "commandes sensibles classees publiques: "
                + ", ".join(public_privileged)
            )

        blacklist_public = sorted(
            name for name in main.PUBLIC_COMMANDS if "blacklist" in name.casefold()
        )
        if blacklist_public:
            errors.append(
                "commandes blacklist accessibles aux membres: "
                + ", ".join(blacklist_public)
            )

        normal_user = SimpleNamespace(id=987654321012345678)
        owner_user = SimpleNamespace(id=PRIMARY_CREATOR_ID)

        expected_normal = {
            "help": True,
            "ping": True,
            "bl": False,
            "setup": False,
            "ban": False,
            "blacklist-user": False,
            "blacklist-add": False,
            "unknown-new-command": False,
        }
        for command_name, expected_allowed in expected_normal.items():
            decision = await permission_guard.evaluate_command_access(
                bot,
                command_name=command_name,
                author=normal_user,
                guild=None,
            )
            if decision.allowed != expected_allowed:
                errors.append(
                    f"membre normal: {command_name} => allowed={decision.allowed} "
                    f"policy={decision.policy!r}, attendu={expected_allowed}"
                )

        for command_name in ("bl", "setup", "ban", "unknown-new-command"):
            decision = await permission_guard.evaluate_command_access(
                bot,
                command_name=command_name,
                author=owner_user,
                guild=None,
            )
            if not decision.allowed:
                errors.append(
                    f"proprietaire verifie refuse sur {command_name}: {decision.policy}"
                )

        blacklisted_id = 987654321012345679
        bot.blacklist_cache[blacklisted_id] = "audit-ci"
        fake_interaction = SimpleNamespace(
            user=SimpleNamespace(id=blacklisted_id),
            guild=None,
            command=None,
            data={"name": "help"},
        )
        blacklisted_decision = await permission_guard.evaluate_interaction_access(
            bot, fake_interaction
        )
        if blacklisted_decision.allowed or blacklisted_decision.policy != "global-blacklist":
            errors.append(
                "la blacklist globale ne bloque pas correctement les commandes slash"
            )

        # Verification structurelle supplementaire : chaque racine active doit etre classee
        # ou rester volontairement dans le fail-closed. Aucun oubli ne doit devenir public.
        roots = {command.name.casefold() for command in bot.commands}
        known = set(main.KNOWN_PERMISSION_COMMANDS)
        unknown = sorted(roots - known)
        for name in unknown:
            decision = await permission_guard.evaluate_command_access(
                bot,
                command_name=name,
                author=normal_user,
                guild=None,
            )
            if decision.allowed:
                errors.append(f"commande non classee devenue publique: {name}")

        print(
            "Permission matrix: "
            f"{len(main.PUBLIC_COMMANDS)} publiques, "
            f"{len(main.OWNER_ONLY_COMMANDS)} owner-only, "
            f"{len(main.DISCORD_PERMISSION_COMMANDS)} permissions Discord, "
            f"{sum(len(names) for names in main.CATEGORY_COMMANDS.values())} commandes de gestion"
        )
        print("+help et /help: acces membre force et verifie")
        print("Blacklist: bl/blinfo/unbl/editbl owner-only + utilisateurs blacklistes bloques en slash")
        print("Administration: permissions Discord/categories + fail-closed verifiees")
        print("Prefixe/slash: matrice centrale partagee verifiee")

        await _close_runtime(bot)

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s) de permissions detecte(s)")
        return 1

    print("OK: matrice de permissions SentriX coherente et fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
