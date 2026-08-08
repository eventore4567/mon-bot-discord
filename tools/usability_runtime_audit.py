#!/usr/bin/env python3
"""Audit CI des améliorations d'utilisation quotidiennes SentriX."""
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


EXPECTED_ALIASES = {
    "aide": "help",
    "bannir": "ban",
    "debannir": "unban",
    "avertir": "warn",
    "muet": "mute",
    "configurer": "setup",
    "securite": "security-check",
    "solde": "balance",
    "boutique": "shop",
    "niveau": "level",
    "profil": "profile",
    "sondage": "poll",
    "meteo": "weather",
    "traduire": "translate",
}


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-usability-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-usability.db")

        import main
        from discord.ext import commands
        from cogs import common_command_names

        bot = main.BotAllInOne()
        await bot.db.connect()

        loaded = 0
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded += 1
            except Exception as exc:
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")

        if loaded != len(main.EXTENSIONS):
            errors.append(f"extensions chargées: {loaded}/{len(main.EXTENSIONS)}")

        bot._prune_redundant_commands()

        for alias, canonical in EXPECTED_ALIASES.items():
            resolved = bot.get_command(alias)
            target = bot.get_command(canonical)
            if target is None:
                errors.append(f"commande canonique absente: {canonical}")
                continue
            if resolved is not target:
                errors.append(f"alias +{alias} ne pointe pas vers +{canonical}")

        if not getattr(commands.UserConverter.convert, "_sentrix_resilient_user_converter", False):
            errors.append("UserConverter n'a pas le fallback fetch_user pour les IDs hors cache")

        if not common_command_names._USER_CONVERTER_PATCHED:
            errors.append("flag de résolution utilisateur robuste inactif")

        if not getattr(bot, "_sentrix_mention_help_listener", False):
            errors.append("aide lors d'une mention directe de SentriX non installée")

        # Les alias français sont secondaires : +help doit continuer à afficher le nom
        # préféré existant plutôt que remplacer toute l'interface par les alias.
        help_command = bot.get_command("help")
        if help_command is not None and common_command_names.preferred_name(help_command) != "help":
            errors.append("l'alias +aide a remplacé le nom préféré de +help")

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

    print(f"Usability audit: {loaded}/{len(main.EXTENSIONS)} extensions chargées")
    print(f"Usability audit: {len(EXPECTED_ALIASES)} alias français critiques vérifiés")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} problème(s) d'utilisation")
        return 1
    print("OK: alias français, résolution des IDs et aide au ping direct sont actifs")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
