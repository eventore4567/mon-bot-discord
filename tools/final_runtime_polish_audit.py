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
            if not getattr(help_command, "_sentrix_help_root_only", False):
                errors.append("+help n'a pas le marqueur root-only")
            if getattr(help_command, "clean_params", None):
                errors.append(f"+help expose encore des paramètres: {list(help_command.clean_params)}")
            signature = str(getattr(help_command, "signature", "") or "").strip()
            if signature:
                errors.append(f"+help affiche encore une signature publique: {signature!r}")
            callback_params = list(inspect.signature(help_command.callback).parameters)
            if callback_params != ["cog", "ctx"]:
                errors.append(f"callback +help inattendu: {callback_params}")

        for language in (language_runtime.LANG_FR, language_runtime.LANG_EN):
            home = help_clean_style._help_home(bot, None, "+", True, language)
            nav = "\n".join(str(field.value) for field in home.fields if str(field.name).upper() == "NAVIGATION")
            if "+help ban" in nav or "+aide bannir" in nav:
                errors.append(f"ancien exemple +help <commande> encore visible en {language}")
            if "Aucun nom de commande" not in nav and "No command name" not in nav:
                errors.append(f"navigation root-only absente en {language}")

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
