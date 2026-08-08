#!/usr/bin/env python3
"""Audit CI du nouveau rendu +help / +setup sans connexion à Discord."""
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

    with tempfile.TemporaryDirectory(prefix="sentrix-ux-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-ux.db")

        import main
        from cogs import command_clarity, configuration, setup_oxyde_style

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

        bot._prune_redundant_commands()

        if not command_clarity._INSTALLED:
            errors.append("command_clarity n'est pas installé après le chargement de Utility")
        if not setup_oxyde_style._INSTALLED:
            errors.append("le nouveau style +setup n'est pas installé")

        help_command = bot.get_command("help")
        if help_command is None:
            errors.append("+help est absent")
        elif not getattr(help_command, "_sentrix_clarity_callback", False):
            errors.append("+help n'utilise pas le callback de fiche claire")

        checked_commands = 0
        for command in bot.walk_commands():
            if getattr(command, "hidden", False):
                continue
            checked_commands += 1
            title = command_clarity.friendly_title(command)
            summary = command_clarity.friendly_summary(command)
            syntax = command_clarity.command_usage(command, "+")
            example = command_clarity.example_usage(command, "+")
            if not title or len(title) > 70:
                errors.append(f"titre illisible pour {command.qualified_name}: {title!r}")
            if not summary or "Aucune description" in summary or "Pas de description" in summary:
                errors.append(f"résumé illisible pour {command.qualified_name}: {summary!r}")
            if command.qualified_name not in syntax or not syntax.startswith("+"):
                errors.append(f"syntaxe invalide pour {command.qualified_name}: {syntax!r}")
            if command.qualified_name not in example or not example.startswith("+"):
                errors.append(f"exemple invalide pour {command.qualified_name}: {example!r}")

        # Le setup doit réellement ressembler à un centre de configuration : menu de
        # modules, boutons de navigation utiles, aucune rangée marketing Inviter/Sécurité.
        try:
            view = configuration.SetupView(
                bot,
                guild_id=987654321,
                author_id=123456789,
                message_id=555555555,
                channel_id=444444444,
            )
            labels = [str(getattr(item, "label", "") or "") for item in view.children]
            selects = [item for item in view.children if item.__class__.__name__.endswith("Select")]
            if not selects:
                errors.append("+setup accueil n'a aucun menu de modules")
            if not any("Résumé" in label for label in labels):
                errors.append("+setup accueil n'a pas de bouton Résumé")
            if not any("Historique" in label for label in labels):
                errors.append("+setup accueil n'a pas de bouton Historique")
            if not any("Fermer" in label for label in labels):
                errors.append("+setup accueil n'a pas de bouton Fermer")
            if any("Inviter SentriX" in label for label in labels):
                errors.append("+setup contient encore l'ancien bouton marketing Inviter SentriX")

            home = await view._build_home_embed()
            if "Centre de contrôle" not in str(home.title or ""):
                errors.append(f"titre accueil +setup inattendu: {home.title!r}")
            field_names = [str(field.name) for field in home.fields]
            if not any("État de la configuration" in name for name in field_names):
                errors.append("+setup n'affiche pas l'état global")
            if not any("À faire maintenant" in name for name in field_names):
                errors.append("+setup n'affiche pas les prochaines actions")
        except Exception as exc:
            errors.append(f"construction de +setup impossible: {type(exc).__name__}: {exc}")

        for step in configuration.SETUP_STEPS:
            if step["key"] == "summary":
                continue
            if not str(step.get("description") or "").strip():
                errors.append(f"module +setup sans explication: {step['key']}")

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

    print(f"UX audit: {checked_commands} commande(s) vérifiée(s)")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} problème(s) UX")
        return 1
    print("OK: toutes les commandes ont une fiche claire et +setup utilise le nouveau centre de contrôle")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
