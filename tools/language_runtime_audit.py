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
                errors.append(f"alias FR {french} ne pointe pas vers {canonical}")
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

        if not getattr(configuration.SetupView, "_sentrix_language_patch", False):
            errors.append("+setup n'a pas le support de langue")

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

            # Teste le vrai état juste APRES le constructeur, car c'est exactement le
            # panneau que +setup envoie pour la première fois sur Discord.
            selects = [item for item in setup_view.children if isinstance(item, __import__("discord").ui.Select)]
            category_selects = []
            for item in selects:
                values = [str(getattr(option, "value", "")) for option in getattr(item, "options", [])]
                if LANGUAGE_CATEGORY_VALUE in values:
                    category_selects.append(item)

            if len(category_selects) != 1:
                errors.append(f"menu Categories final avec Langue attendu 1 fois, trouve {len(category_selects)}")
            else:
                category_select = category_selects[0]
                matches = [
                    option for option in category_select.options
                    if str(getattr(option, "value", "")) == LANGUAGE_CATEGORY_VALUE
                ]
                if len(matches) != 1:
                    errors.append(f"option Langue dupliquee ou absente: {len(matches)}")
                else:
                    option = matches[0]
                    label = str(getattr(option, "label", "") or "")
                    if "Langue" not in label and "Language" not in label:
                        errors.append(f"label langue incomprehensible: {label!r}")
                    if str(getattr(option, "emoji", "") or "") != "🌐":
                        errors.append(f"emoji langue invalide: {getattr(option, 'emoji', None)!r}")
                if getattr(category_select, "row", None) != 0:
                    errors.append("le menu Categories contenant Langue n'est pas sur la ligne principale")

            # Teste aussi un retour Accueil : _render_home doit remettre l'option tout seul.
            setup_view._render_home()
            home_matches = []
            for item in setup_view.children:
                if not isinstance(item, __import__("discord").ui.Select):
                    continue
                home_matches.extend(
                    option for option in getattr(item, "options", [])
                    if str(getattr(option, "value", "")) == LANGUAGE_CATEGORY_VALUE
                )
            if len(home_matches) != 1:
                errors.append(f"retour accueil perd la categorie Langue: {len(home_matches)} option(s)")

            # Ouvre réellement la page virtuelle de langue et vérifie ce qui est rendu.
            setup_view.page = LANGUAGE_PAGE
            setup_view.render_page()
            lang_buttons = {
                getattr(item, "custom_id", None)
                for item in setup_view.children
                if getattr(item, "custom_id", None) in {
                    "sentrix:setup:lang:fr", "sentrix:setup:lang:en", "sentrix:setup:lang:home"
                }
            }
            expected_buttons = {
                "sentrix:setup:lang:fr", "sentrix:setup:lang:en", "sentrix:setup:lang:home"
            }
            if lang_buttons != expected_buttons:
                errors.append(f"boutons page Langue invalides: {lang_buttons}")

            language_embed = await setup_view.build_embed()
            if "Langue" not in str(language_embed.title or "") and "Language" not in str(language_embed.title or ""):
                errors.append(f"embed de page Langue invalide: {language_embed.title!r}")

            # Le correctif ne doit plus modifier SETUP_STEPS : les index historiques restent intacts.
            if any(step.get("key") == "language" for step in configuration.SETUP_STEPS):
                errors.append("SETUP_STEPS contient encore une etape language ajoutee a chaud")

            # Aucun sélecteur FR/EN séparé sur l'accueil.
            setup_view.page = -1
            setup_view.render_page()
            standalone_language_selects = []
            for item in setup_view.children:
                if not isinstance(item, __import__("discord").ui.Select):
                    continue
                values = {str(getattr(option, "value", "")) for option in getattr(item, "options", [])}
                if values == {"fr", "en"}:
                    standalone_language_selects.append(item)
            if standalone_language_selects:
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
    print("OK: FR/EN persistant et Langue forcee dans le vrai menu Categories de +setup")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
