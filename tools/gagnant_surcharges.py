"""Pour chaque commande surchargee, QUI gagne — et rend-il le nouveau visuel ?

Une commande peut etre redefinie par plusieurs couches successives. Lire le cog
d'origine ne dit alors rien de ce que l'utilisateur voit : c'est la DERNIERE
couche qui repond. +ping et +clear rendaient ainsi l'ancien embed alors que
leur cog etait migre depuis longtemps.

On charge donc le bot comme Railway le fait, et on demande a chaque commande
quel module porte finalement son callback.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import pathlib
import re
import sys
import tempfile

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

COMPOSE = ("panels.envoyer", "sx_panels.envoyer", "panels.editer", "sx_panels.editer")


async def _charger():
    import config

    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "gagnants.db")
    import main as bot_main

    bot = bot_main.BotAllInOne()
    await bot.db.connect()
    extensions = list(bot_main.EXTENSIONS)
    source = (RACINE / "railway_boot.py").read_text(encoding="utf-8")
    for module in re.findall(
        r'bot_main\.EXTENSIONS\.append\("(cogs\.[a-z0-9_]+)"\)', source
    ):
        if module not in extensions:
            extensions.append(module)
    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=30)
        except Exception:
            pass
    return bot


def main() -> int:
    logging.disable(logging.CRITICAL)
    bot = asyncio.run(_charger())

    surcharges = set()
    for chemin in sorted(RACINE.glob("cogs/*.py")) + sorted(RACINE.glob("utils/*.py")):
        texte = chemin.read_text(encoding="utf-8")
        for m in re.finditer(r'get_command\(\s*["\']([^"\']+)["\']', texte):
            surcharges.add(m.group(1))

    lignes: list[str] = []
    non_composees: list[str] = []
    for nom in sorted(surcharges):
        commande = bot.get_command(nom)
        if commande is None:
            continue
        rappel = getattr(commande, "callback", None)
        module = getattr(rappel, "__module__", "?")
        try:
            source = inspect.getsource(rappel)
        except Exception:
            source = ""
        compose = any(marque in source for marque in COMPOSE)
        lignes.append(f"  {nom:24} {module:42} {'panneau' if compose else 'AUTRE'}")
        if not compose:
            non_composees.append(f"{nom} → {module}")

    print(f"{len(lignes)} commande(s) susceptibles d'etre surchargees\n")
    print("\n".join(lignes))
    if non_composees:
        print(f"\n{len(non_composees)} sans appel compose visible dans le callback gagnant :")
        for n in non_composees:
            print("   " + n)
        print("\n(un callback peut deleguer : verifier avec tools/verif_execution.py)")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
