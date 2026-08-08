#!/usr/bin/env python3
"""Audit CI du choix FR/EN sans connexion a Discord."""
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
    with tempfile.TemporaryDirectory(prefix="sentrix-language-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-language.db")

        import main
        from cogs import common_command_names, configuration, language_runtime

        bot = main.BotAllInOne()
        await bot.db.connect()
        loaded = []
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded.append(extension)
            except Exception as exc:
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")

        if len(loaded) != len(main.EXTENSIONS):
            errors.append(f"extensions chargees: {len(loaded)}/{len(main.EXTENSIONS)}")

        bot._prune_redundant_commands()

        # Preference persistante.
        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_EN)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_EN:
            errors.append("la preference English n'est pas persistante")
        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_FR)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_FR:
            errors.append("la preference Francais n'est pas persistante")

        # Les anciens alias FR ad hoc ne doivent plus etre la source de verite.
        if common_command_names.FRENCH_COMMAND_ALIASES:
            errors.append("FRENCH_COMMAND_ALIASES n'a pas ete desactive")

        # Les traductions pointent vers LE MEME objet commande, donc aucune copie fonctionnelle.
        checks = [
            ("ban", "bannir", "ban"),
            ("help", "aide", "help"),
            ("setup", "configurer", "setup"),
            ("balance", "solde", "balance"),
            ("poll", "sondage", "poll"),
        ]
        for canonical, french, english in checks:
            base = bot.get_command(canonical)
            if base is None:
                errors.append(f"commande canonique absente: {canonical}")
                continue
            if bot.get_command(french) is not base:
                errors.append(f"alias FR {french} ne pointe pas vers {canonical}")
            if bot.get_command(english) is not base:
                errors.append(f"nom EN {english} ne pointe pas vers {canonical}")

        # Chaque commande a exactement un nom d'affichage par langue et aucun conflit dans
        # un meme groupe. Les alias peuvent exister dans le registre, mais walk_commands()
        # ne doit jamais contenir de copie supplementaire.
        seen_objects = set()
        collisions: dict[tuple[int, str, str], str] = {}
        visible = 0
        for command in bot.walk_commands():
            if getattr(command, "hidden", False):
                continue
            visible += 1
            seen_objects.add(id(command))
            for language in (language_runtime.LANG_FR, language_runtime.LANG_EN):
                name = language_runtime.localized_command_name(command, language)
                if not name or "  " in name:
                    errors.append(f"nom {language} invalide pour {command.qualified_name}: {name!r}")
                parent = getattr(command, "parent", None)
                key = (id(parent) if parent else 0, language, language_runtime.localized_component(command, language))
                old = collisions.get(key)
                if old and old != command.qualified_name:
                    errors.append(f"collision {language}: {old} / {command.qualified_name} -> {key[2]}")
                collisions[key] = command.qualified_name

        if len(seen_objects) != visible:
            errors.append("walk_commands contient des objets commandes dupliques")

        help_command = bot.get_command("help")
        if help_command is None or not getattr(help_command, "_sentrix_language_help", False):
            errors.append("+help n'utilise pas le rendu localise")

        if not getattr(configuration.SetupView, "_sentrix_language_patch", False):
            errors.append("+setup n'a pas le selecteur de langue")

        # La vue initiale doit survivre aux redemarrages et proposer exactement FR/EN.
        view = language_runtime.LanguageChoiceView(bot)
        custom_ids = {getattr(item, "custom_id", None) for item in view.children}
        if custom_ids != {"sentrix:language:fr", "sentrix:language:en"}:
            errors.append(f"boutons langue inattendus: {custom_ids}")

        # Construction du setup : le changement de langue doit etre impossible a rater.
        # On exige a la fois le menu FR/EN ET un bouton visible dans la rangée d'actions.
        try:
            setup_view = configuration.SetupView(
                bot,
                guild_id=123456789,
                author_id=111,
                message_id=222,
                channel_id=333,
            )
            language_selects = [
                item for item in setup_view.children
                if item.__class__.__name__.endswith("Select")
                and {getattr(option, "value", None) for option in getattr(item, "options", [])} == {"fr", "en"}
            ]
            if not language_selects:
                errors.append("aucun selecteur FR/EN sur l'accueil +setup")
            else:
                if getattr(language_selects[0], "row", None) != 3:
                    errors.append("le selecteur FR/EN n'est pas place sur la ligne dediee du +setup")

            language_buttons = [
                item for item in setup_view.children
                if getattr(item, "custom_id", None) == "sentrix:setup:language"
            ]
            if not language_buttons:
                errors.append("aucun bouton Langue visible sur l'accueil +setup")
            else:
                label = str(getattr(language_buttons[0], "label", "") or "")
                if "Langue" not in label and "Language" not in label:
                    errors.append(f"label du bouton langue incomprehensible: {label!r}")
                if getattr(language_buttons[0], "row", None) != 1:
                    errors.append("le bouton Langue n'est pas dans la rangee d'actions principale")
        except Exception as exc:
            errors.append(f"construction +setup langue impossible: {type(exc).__name__}: {exc}")

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

    print(f"Language audit: {visible} commande(s) verifiee(s)")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s)")
        return 1
    print("OK: FR/EN persistant, aucune copie de commande, bouton + menu langue visibles dans +setup")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
