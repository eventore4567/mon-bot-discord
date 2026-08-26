#!/usr/bin/env python3
"""Audit runtime de la surface de commandes et des permissions SentriX."""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def run() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-command-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-ci.db")

        import main
        from cogs import (
            command_catalog_cleanup,
            command_response_guard,
            help_complete,
            slash_command_budget,
        )

        bot = main.BotAllInOne()
        await bot.db.connect()

        loaded: list[str] = []
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded.append(extension)
            except Exception as exc:
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")

        if len(loaded) != len(main.EXTENSIONS):
            errors.append(f"extensions chargées: {len(loaded)}/{len(main.EXTENSIONS)}")

        if not command_catalog_cleanup._INSTALLED:
            errors.append("politique canonique du catalogue non installée")

        if len(command_catalog_cleanup.NORMAL_DIRECT_COMMANDS) != 100:
            errors.append(
                "la surface normale doit contenir exactement 100 commandes directes, "
                f"obtenu: {len(command_catalog_cleanup.NORMAL_DIRECT_COMMANDS)}"
            )
        if len(command_catalog_cleanup.GAME_COMMANDS) != 43:
            errors.append(
                f"les 43 jeux doivent rester directs, obtenu: {len(command_catalog_cleanup.GAME_COMMANDS)}"
            )

        expected_pruned = command_catalog_cleanup.PURE_DUPLICATE_COMMANDS
        if main.PRUNED_COMMANDS != expected_pruned:
            errors.append(
                "seuls les vrais doublons doivent être prunés: "
                + ", ".join(sorted(main.PRUNED_COMMANDS ^ expected_pruned))
            )

        bot._prune_redundant_commands()
        command_catalog_cleanup.apply_surface(bot)
        slash_command_budget.finalize(bot)

        active = list(bot.walk_commands())
        qualified = [command.qualified_name.casefold() for command in active]
        if not active:
            errors.append("aucune commande enregistrée")
        if len(qualified) != len(set(qualified)):
            duplicates = sorted({name for name in qualified if qualified.count(name) > 1})
            errors.append("commandes dupliquées: " + ", ".join(duplicates))

        for command in active:
            callback = getattr(command, "callback", None)
            if callback is None or not inspect.iscoroutinefunction(callback):
                errors.append(f"callback non asynchrone/invalide: {command.qualified_name}")
            try:
                _ = command.signature
            except Exception as exc:
                errors.append(
                    f"signature impossible pour {command.qualified_name}: {type(exc).__name__}: {exc}"
                )

        missing_direct = sorted(
            name for name in command_catalog_cleanup.NORMAL_DIRECT_COMMANDS
            if bot.get_command(name) is None
        )
        if missing_direct:
            errors.append("commandes directes normales absentes: " + ", ".join(missing_direct))

        hidden_direct = sorted(
            name for name in command_catalog_cleanup.NORMAL_DIRECT_COMMANDS
            if (command := bot.get_command(name)) is not None and command.hidden
        )
        if hidden_direct:
            errors.append("commandes directes anormalement masquées: " + ", ".join(hidden_direct))

        missing_admin = sorted(
            name for name in command_catalog_cleanup.ADMIN_DIRECT_COMMANDS
            if bot.get_command(name) is None
        )
        if missing_admin:
            errors.append("commandes admin directes absentes: " + ", ".join(missing_admin))

        removed_still_present = sorted(
            name for name in command_catalog_cleanup.PURE_DUPLICATE_COMMANDS
            if bot.get_command(name) is not None
        )
        if removed_still_present:
            errors.append("vrais doublons encore enregistrés: " + ", ".join(removed_still_present))

        merged_visible = sorted(
            name for name in command_catalog_cleanup.MERGED_COMMANDS
            if (command := bot.get_command(name)) is not None and not command.hidden
        )
        if merged_visible:
            errors.append("anciennes commandes fusionnées encore visibles: " + ", ".join(merged_visible))

        for required in ("ticket", "giveaway", "giveaway-reroll", "help", "security"):
            if bot.get_command(required) is None:
                errors.append(f"racine essentielle absente: {required}")

        help_command = bot.get_command("help")
        if help_command is not None:
            if help_command.hidden:
                errors.append("+help est masqué alors qu'il doit être public")
            if getattr(help_command, "checks", []):
                errors.append("+help possède encore un check local staff")
        if "help" not in main.PUBLIC_COMMANDS:
            errors.append("+help n'est pas classé PUBLIC_COMMANDS")

        owner_expected = {
            "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
            "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
        }
        if not owner_expected <= set(main.OWNER_ONLY_COMMANDS):
            errors.append("certaines commandes propriétaire ne sont plus owner-only")

        security_sensitive = {"blacklist-add", "blacklist-users", "panic", "syncbl"}
        public_security = sorted(security_sensitive & set(main.PUBLIC_COMMANDS))
        if public_security:
            errors.append("commandes sécurité sensibles classées publiques: " + ", ".join(public_security))
        if not security_sensitive <= set(main.CATEGORY_COMMANDS.get("securite", ())):
            errors.append("commandes sécurité directes absentes de la catégorie protégée securite")
        for name in ("quarantine", "unquarantine"):
            if main.DISCORD_PERMISSION_COMMANDS.get(name) != "moderate_members":
                errors.append(f"{name} doit exiger moderate_members")
        for name in ("nickname", "resetnick"):
            if main.DISCORD_PERMISSION_COMMANDS.get(name) != "manage_nicknames":
                errors.append(f"{name} doit exiger manage_nicknames")
        for name in ("giverole", "removerole"):
            if main.DISCORD_PERMISSION_COMMANDS.get(name) != "manage_roles":
                errors.append(f"{name} doit exiger manage_roles")

        if not getattr(bot, "_sentrix_permission_guard_installed", False):
            errors.append("le verrou global de permissions slash n'est pas installé")

        app_roots = list(bot.tree.get_commands())
        app_root_names = {str(command.name).casefold() for command in app_roots}
        expected_slash = {
            "nick" if name == "nickname" else name
            for name in command_catalog_cleanup.NORMAL_DIRECT_COMMANDS
        }
        missing_slash_direct = sorted(expected_slash - app_root_names)
        if len(app_roots) > slash_command_budget.GLOBAL_CHAT_INPUT_BUDGET:
            errors.append(f"trop de racines slash: {len(app_roots)}/100")
        if "nick" not in app_root_names:
            errors.append("/nick est absent")

        admin_slash = sorted(app_root_names & set(command_catalog_cleanup.ADMIN_DIRECT_COMMANDS))
        if admin_slash:
            errors.append("commandes admin présentes en slash: " + ", ".join(admin_slash))

        merged_slash = sorted(app_root_names & set(command_catalog_cleanup.MERGED_COMMANDS))
        if merged_slash:
            errors.append("anciennes commandes fusionnées encore en slash: " + ", ".join(merged_slash))

        if not command_response_guard._INSTALLED:
            errors.append("le filet de sécurité de réponse des commandes n'est pas installé")

        required_listeners = {
            "on_command": "départ des commandes +",
            "on_command_completion": "fin des commandes +",
            "on_command_error": "erreurs des commandes +",
            "on_interaction": "départ des commandes slash",
            "on_app_command_completion": "fin des commandes slash",
        }
        for event_name, label in required_listeners.items():
            if not bot.extra_events.get(event_name, []):
                errors.append(f"listener absent: {label} ({event_name})")

        if getattr(bot, "_sentrix_help_owner", None) != "cogs.help_simple":
            errors.append("l'aide canonique simple n'est pas installée")

        category_counts: Counter[str] = Counter()
        uncategorized: list[str] = []
        for command in active:
            if getattr(command, "hidden", False):
                continue
            category = help_complete._category_for(command)
            category_counts[category.key] += 1
            if category.key == "other":
                uncategorized.append(command.qualified_name)
        if uncategorized:
            warnings.append(
                f"{len(uncategorized)} commandes utilisent la catégorie de repli Fonctionnalités avancées"
            )

        print(f"SentriX audit: {len(active)} commandes texte/hybrides chargées")
        print(f"SentriX audit: {len(app_roots)}/100 racines slash enregistrées")
        print(f"SentriX audit: {len(command_catalog_cleanup.NORMAL_DIRECT_COMMANDS)} commandes normales directes")
        print(f"SentriX audit: {len(command_catalog_cleanup.ADMIN_DIRECT_COMMANDS)} commandes admin directes + uniquement")
        print(f"SentriX audit: {len(command_catalog_cleanup.GAME_COMMANDS)} jeux directs")
        if missing_slash_direct:
            print("Slash directs absents: " + ", ".join(missing_slash_direct))
        print(f"Extensions: {len(loaded)}/{len(main.EXTENSIONS)} chargées")
        print("Catégories visibles +help:")
        for category in help_complete.CATEGORIES:
            count = category_counts.get(category.key, 0)
            if count:
                print(f"  {category.key}: {count}")
        if len(app_roots) < 100:
            warnings.append(f"catalogue slash sous le plafond: {len(app_roots)}/100")
        for warning in warnings:
            print(f"[WARN] {warning}")
        for error in errors:
            print(f"[ERROR] {error}")

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        close_db = getattr(bot.db, "close", None)
        if close_db:
            result = close_db()
            if inspect.isawaitable(result):
                await result

    if errors:
        print(f"ECHEC: {len(errors)} problème(s) détecté(s)")
        return 1
    print("OK: catalogue, +help et permissions préfixe/slash conformes")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
