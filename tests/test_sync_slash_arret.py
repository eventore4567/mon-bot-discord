"""Une synchro slash coupée par l'arrêt de l'instance n'est pas une panne.

Prod 26/10 19:04 : le standby, remplacé par un redéploiement, recevait
SIGTERM en pleine synchro ; « Connector is closed » sortait en ERROR avec
une pile complète, alors que l'instance suivante publiait le catalogue.
"""
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "x")

import aiohttp  # noqa: E402

import main  # noqa: E402


def test_connexion_fermee_par_l_arret():
    bot = SimpleNamespace(is_closed=lambda: False)
    erreur = aiohttp.ClientConnectionError("Connector is closed.")
    assert main.sync_interrompue_par_arret(bot, erreur) is True


def test_bot_deja_ferme():
    bot = SimpleNamespace(is_closed=lambda: True)
    assert main.sync_interrompue_par_arret(bot, RuntimeError("autre")) is True


def test_une_vraie_panne_reste_une_erreur():
    bot = SimpleNamespace(is_closed=lambda: False)
    assert main.sync_interrompue_par_arret(bot, RuntimeError("400 Bad Request")) is False
