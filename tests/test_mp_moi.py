"""« mp moi » : SentriX écrit en privé, et la conversation y continue 24 h.

22/11/2026, capture : « mp moi » → « Je peux pas envoyer de MP moi-même ici ».
Demande : « genre ça MP la personne en lui disant "tu voulais me dire quoi" ».

Le privé avait été fermé le 20/11 (« Je ne discute qu'en serveur »). Il ne
s'ouvre que pour qui l'a demandé lui-même dans un serveur, pendant 24 h. Écrire
à un AUTRE membre est réservé au staff, et le message dit qui l'envoie.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from utils import ai_actions, mp_ouvertes  # noqa: E402


@pytest.mark.parametrize("phrase", [
    "mp moi", "stp mp moi", "dm moi stp", "écris-moi en privé", "viens en mp",
    "tu peux me mp ?", "tu peux m'écrire en mp",
])
def test_mp_moi_est_compris_et_vise_l_auteur(phrase):
    action = ai_actions.local_parse(phrase)
    assert action is not None and action.intent == "member.dm", phrase
    assert action.slots["target"] == "__self__"


@pytest.mark.parametrize("phrase", ["il m a mp moi aussi", "je suis en mp avec lui"])
def test_parler_de_mp_n_envoie_rien(phrase):
    action = ai_actions.local_parse(phrase)
    assert action is None or action.intent != "member.dm"


def test_mp_a_un_autre_membre_garde_la_cible_et_le_texte():
    action = ai_actions.local_parse("mp <@123456789012345678> : la réunion est à 20 h")
    assert action.intent == "member.dm"
    assert action.slots == {"target": "<@123456789012345678>", "text": "la réunion est à 20 h"}


class _Base:
    """Base minimale au comportement de SQLite pour cette table."""

    def __init__(self):
        self.lignes = {}

    async def execute(self, sql, params=()):
        if sql.lstrip().startswith("INSERT"):
            user_id, guild_id, fin = params
            self.lignes[user_id] = {"expire_at": fin, "guild_id": guild_id}

    async def fetchone(self, sql, params=()):
        return self.lignes.get(params[0])


def test_la_fenetre_dure_24_heures(tmp_path):
    """Sur la VRAIE base SQLite : l'upsert et la lecture doivent s'y comporter ainsi."""
    from database.db import Database

    async def scenario():
        db = Database(str(tmp_path / "mp.db"))
        await db.connect()
        try:
            bot = SimpleNamespace(db=db)
            await mp_ouvertes.ouvrir(bot, 42, 1, maintenant=1000)
            await mp_ouvertes.ouvrir(bot, 42, 1, maintenant=2000)  # prolongée, pas dupliquée
            return (
                await mp_ouvertes.est_ouverte(bot, 42, maintenant=2000 + 3600),
                await mp_ouvertes.est_ouverte(bot, 42, maintenant=2000 + mp_ouvertes.DUREE_S + 1),
                await mp_ouvertes.est_ouverte(bot, 7, maintenant=2000),
            )
        finally:
            await db.close()

    ouverte, expiree, autre = asyncio.run(scenario())
    assert ouverte and not expiree and not autre


def test_une_base_illisible_garde_le_prive_ferme():
    class Cassee:
        async def execute(self, *a, **k):
            raise RuntimeError("base indisponible")

    assert not asyncio.run(mp_ouvertes.est_ouverte(SimpleNamespace(db=Cassee()), 42))


def _executer(action, *, actor_perms=False, cible=None):
    from cogs.ai import Ai

    reponses = []
    guild = SimpleNamespace(id=1, name="Serveur", owner_id=999)
    auteur = SimpleNamespace(
        id=42, display_name="Jay", mention="<@42>", send=AsyncMock(),
        guild_permissions=SimpleNamespace(moderate_members=actor_perms),
    )
    message = SimpleNamespace(
        guild=guild, author=auteur,
        reply=AsyncMock(side_effect=lambda texte, **_: reponses.append(texte)),
    )
    cog = Ai.__new__(Ai)
    cog.bot = SimpleNamespace(db=_Base())

    async def reply(texte):
        reponses.append(texte)

    membre = cible if cible is not None else auteur
    asyncio.run(cog._message_prive(message, action, membre, reply))
    return cog, auteur, reponses


def test_mp_moi_ecrit_a_l_auteur_et_ouvre_la_conversation():
    action = ai_actions.ParsedAction("member.dm", {"target": "__self__"}, 99, "local")
    cog, auteur, reponses = _executer(action)
    auteur.send.assert_awaited_once()
    assert "Vous vouliez me dire quoi" in auteur.send.await_args.args[0]
    assert asyncio.run(mp_ouvertes.est_ouverte(cog.bot, 42))
    assert "écrit en message privé" in reponses[0]


def test_ecrire_a_un_autre_membre_exige_moderer_les_membres():
    bob = SimpleNamespace(id=7, bot=False, mention="<@7>", send=AsyncMock())
    action = ai_actions.ParsedAction("member.dm", {"target": "<@7>", "text": "salut"}, 99, "local")
    _cog, _auteur, reponses = _executer(action, cible=bob)
    bob.send.assert_not_awaited()
    assert "Modérer les membres" in reponses[0]


def test_le_staff_ecrit_a_un_membre_en_signant_le_message():
    bob = SimpleNamespace(id=7, bot=False, mention="<@7>", send=AsyncMock())
    action = ai_actions.ParsedAction("member.dm", {"target": "<@7>", "text": "réunion à 20 h"}, 99, "local")
    cog, _auteur, reponses = _executer(action, actor_perms=True, cible=bob)
    envoye = bob.send.await_args.args[0]
    assert "Message de Jay" in envoye and "réunion à 20 h" in envoye
    assert not asyncio.run(mp_ouvertes.est_ouverte(cog.bot, 7)), "écrire à Bob n'ouvre pas SON privé"


def test_mp_fermes_le_dit_clairement():
    action = ai_actions.ParsedAction("member.dm", {"target": "__self__"}, 99, "local")
    from cogs.ai import Ai

    reponses = []
    auteur = SimpleNamespace(
        id=42, display_name="Jay", send=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason="x"), "fermé")),
        guild_permissions=SimpleNamespace(moderate_members=False),
    )
    message = SimpleNamespace(guild=SimpleNamespace(id=1, name="S", owner_id=9), author=auteur)
    cog = Ai.__new__(Ai)
    cog.bot = SimpleNamespace(db=_Base())

    async def reply(texte):
        reponses.append(texte)

    asyncio.run(cog._message_prive(message, action, auteur, reply))
    assert "messages privés sont fermés" in reponses[0]
    assert not asyncio.run(mp_ouvertes.est_ouverte(cog.bot, 42))


def test_le_point_d_entree_natif_refuse_aussi_l_ecriture_a_autrui():
    """Le chemin réellement emprunté par le routeur : _execute_native_action."""
    from cogs.ai import Ai

    reponses = []
    bob = SimpleNamespace(id=7, bot=False, mention="<@7>", send=AsyncMock())
    auteur = SimpleNamespace(
        id=42, display_name="Jay", send=AsyncMock(),
        guild_permissions=SimpleNamespace(moderate_members=False),
    )
    message = SimpleNamespace(
        guild=SimpleNamespace(id=1, name="S", owner_id=9, me=SimpleNamespace()),
        author=auteur,
        reply=AsyncMock(side_effect=lambda texte, **_: reponses.append(texte)),
    )
    cog = Ai.__new__(Ai)
    cog.bot = SimpleNamespace(db=_Base())
    action = ai_actions.ParsedAction("member.dm", {"target": "<@7>", "text": "salut"}, 99, "local")
    asyncio.run(cog._execute_native_action(message, action, member=bob))
    bob.send.assert_not_awaited()
    assert "Modérer les membres" in reponses[0]
