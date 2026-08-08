#!/usr/bin/env python3
"""Audit CI des améliorations d'utilisation quotidiennes SentriX.

Les anciens alias français globaux ont été remplacés par le vrai mode de langue par
serveur. Cet audit vérifie donc la fiabilité commune (résolution d'ID, aide au ping) et
laisse les traductions FR/EN au language_runtime_audit dédié.
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


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-usability-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-usability.db")

        import main
        from discord.ext import commands
        from cogs import common_command_names, language_runtime

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

        # Les alias FR ad hoc de l'ancienne passe ne doivent plus exister comme système
        # indépendant. Les noms traduits sont désormais gérés par language_runtime.
        if common_command_names.FRENCH_COMMAND_ALIASES:
            errors.append("les anciens alias français globaux sont encore actifs")

        critical = {
            "help": ("aide", "help"),
            "ban": ("bannir", "ban"),
            "unban": ("debannir", "unban"),
            "warn": ("avertir", "warn"),
            "mute": ("rendre-muet", "mute"),
            "setup": ("configurer", "setup"),
            "security-check": ("verifier-securite", "security"),
            "balance": ("solde", "balance"),
            "shop": ("boutique", "shop"),
            "level": ("niveau", "level"),
            "profile": ("profil", "profile"),
            "poll": ("sondage", "poll"),
            "weather": ("meteo", "weather"),
            "translate": ("traduire", "translate"),
        }
        for canonical, (french, english) in critical.items():
            target = bot.get_command(canonical)
            if target is None:
                errors.append(f"commande canonique absente: {canonical}")
                continue
            if language_runtime.localized_command_name(target, language_runtime.LANG_FR) != french:
                errors.append(
                    f"nom FR inattendu pour {canonical}: "
                    f"{language_runtime.localized_command_name(target, language_runtime.LANG_FR)!r}"
                )
            if language_runtime.localized_command_name(target, language_runtime.LANG_EN) != english:
                errors.append(
                    f"nom EN inattendu pour {canonical}: "
                    f"{language_runtime.localized_command_name(target, language_runtime.LANG_EN)!r}"
                )

        if not getattr(commands.UserConverter.convert, "_sentrix_resilient_user_converter", False):
            errors.append("UserConverter n'a pas le fallback fetch_user pour les IDs hors cache")

        if not common_command_names._USER_CONVERTER_PATCHED:
            errors.append("flag de résolution utilisateur robuste inactif")

        # Le listener historique a volontairement été remplacé par le listener localisé.
        if not getattr(bot, "_sentrix_language_listeners", False):
            errors.append("listener d'aide localisé lors d'une mention directe de SentriX non installé")

        help_command = bot.get_command("help")
        if help_command is None or not getattr(help_command, "_sentrix_language_help", False):
            errors.append("+help n'utilise pas le rendu de langue par serveur")

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
    print(f"Usability audit: {len(critical)} commandes critiques FR/EN vérifiées")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} problème(s) d'utilisation")
        return 1
    print("OK: langue par serveur, résolution des IDs et aide au ping direct sont actives")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
