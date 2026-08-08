#!/usr/bin/env python3
"""Audit CI du choix FR/EN, y compris le payload final des composants Discord."""
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
        from cogs.language_setup_finalizer import LANGUAGE_CATEGORY_VALUE, LANGUAGE_PAGE

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

        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_EN)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_EN:
            errors.append("la preference English n'est pas persistante")
        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_FR)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_FR:
            errors.append("la preference Francais n'est pas persistante")

        if common_command_names.FRENCH_COMMAND_ALIASES:
            errors.append("FRENCH_COMMAND_ALIASES n'a pas ete desactive")

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
                errors.append(f"nom FR {french} ne pointe pas vers {canonical}")
            if bot.get_command(english) is not base:
                errors.append(f"nom EN {english} ne pointe pas vers {canonical}")

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

        if not getattr(configuration.SetupView, "_sentrix_language_payload_guard", False):
            errors.append("+setup n'a pas le garde-fou final-wire pour la langue")

        initial_view = language_runtime.LanguageChoiceView(bot)
        custom_ids = {getattr(item, "custom_id", None) for item in initial_view.children}
        if custom_ids != {"sentrix:language:fr", "sentrix:language:en"}:
            errors.append(f"boutons langue initiaux inattendus: {custom_ids}")

        try:
            setup_view = configuration.SetupView(
                bot,
                guild_id=123456789,
                author_id=111,
                message_id=222,
                channel_id=333,
            )

            def find_language_select(view):
                for item in view.children:
                    options = list(getattr(item, "options", []) or [])
                    if any(str(getattr(opt, "value", "")) == LANGUAGE_CATEGORY_VALUE for opt in options):
                        return item
                return None

            # Juste après construction : la langue doit être la PREMIERE option.
            select = find_language_select(setup_view)
            if select is None:
                errors.append("Langue absente du menu Categories juste apres construction")
            else:
                if str(getattr(select.options[0], "value", "")) != LANGUAGE_CATEGORY_VALUE:
                    errors.append("Langue n'est pas la premiere option du menu Categories")
                label = str(getattr(select.options[0], "label", "") or "")
                if "Langue" not in label and "Language" not in label:
                    errors.append(f"label langue incomprehensible: {label!r}")

            # Test du dictionnaire EXACT sérialisé par discord.py avant envoi réseau.
            payload = setup_view.to_components()
            serialized_category = None
            for row in payload:
                for component in row.get("components", []):
                    options = component.get("options") or []
                    if any(str(option.get("value", "")) == LANGUAGE_CATEGORY_VALUE for option in options):
                        serialized_category = component
                        break
                if serialized_category:
                    break

            if serialized_category is None:
                errors.append("CRITIQUE: Langue absente du payload final envoye a Discord")
            elif str(serialized_category["options"][0].get("value", "")) != LANGUAGE_CATEGORY_VALUE:
                errors.append("CRITIQUE: Langue n'est pas premiere dans le payload Discord")

            # Retour accueil : même garantie.
            setup_view.page = -1
            setup_view.render_page()
            payload_after_home = setup_view.to_components()
            found_after_home = any(
                str(option.get("value", "")) == LANGUAGE_CATEGORY_VALUE
                for row in payload_after_home
                for component in row.get("components", [])
                for option in (component.get("options") or [])
            )
            if not found_after_home:
                errors.append("Langue perdue apres render_page de l'accueil")

            # Page langue : FR, EN et Accueil.
            setup_view.page = LANGUAGE_PAGE
            setup_view.render_page()
            ids = {getattr(item, "custom_id", None) for item in setup_view.children}
            expected = {
                "sentrix:setup:lang:fr",
                "sentrix:setup:lang:en",
                "sentrix:setup:lang:home",
            }
            if ids != expected:
                errors.append(f"composants de la page Langue invalides: {ids}")

            language_embed = await setup_view.build_embed()
            if "Langue" not in str(language_embed.title or "") and "Language" not in str(language_embed.title or ""):
                errors.append(f"embed Langue invalide: {language_embed.title!r}")

            # Aucun menu FR/EN séparé sur l'accueil.
            setup_view.page = -1
            setup_view.render_page()
            for item in setup_view.children:
                values = {str(getattr(opt, "value", "")) for opt in getattr(item, "options", [])}
                if values == {"fr", "en"}:
                    errors.append("un menu FR/EN separe existe encore hors des Categories")

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
    print("OK: FR/EN persistant et Langue est la 1re option du payload Discord final de +setup")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
