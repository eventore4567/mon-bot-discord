#!/usr/bin/env python3
"""Audit CI du choix FR/EN, du payload Discord final et du vrai Cog +setup."""
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


async def run() -> int:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sentrix-language-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-language.db")

        import main
        from cogs import common_command_names, language_runtime, setup_control_center
        from cogs.language_official_bridge import OfficialLanguageSelect

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

        # +setup est délibérément repris par cogs/setup_control_center.py::install(), qui
        # fait bot.remove_command("setup") puis bot.add_cog(OfficialSetup(bot)) et marque
        # bot._sentrix_setup_owner. cogs.configuration.SetupView (V6) et son finaliseur de
        # langue ne sont donc plus le chemin réel de +setup — ils restent chargés mais ne
        # sont jamais rendus. Le vrai porteur du sélecteur FR/EN est
        # cogs.setup_control_center.SetupView, rebranché par control_center_v3_language.py
        # (confirmé par un probe de boot réel : children = OfficialLanguageSelect/Button/
        # V70PageSelect sur l'instance réellement utilisée par /setup).
        setup_command = bot.get_command("setup")
        owner_cog = getattr(setup_command, "cog", None) if setup_command else None
        if getattr(bot, "_sentrix_setup_owner", None) != "cogs.setup_control_center":
            errors.append(
                "+setup n'est plus repris par cogs.setup_control_center | "
                f"bot._sentrix_setup_owner={getattr(bot, '_sentrix_setup_owner', None)!r}"
            )
        if setup_command is None or type(owner_cog).__name__ != "OfficialSetup":
            errors.append(
                "la commande +setup n'est pas rattachee au vrai Cog OfficialSetup | "
                f"cog={type(owner_cog).__name__ if owner_cog else None}"
            )

        if not getattr(setup_control_center.SetupView, "_sentrix_control_center_v3_language", False):
            errors.append("setup_control_center.SetupView n'a pas ete rebranche par control_center_v3_language")
        if not getattr(setup_control_center.SetupView, "_sentrix_language_payload_guard", False):
            errors.append("+setup n'a pas le garde-fou final-wire pour la langue (vrai SetupView)")

        initial_view = language_runtime.LanguageChoiceView(bot)
        custom_ids = {getattr(item, "custom_id", None) for item in initial_view.children}
        if custom_ids != {"sentrix:language:fr", "sentrix:language:en"}:
            errors.append(f"boutons langue initiaux inattendus: {custom_ids}")

        try:
            fake_guild = SimpleNamespace(
                id=123456789, name="Audit", default_role=SimpleNamespace(id=999),
                roles=[], channels=[], categories=[], text_channels=[], voice_channels=[],
                members=[], me=None, owner_id=1, icon=None, member_count=0,
            )
            def find_language_select(view):
                for item in view.children:
                    if isinstance(item, OfficialLanguageSelect):
                        return item
                return None

            def find_serialized_by_custom_id(components, target):
                # setup_control_center.SetupView imbrique tout dans UN Container (Components
                # V2) : la vraie profondeur est payload -> container.components ->
                # actionrow.components -> item, pas juste payload -> row.components comme
                # pour l'ancienne classe a plat. On descend donc recursivement plutot que de
                # ne verifier que deux niveaux.
                for component in components:
                    if component.get("custom_id") == target:
                        return component
                    nested = component.get("components")
                    if nested:
                        found = find_serialized_by_custom_id(nested, target)
                        if found is not None:
                            return found
                return None

            # cogs.setup_control_center.OfficialSetup.send_setup() construit toujours une
            # instance FRAICHE de SetupView puis appelle composer() une seule fois — jamais
            # render() seul sur une instance deja rendue. Reutiliser la meme instance pour
            # plusieurs verifications (render() puis composer()) reintroduit un etat perime
            # dans le pipeline de rendu qui fait disparaitre le selecteur du payload serialise
            # sans lever d'erreur : chaque verification ci-dessous utilise donc sa propre
            # instance fraiche, exactement comme en production.

            # Page d'accueil (category=None) : c'est la seule page ou
            # control_center_v3_language.py injecte le selecteur de langue.
            home_view = setup_control_center.SetupView(bot, fake_guild, 111)
            home_view.render()
            select = find_language_select(home_view)
            if select is None:
                errors.append("Langue absente du panneau +setup reellement rendu (accueil)")
            else:
                if getattr(select, "custom_id", None) != "sentrix:setup:official:language":
                    errors.append(f"custom_id du selecteur de langue inattendu: {select.custom_id!r}")
                values = {str(getattr(option, "value", "")) for option in select.options}
                if values != {language_runtime.LANG_FR, language_runtime.LANG_EN}:
                    errors.append(f"options du selecteur de langue inattendues: {values}")

            # Le payload REELLEMENT envoye a Discord passe par composer() (Components V2),
            # pas par render() seul : c'est lui qui doit contenir le selecteur de langue.
            payload_view = setup_control_center.SetupView(bot, fake_guild, 111)
            await payload_view.composer()
            payload = payload_view.to_components()
            serialized_select = find_serialized_by_custom_id(payload, "sentrix:setup:official:language")
            if serialized_select is None:
                errors.append("CRITIQUE: selecteur de langue absent du payload final envoye a Discord pour +setup")

            # Hors accueil (ex: moderation), le selecteur ne doit pas rester affiche.
            other_view = setup_control_center.SetupView(bot, fake_guild, 111)
            other_view.category = "moderation"
            other_view.render()
            if find_language_select(other_view) is not None:
                errors.append("le selecteur de langue reste affiche hors de la page d'accueil de +setup")

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
    print("OK: +setup rattache au vrai OfficialSetup, FR/EN persistant et selecteur de langue present dans le payload Discord de +setup")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
