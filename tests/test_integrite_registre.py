"""Le registre reel des commandes, apres un demarrage complet.

Les tests unitaires verifient des commandes choisies. Celui-ci part de
l'inverse : il charge le bot exactement comme Railway le fait, puis interroge
le registre obtenu. C'est ainsi qu'on a vu qu'un alias francais
(« reinitialiser-logs-all ») executait encore l'ANCIENNE implementation
pendant que « reset-logs-all » executait la nouvelle.

Un seul demarrage sert toutes les verifications : il coute une quarantaine de
secondes.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys
import tempfile
from collections import Counter

import pytest

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))


@pytest.fixture(scope="module")
def bot_charge():
    import config

    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "registre.db")
    import main as bot_main

    async def demarrer():
        bot = bot_main.BotAllInOne()
        await bot.db.connect()
        extensions = list(bot_main.EXTENSIONS)
        # railway_boot ajoute des extensions APRES la liste de main.py.
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

    boucle = asyncio.new_event_loop()
    bot, extensions, echecs = boucle.run_until_complete(demarrer())
    yield bot, extensions, echecs
    boucle.run_until_complete(bot.db.close())
    boucle.close()


def test_toutes_les_extensions_chargent(bot_charge):
    _, extensions, echecs = bot_charge
    assert not echecs, "\n".join(echecs)
    assert len(extensions) >= 45


def test_le_bot_charge_bien_toutes_ses_commandes(bot_charge):
    """Garde-fou du harnais : si le chargement echouait en silence, tous les
    tests de ce fichier passeraient sur un registre vide."""
    bot, _, _ = bot_charge
    assert len(list(bot.walk_commands())) >= 500


def test_aucun_nom_de_commande_duplique(bot_charge):
    """Deux commandes du meme nom : l'une des deux est injoignable, et on ne
    sait pas laquelle sans lire l'ordre de chargement."""
    bot, _, _ = bot_charge
    compte = Counter(c.qualified_name for c in bot.walk_commands())
    doublons = {n: k for n, k in compte.items() if k > 1}
    assert not doublons, f"noms dupliques : {doublons}"


def test_aucun_alias_ne_pointe_vers_une_commande_deregistree(bot_charge):
    """Le piege exact de reinitialiser-logs-all : un alias survivant a la
    commande qu'il designait, donc deux comportements pour un meme nom."""
    bot, _, _ = bot_charge
    vivantes = {id(c) for c in bot.walk_commands()}
    orphelins = [
        cle for cle, cmd in bot.all_commands.items() if id(cmd) not in vivantes
    ]
    assert not orphelins, f"alias orphelins : {sorted(orphelins)}"


def test_chaque_commande_a_une_politique_d_acces(bot_charge):
    from utils import access_matrix

    bot, _, _ = bot_charge
    enregistrees = {c.name.lower() for c in bot.commands}
    inconnues = sorted(enregistrees - access_matrix.KNOWN_COMMANDS)
    assert not inconnues, f"commandes sans politique d'acces : {inconnues}"


def test_la_garde_de_permissions_est_bien_celle_installee(bot_charge):
    """add_check() capture l'objet au moment de l'appel : si le guard
    s'installait APRES, c'est l'ancienne fonction qui serait enregistree."""
    bot, _, _ = bot_charge
    assert getattr(bot.global_permission_check, "_sentrix_permission_guard", False)
    assert getattr(bot.tree.interaction_check, "_sentrix_previous_tree_check", None) is not None
