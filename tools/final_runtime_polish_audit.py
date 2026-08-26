#!/usr/bin/env python3
"""Audit du correctif final +help et Canary externe."""
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
    with tempfile.TemporaryDirectory(prefix="sentrix-final-polish-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "polish.db")
        os.environ.pop("SENTRIX_CANARY_MODE", None)
        os.environ.pop("CANARY_GUILD_ID", None)

        import main
        from cogs import help_clean_style, language_runtime, production_readiness_runtime

        bot = main.BotAllInOne()
        await bot.db.connect()
        for extension in main.EXTENSIONS:
            await bot.load_extension(extension)
        bot._prune_redundant_commands()

        help_command = bot.get_command("help")
        if help_command is None:
            errors.append("+help absent")
        else:
            if getattr(bot, "_sentrix_help_owner", None) != "cogs.help":
                errors.append("+help n'appartient pas au propriétaire officiel")
            if list(getattr(help_command, "checks", ())):
                errors.append("+help conserve un verrou local")

        help_source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")
        for marker in ("class HelpView", "class SearchModal", "class CategorySelect"):
            if marker not in help_source:
                errors.append(f"navigation officielle incomplète: {marker}")

        if not getattr(production_readiness_runtime.audit_guild_configuration, "_sentrix_external_canary", False):
            errors.append("audit readiness n'est pas patché pour Canary externe")

        root = bot.get_command("security")
        infra = root.get_command("infra") if root else None
        if infra is None or not getattr(infra, "_sentrix_external_canary", False):
            errors.append("+security infra n'est pas patché pour Canary externe")

        canary_boot = (ROOT / "railway_canary_boot.py").read_text(encoding="utf-8")
        if "bot._persistence_check_done = True" not in canary_boot:
            errors.append("le Canary peut encore envoyer le faux MP de perte de persistance")

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await bot.db.close()

    for error in errors:
        print("[ERROR]", error)
    if errors:
        print(f"ECHEC: {len(errors)} problème(s)")
        return 1
    print("OK: +help sans argument public, Canary externe sans faux malus et sans MP de persistance")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
