"""Sonde exécutée dans un SOUS-PROCESSUS dédié par test_boot_smoke.py.

Milestone 1 (SentriX Core Reliability), priorité P0 #3 : SentriX n'avait aucun
test dédié qui boote réellement le bot complet (les 51 extensions, main.py +
les 21 ajoutées par railway_boot.py) et échoue clairement s'il ne démarre pas —
seule garantie incidente existante : tests/_boot_probe_roles_rules_subpage.py,
qui boote bien tout le runtime mais dans un but étroit (une sous-page de
/setup), pas pour vérifier le boot lui-même.

Sous-processus requis pour la même raison que cette sonde-là : les
monkeypatches idempotents posés par les cogs supposent un seul vrai boot par
processus, incompatible avec le reste de la suite pytest partagée.

Imprime un objet JSON unique sur stdout ; toute exception y apparaît sous la
clé "error" plutôt que de faire planter le sous-processus silencieusement.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _close_runtime(bot) -> None:
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


async def _boot() -> dict:
    import main as main_module
    import railway_boot  # noqa: F401 -- appends the 21 extra extensions to main.EXTENSIONS

    bot = main_module.BotAllInOne()
    await bot.db.connect()

    failed: list[dict] = []
    for extension in main_module.EXTENSIONS:
        try:
            await bot.load_extension(extension)
        except Exception as exc:
            failed.append({"extension": extension, "error": f"{type(exc).__name__}: {exc}"})

    loaded = len(main_module.EXTENSIONS) - len(failed)
    result = {
        "extensions_expected": len(main_module.EXTENSIONS),
        "extensions_loaded": loaded,
        "extensions_failed": failed,
        "commands": len(list(bot.walk_commands())),
    }

    await _close_runtime(bot)
    return result


def main() -> None:
    os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
    with tempfile.TemporaryDirectory(prefix="sentrix-boot-smoke-") as temp_dir:
        os.environ["DATABASE_PATH"] = str(Path(temp_dir) / "sentrix-boot-smoke.db")
        try:
            result = asyncio.run(_boot())
        except Exception as exc:
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}))
            return
        print(json.dumps(result))


if __name__ == "__main__":
    main()
