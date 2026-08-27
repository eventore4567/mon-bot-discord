#!/usr/bin/env python3
"""Audit FR/EN adapté aux propriétaires officiels setup/help de SentriX."""
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
    with tempfile.TemporaryDirectory(prefix="sentrix-language-official-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-language.db")

        import main
        from cogs import language_runtime, setup_control_center
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

        # La préférence de langue reste persistante dans la même table historique.
        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_EN)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_EN:
            errors.append("la preference English n'est pas persistante")
        await language_runtime.set_language(bot, 123456789, language_runtime.LANG_FR)
        if await language_runtime.get_language(bot, 123456789) != language_runtime.LANG_FR:
            errors.append("la preference Francais n'est pas persistante")

        # Les alias FR/EN restent deux noms du MEME objet commande, jamais des doublons.
        for canonical, french in (("ban", "bannir"), ("help", "aide"), ("setup", "configurer"), ("balance", "solde")):
            base = bot.get_command(canonical)
            if base is None:
                errors.append(f"commande canonique absente: {canonical}")
                continue
            translated = bot.get_command(french)
            if translated is not base:
                errors.append(f"alias FR {french} ne pointe pas vers {canonical}")

        setup_command = bot.get_command("setup")
        setup_cog = bot.get_cog("SentriXSetup")
        if setup_command is None or setup_cog is None:
            errors.append("le nouveau propriétaire SentriXSetup n'est pas charge")
        elif getattr(setup_command, "cog", None) is not setup_cog:
            errors.append("+setup n'est pas rattache au Cog SentriXSetup")

        if len(setup_control_center.CATEGORIES) != 9:
            errors.append(f"le setup officiel doit garder exactement 9 categories: {len(setup_control_center.CATEGORIES)}")
        if not getattr(setup_control_center.SetupView, "_sentrix_official_language_bridge", False):
            errors.append("le pont FR/EN n'est pas branche sur le nouveau SetupView")
        if not getattr(setup_control_center.SetupView, "_sentrix_language_payload_guard", False):
            errors.append("le nouveau SetupView n'est pas marque comme compatible langue")

        # La langue est un réglage transversal : elle ne devient PAS une dixième catégorie.
        fake_guild = SimpleNamespace(id=123456789, owner_id=1)
        await language_runtime.set_language(bot, fake_guild.id, language_runtime.LANG_EN)
        view = setup_control_center.SetupView(bot, fake_guild, 1)
        view.render()
        language_selects = [item for item in view.children if isinstance(item, OfficialLanguageSelect)]
        if len(language_selects) != 1:
            errors.append(f"selecteur de langue officiel inattendu: {len(language_selects)}")
        labels = {str(getattr(item, "label", "")) for item in view.children}
        for expected in ("Home", "Refresh", "Close"):
            if expected not in labels:
                errors.append(f"bouton anglais absent du nouveau setup: {expected}")

        category_selects = [
            item for item in view.children
            if getattr(item, "custom_id", None) != "sentrix:setup:official:language"
            and getattr(item, "options", None)
        ]
        if not category_selects or len(category_selects[0].options) != 9:
            errors.append("le menu principal ne contient plus exactement les 9 categories officielles")

        help_command = bot.get_command("help")
        help_cog = bot.get_cog("SentriXHelp")
        if help_command is None or help_cog is None:
            errors.append("le nouveau propriétaire SentriXHelp n'est pas charge")
        elif getattr(help_command, "cog", None) is not help_cog:
            errors.append("+help n'est pas rattache au Cog SentriXHelp")
        if help_command is not None and not getattr(help_command, "_sentrix_language_help", False):
            errors.append("le help officiel n'est pas reconnu par le moteur de langue")

        # Toutes les commandes visibles restent uniques malgré les alias linguistiques.
        visible = [command for command in bot.walk_commands() if not getattr(command, "hidden", False)]
        object_ids = [id(command) for command in visible]
        if len(object_ids) != len(set(object_ids)):
            errors.append("walk_commands contient des objets commandes dupliques")

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

    print(f"Language official audit: {len(visible) if 'visible' in locals() else 0} commande(s) verifiee(s)")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s)")
        return 1
    print("OK: FR/EN persistant, 9 categories setup, propriétaires officiels setup/help et aucun doublon")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
