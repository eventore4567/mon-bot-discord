"""Un incident base de données ne doit jamais bloquer les commandes de TOUT
le monde SAUF le propriétaire.

global_blacklist_check et global_cooldown_check court-circuitent d'abord pour
le créateur principal (ctx.author.id == PRIMARY_CREATOR_ID), puis appellent
self.db.is_bot_creator(...) pour tout le monde d'autre — SANS protection.
Un verrou SQLite ("database is locked") y faisait alors lever une exception
AVANT la commande elle-même : le propriétaire ne le voyait jamais (son
raccourci l'esquive), mais n'importe quel autre membre en était bloqué.
C'est un candidat direct pour « seul le propriétaire arrive à utiliser les
commandes ».
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import main as bot_main  # noqa: E402


class _DBExplose:
    async def is_bot_creator(self, user_id):
        raise RuntimeError("database is locked")


class _Auteur:
    def __init__(self, uid):
        self.id = uid


def _bot_minimal():
    bot = bot_main.BotAllInOne.__new__(bot_main.BotAllInOne)
    bot.db = _DBExplose()
    bot.blacklist_cache = {}
    return bot


def test_le_repli_ne_leve_jamais_sur_un_incident_db():
    bot = _bot_minimal()
    resultat = asyncio.run(bot._is_extra_bot_creator(999888777))
    assert resultat is False


def test_blacklist_check_survit_a_un_incident_db_pour_un_membre_normal():
    bot = _bot_minimal()

    class Ctx:
        author = _Auteur(999888777)

    autorise = asyncio.run(bot_main.BotAllInOne.global_blacklist_check(bot, Ctx()))
    assert autorise is True


def test_cooldown_check_survit_a_un_incident_db_pour_un_membre_normal():
    import discord.ext.commands as commands

    bot = _bot_minimal()
    bot._cooldown_bucket = commands.CooldownMapping.from_cooldown(
        1000, 60.0, commands.BucketType.user
    )

    class _Message:
        author = _Auteur(999888777)

    class Ctx:
        author = _Auteur(999888777)
        message = _Message()
        interaction = None

    autorise = asyncio.run(bot_main.BotAllInOne.global_cooldown_check(bot, Ctx()))
    assert autorise is True
