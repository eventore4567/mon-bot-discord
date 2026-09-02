"""Le registre reel des commandes, apres un demarrage complet.

Charge le bot comme Railway le fait, puis interroge le registre obtenu. C'est
ainsi qu'on a vu qu'un alias francais (« reinitialiser-logs-all ») executait
encore l'ANCIENNE implementation pendant que « reset-logs-all » executait la
nouvelle.

Ce demarrage patche des objets globaux de discord.py : il doit tourner dans son
PROPRE processus, jamais au milieu d'une suite de tests.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys
import tempfile
from collections import Counter

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))


async def _charger():
    import config

    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "registre.db")
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

    echecs = []
    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=30)
        except Exception as erreur:
            echecs.append(f"{extension}: {type(erreur).__name__}: {erreur}")
    return bot, extensions, echecs


def main() -> int:
    from utils import access_matrix

    bot, extensions, echecs = asyncio.run(_charger())
    problemes: list[str] = []

    if echecs:
        problemes += [f"EXTENSION EN ECHEC   {e}" for e in echecs]

    commandes = list(bot.walk_commands())
    if len(commandes) < 500:
        problemes.append(
            f"REGISTRE TROP PETIT   {len(commandes)} commandes — chargement incomplet"
        )

    compte = Counter(c.qualified_name for c in commandes)
    for nom, k in compte.items():
        if k > 1:
            problemes.append(f"NOM DUPLIQUE   {nom} ({k} fois)")

    vivantes = {id(c) for c in commandes}
    for cle, cmd in bot.all_commands.items():
        if id(cmd) not in vivantes:
            problemes.append(f"ALIAS ORPHELIN   {cle} designe une commande deregistree")

    # Aucun parametre interne de wrapper ne doit subsister une fois TOUTES les
    # extensions chargees : ces noms se retrouveraient dans la signature des
    # commandes slash, donc sous les yeux des utilisateurs.
    internes = {"self", "ctx", "context", "interaction", "bot", "original", "kwargs", "args"}
    for commande in commandes:
        try:
            parametres = list(commande.clean_params)
        except Exception:
            problemes.append(f"PARAMETRES ILLISIBLES   {commande.qualified_name}")
            continue
        pollues = [p for p in parametres if p.casefold().lstrip("_") in internes]
        if pollues:
            problemes.append(
                f"PARAMETRE INTERNE EXPOSE   {commande.qualified_name} → {pollues}"
            )

    inconnues = sorted({c.name.lower() for c in bot.commands} - access_matrix.KNOWN_COMMANDS)
    problemes += [f"SANS POLITIQUE D'ACCES   {n}" for n in inconnues]

    # add_check() capture l'objet au moment de l'appel : si le guard
    # s'installait apres, c'est l'ancienne fonction qui serait enregistree.
    if not getattr(bot.global_permission_check, "_sentrix_permission_guard", False):
        problemes.append("GARDE PREFIXE   ce n'est pas le guard qui est installe")
    if getattr(bot.tree.interaction_check, "_sentrix_previous_tree_check", None) is None:
        problemes.append("GARDE SLASH   interaction_check non installe")

    print(f"extensions : {len(extensions)}   commandes : {len(commandes)}")
    if not problemes:
        print("OK : registre coherent.")
        return 0
    print(f"\nECHEC : {len(problemes)} probleme(s)\n")
    for p in sorted(set(problemes)):
        print("   " + p)
    return 1


if __name__ == "__main__":
    code = main()
    # Le bot laisse des taches asyncio et des boucles de fond vivantes : une
    # sortie normale attendrait indefiniment. Ce processus n'a plus rien a
    # faire, on le termine franchement.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
