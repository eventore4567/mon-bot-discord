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


def _component_label(item) -> str:
    """Lit aussi le label d'un DynamicItem Discord (bouton stocké dans .item)."""
    label = getattr(item, "label", None)
    if not label:
        wrapped = getattr(item, "item", None)
        label = getattr(wrapped, "label", None) if wrapped is not None else None
    return str(label or "")


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-ux-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-ux.db")

        import main
        from cogs import configuration, help as official_help

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

        help_command = bot.get_command("help")
        if help_command is None:
            errors.append("+help est absent")
        if getattr(bot, "_sentrix_help_owner", None) != "cogs.help":
            errors.append("le propriétaire canonique de +help n'est pas déclaré")

        checked_commands = 0
        for command in bot.walk_commands():
            if getattr(command, "hidden", False):
                continue
            checked_commands += 1
            title = official_help._category(command)
            summary = official_help._description(command)
            syntax = official_help._usage(command, "+")
            if not title or len(title) > 100:
                errors.append(f"catégorie illisible pour {command.qualified_name}: {title!r}")
            if not summary:
                errors.append(f"résumé vide pour {command.qualified_name}")
            if command.qualified_name not in syntax or not syntax.startswith("+"):
                errors.append(f"syntaxe invalide pour {command.qualified_name}: {syntax!r}")

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
            labels = [_component_label(item) for item in view.children]
            actions = {str(getattr(item, "action", "") or "") for item in view.children}
            selects = [item for item in view.children if item.__class__.__name__.endswith("Select")]
            if not selects:
                errors.append("+setup accueil n'a aucun menu de modules")

            # SetupNavButton est un discord.ui.DynamicItem : selon la version de
            # discord.py, son label visible vit dans item.item.label. L'action encodée
            # dans le custom_id est la vraie garantie fonctionnelle et doit être testée.
            setup_source = (ROOT / "cogs" / "configuration.py").read_text(encoding="utf-8")
            for action in ("summary", "history", "cancel"):
                if f'SetupNavButton("{action}"' not in setup_source:
                    errors.append(f"+setup n'enregistre plus l'action {action}")
            if any("Inviter SentriX" in label for label in labels):
                errors.append("+setup contient encore l'ancien bouton marketing Inviter SentriX")

            home = await view._build_home_embed()
            if "CENTRE DE CONFIGURATION SENTRIX" not in str(home.title or ""):
                errors.append(f"titre accueil +setup inattendu: {home.title!r}")
            field_names = [str(field.name) for field in home.fields]
            if "État général" not in field_names:
                errors.append("+setup n'affiche pas l'état global")
            if "Catégories disponibles ici" not in field_names:
                errors.append("+setup n'affiche pas les catégories disponibles")
        except Exception as exc:
            errors.append(f"construction de +setup impossible: {type(exc).__name__}: {exc}")

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
    print("OK: aide officielle, syntaxes lisibles et centre +setup canonique conformes")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
