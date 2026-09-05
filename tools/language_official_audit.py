#!/usr/bin/env python3
"""Audit FR/EN du Setup/Help officiels sur l'interface finale V70-V72."""
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

EXPECTED_SETUP_CATEGORIES = 10


async def run() -> int:
    errors: list[str] = []
    visible = []
    with tempfile.TemporaryDirectory(prefix="sentrix-language-official-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-language.db")

        import main
        from cogs import (
            language_runtime,
            setup_control_center,
            setup_polish_v70,
        )
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

        # La préférence de langue reste persistante dans la table historique.
        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_EN)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_EN:
            errors.append("la preference English n'est pas persistante")
        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_FR)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_FR:
            errors.append("la preference Francais n'est pas persistante")

        # Les alias FR/EN doivent rester des alias du même objet commande.
        for canonical, french in (
            ("ban", "bannir"),
            ("help", "aide"),
            ("setup", "configurer"),
            ("balance", "solde"),
        ):
            base = bot.get_command(canonical)
            if base is None:
                errors.append(f"commande canonique absente: {canonical}")
                continue
            if bot.get_command(french) is not base:
                errors.append(f"alias FR {french} ne pointe pas vers {canonical}")

        setup_command = bot.get_command("setup")
        setup_cog = bot.get_cog("SentriXSetup")
        if setup_command is None or setup_cog is None:
            errors.append("le propriétaire SentriXSetup n'est pas charge")
        elif getattr(setup_command, "cog", None) is not setup_cog:
            errors.append("+setup n'est pas rattache au Cog SentriXSetup")

        if len(setup_control_center.CATEGORIES) != EXPECTED_SETUP_CATEGORIES:
            errors.append(
                f"le setup officiel doit garder {EXPECTED_SETUP_CATEGORIES} categories: "
                f"{len(setup_control_center.CATEGORIES)}"
            )
        if "permissions" not in setup_control_center.CATEGORIES:
            errors.append("la categorie Permissions / Acces aux commandes manque")

        view_cls = setup_control_center.SetupView
        # Les marqueurs V3/langue restent le contrat backend. V70 est le propriétaire
        # visuel actuel et V72 ajoute uniquement états propres + Tickets auto-configurables.
        if not getattr(view_cls, "_sentrix_control_center_v3", False):
            errors.append("le backend Control Center V3 n'est pas installe")
        if not getattr(view_cls, "_sentrix_control_center_v3_language", False):
            errors.append("le pont FR/EN final du Control Center n'est pas installe")
        if not getattr(view_cls, "_sentrix_language_payload_guard", False):
            errors.append("le SetupView final n'est pas marque compatible langue")
        if not getattr(view_cls.render, "_sentrix_setup_ticket_v72", False):
            errors.append("le renderer final Tickets/Setup V72 n'est pas installe")
        if not getattr(bot, "_sentrix_setup_ticket_autoconfig_v72", False):
            errors.append("le runtime Tickets auto-configurable V72 n'est pas actif")

        fake_guild = SimpleNamespace(
            id=123456789,
            owner_id=1,
            default_role=SimpleNamespace(id=1234567890),
        )
        await language_runtime.set_language(bot, fake_guild.id, language_runtime.LANG_EN)
        view = view_cls(bot, fake_guild, 1)
        view.render()

        language_selects = [
            item for item in view.children if isinstance(item, OfficialLanguageSelect)
        ]
        if len(language_selects) != 1:
            errors.append(f"selecteur de langue final inattendu: {len(language_selects)}")

        # Les vieux boutons Home/Refresh/Close sont toujours interdits.
        button_labels = {
            str(getattr(item, "label", ""))
            for item in view.children
            if hasattr(item, "style")
        }
        for forbidden in ("Home", "Refresh", "Close", "Accueil", "Actualiser", "Fermer"):
            if forbidden in button_labels:
                errors.append(f"ancien bouton de navigation encore present: {forbidden}")

        # Depuis V70, le menu final est volontairement simple : Accueil + les dix pages
        # officielles. Les anciennes sous-pages techniques V3 ne sont plus des options du
        # menu principal ; V71 les ouvre depuis les contrôles de la page Sécurité.
        page_selects = [
            item for item in view.children
            if isinstance(item, setup_polish_v70.V70PageSelect)
        ]
        if len(page_selects) != 1:
            errors.append(f"menu final V70/V72 inattendu: {len(page_selects)}")
        else:
            select = page_selects[0]
            values = {str(option.value) for option in select.options}
            # dc70965 a ajoute trois sous-pages au menu principal : elles n'etaient
            # atteignables que par les controles de la page Securite, mecanisme qui
            # ne fonctionnait pas en production (page Roles — Regles & CAPTCHA
            # injoignable). Ce sont des entrees VOULUES, pas des fuites.
            sous_pages_volontaires = {"security_verification", "roles_panel", "roles_rules"}
            expected_values = (
                set(setup_control_center.CATEGORY_ORDER) | {"__home__"} | sous_pages_volontaires
            )
            missing = sorted(expected_values - values)
            unexpected = sorted(values - expected_values)
            if missing:
                errors.append("pages manquantes dans le menu final: " + ", ".join(missing))
            if unexpected:
                errors.append("pages inattendues dans le menu final: " + ", ".join(unexpected))
            labels = {str(option.label) for option in select.options}
            if "Permissions" not in labels:
                errors.append("l'option Permissions manque dans le menu final traduit")

        help_command = bot.get_command("help")
        help_cog = bot.get_cog("SentriXHelp")
        if help_command is None or help_cog is None:
            errors.append("le propriétaire SentriXHelp n'est pas charge")
        elif getattr(help_command, "cog", None) is not help_cog:
            errors.append("+help n'est pas rattache au Cog SentriXHelp")
        if help_command is not None and not getattr(help_command, "_sentrix_language_help", False):
            errors.append("le help officiel n'est pas reconnu par le moteur de langue")

        visible = [
            command for command in bot.walk_commands()
            if not getattr(command, "hidden", False)
        ]
        object_ids = [id(command) for command in visible]
        if len(object_ids) != len(set(object_ids)):
            errors.append("walk_commands contient des objets commandes dupliques")

        current = asyncio.current_task()
        pending = [
            task for task in asyncio.all_tasks()
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

    print(f"Language official audit: {len(visible)} commande(s) verifiee(s)")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s)")
        return 1
    print(
        "OK: FR/EN persistant, 10 categories, navigation V70/V72, "
        "Tickets V72, help officiel et aucun doublon"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
