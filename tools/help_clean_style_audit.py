#!/usr/bin/env python3
"""Audit runtime du style final de +help.

Le test ne se connecte jamais a Discord. Il charge le bot comme la production puis verifie
que le rendu FR/EN, les categories, les boutons et les pages de commandes ne contiennent
plus d'emoji decoratif.
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


def _strings_from_embed(embed):
    yield embed.title
    yield embed.description
    for field in embed.fields:
        yield field.name
        yield field.value
    if embed.footer:
        yield embed.footer.text


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-help-style-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "help-style.db")

        import main
        from cogs import help_clean_style, language_runtime

        bot = main.BotAllInOne()
        await bot.db.connect()

        loaded = 0
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded += 1
            except Exception as exc:
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")

        bot._prune_redundant_commands()

        help_command = bot.get_command("help")
        if help_command is None:
            errors.append("commande +help absente")
        else:
            if not getattr(help_command, "_sentrix_help_clean_v8", False):
                errors.append("marqueur V8 absent sur +help")
            if not getattr(help_command.callback, "_sentrix_help_clean_v8", False):
                errors.append("callback final V8 non lie a +help")

        for language in (language_runtime.LANG_FR, language_runtime.LANG_EN):
            home = language_runtime._help_home(bot, None, "+", True, language)
            if help_clean_style._embed_has_emoji(home):
                errors.append(f"emoji detecte dans l'accueil {language}")
            expected_prefix = "SENTRIX /"
            if not str(home.title or "").startswith(expected_prefix):
                errors.append(f"titre accueil {language} hors style V8: {home.title!r}")

            view = language_runtime.LanguageHelpHomeView(bot, "+", True, language, 123)
            for child in view.children:
                if getattr(child, "emoji", None) is not None:
                    errors.append(f"emoji de composant accueil {language}: {child.emoji!r}")
                label = getattr(child, "label", None)
                placeholder = getattr(child, "placeholder", None)
                if help_clean_style._text_has_emoji(label) or help_clean_style._text_has_emoji(placeholder):
                    errors.append(f"emoji dans texte composant accueil {language}")
                for option in getattr(child, "options", []) or []:
                    if getattr(option, "emoji", None) is not None:
                        errors.append(f"emoji option menu {language}: {option.emoji!r}")
                    if help_clean_style._text_has_emoji(option.label) or help_clean_style._text_has_emoji(option.description):
                        errors.append(f"emoji texte option menu {language}: {option.label!r}")

            entries = language_runtime._help_entries(bot, True)
            if not entries:
                errors.append(f"aucune categorie visible en {language}")
            else:
                category, commands_list = entries[0]
                pages = language_runtime._build_category_pages(bot, "+", language, category, commands_list)
                if not pages:
                    errors.append(f"aucune page categorie en {language}")
                for page in pages:
                    if help_clean_style._embed_has_emoji(page):
                        errors.append(f"emoji detecte dans page categorie {language}")
                        break

                pages_view = language_runtime.LanguageHelpPagesView(
                    bot, "+", True, language, 123, pages, home
                )
                for child in pages_view.children:
                    if getattr(child, "emoji", None) is not None:
                        errors.append(f"emoji de composant page {language}: {child.emoji!r}")
                    if help_clean_style._text_has_emoji(getattr(child, "label", None)):
                        errors.append(f"emoji dans label composant page {language}")

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

    print(f"Help style audit: {loaded}/{len(main.EXTENSIONS)} extensions chargees")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s) de style +help")
        return 1

    print("OK: +help V8 FR/EN, categories, commandes et composants sans emoji")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
