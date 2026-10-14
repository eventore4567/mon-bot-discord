"""Les noms courts annoncés doivent répondre.

Mesuré le 2026-10-14 par tools/command_sweep.py — quatre commandes
marquées « fragile », et les mêmes quatre produisant 50 « refus
silencieux » dans tools/permission_audit_sweep.py :

    +perms     statut=fragile replies=0 http=0 ms=401
    +quar      statut=fragile replies=0 http=0 ms=401
    +unquar    statut=fragile replies=0 http=0 ms=402
    +roleload  statut=fragile replies=0 http=0 ms=402

Zéro appel HTTP : le corps ne tournait jamais. La table
``SHORT_COMMAND_NAMES`` de cogs/command_catalog_cleanup publie ces noms
dans le catalogue, mais aucune commande ne les portait. La preuve par
l'inverse : les noms courts qui fonctionnaient (``+backup``,
``+restore``, ``+lockdown``) sont précisément ceux définis en dur.

Un membre lisait donc un nom dans l'aide et n'obtenait rien en le tapant.
"""
from __future__ import annotations

import asyncio
import logging
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest
from discord.ext import commands

from cogs.command_catalog_cleanup import SHORT_COMMAND_NAMES


def _bot_avec_securite() -> commands.Bot:
    logging.disable(logging.CRITICAL)
    try:
        intents = discord.Intents.default()
        intents.message_content = True
        bot = commands.Bot(command_prefix="+", intents=intents)
        asyncio.run(bot.load_extension("cogs.security_tools"))
        return bot
    finally:
        logging.disable(logging.NOTSET)


_BOT = _bot_avec_securite()

# Trois noms courts de la table sont servis par d'autres cogs et
# fonctionnaient déjà : +backup, +restore (cogs/security_command_center) et
# +lockdown (cogs/sentrix_ultimate). Le balayage les donne « ok ». Ce test
# couvre donc les commandes dont security_tools est bien le propriétaire —
# celles qui, elles, ne répondaient pas.
SERVIS_AILLEURS = {"backup", "restore", "lockdown", "unlockdown"}
PAIRES = {
    long: court
    for long, court in SHORT_COMMAND_NAMES.items()
    if _BOT.get_command(long) is not None and court not in SERVIS_AILLEURS
}


def test_la_table_de_renommage_couvre_bien_security_tools():
    assert PAIRES, "aucune commande de la table n'est portée par security_tools"


@pytest.mark.parametrize("long,court", sorted(PAIRES.items()))
def test_le_nom_court_annonce_resout(long, court):
    commande = _BOT.get_command(court)
    assert commande is not None, f"+{court} est publié dans le catalogue mais n'existe pas"
    assert commande.qualified_name == long, (
        f"+{court} devrait mener à {long}, il mène à {commande.qualified_name}"
    )


@pytest.mark.parametrize("long", sorted(PAIRES))
def test_le_nom_long_continue_de_fonctionner(long):
    """Ajouter un alias ne doit retirer aucun nom existant."""
    assert _BOT.get_command(long) is not None


def test_aucune_collision_n_a_tue_le_cog():
    """Un nom en double fait échouer le chargement et emporte tout le cog."""
    cog = _BOT.get_cog("Security")
    assert cog is not None, "le cog Security n'est pas chargé"
    noms = [c.qualified_name for c in cog.get_commands()]
    assert len(noms) == len(set(noms))
