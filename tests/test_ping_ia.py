"""L'IA peut mentionner quelqu'un, avec une limite (23/11/2026).

Capture : « @ un mec au hasard pls » → « je peux pas ping au hasard » ;
« vzi @ vortex » → « je peux pas ping VortexV1 directement ». Demande : tout le
monde peut le demander, mais avec une limite : un seul membre, jamais
@everyone, @here ni un rôle, une demande par minute et par membre.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from utils import ai_actions  # noqa: E402


@pytest.mark.parametrize(("phrase", "cible"), [
    ("@ un mec au hasard pls", "__random__"),
    ("ping quelqu un au hasard", "__random__"),
    ("vzi @ vortex", "vortex"),
    ("ping vortex", "vortex"),
    ("mentionne VortexV1", "VortexV1"),
    ("tag @vortex stp", "vortex"),
])
def test_une_demande_de_ping_est_comprise(phrase, cible):
    action = ai_actions.local_parse(phrase)
    assert action is not None and action.intent == "member.ping", phrase
    assert action.slots == {"target": cible}
    assert ai_actions.looks_action_request(phrase), "la porte du routeur doit la laisser passer"


@pytest.mark.parametrize("phrase", [
    "@everyone", "ping <@&123456789012345678>", "le ping est élevé", "j ai été ping",
    "appelle moi demain", "tagué par lui",
])
def test_pas_de_ping_par_erreur_ni_de_masse(phrase):
    action = ai_actions.local_parse(phrase)
    assert action is None or action.intent != "member.ping", (phrase, action)


def _cog():
    from cogs.ai import Ai

    cog = Ai.__new__(Ai)
    return cog


def _message(envois):
    canal = SimpleNamespace(send=AsyncMock(side_effect=lambda *a, **k: envois.append((a, k))))
    return SimpleNamespace(
        guild=SimpleNamespace(id=1, name="S", owner_id=9, me=SimpleNamespace(
            guild_permissions=SimpleNamespace(send_messages=True))),
        author=SimpleNamespace(id=42, display_name="Jay"),
        channel=canal,
        reply=AsyncMock(side_effect=lambda texte, **_: envois.append(((texte,), {}))),
    )


def test_le_ping_ne_mentionne_que_le_membre_vise_puis_respecte_la_limite():
    envois = []
    cog, message = _cog(), _message(envois)
    vortex = discord.Object(id=7)
    vortex.mention, vortex.bot = "<@7>", False
    action = ai_actions.ParsedAction("member.ping", {"target": "vortex"}, 99, "local")

    asyncio.run(cog._execute_native_action(message, action, member=vortex))
    (texte,), options = envois[0]
    assert texte.startswith("<@7>")
    mentions = options["allowed_mentions"]
    assert mentions.everyone is False and mentions.roles is False
    assert [u.id for u in mentions.users] == [7], "seul le membre visé est notifié"

    asyncio.run(cog._execute_native_action(message, action, member=vortex))
    (refus,), _ = envois[1]
    assert "Doucement" in refus, "une seconde demande dans la minute est refusée"
    assert len([e for e in envois if e[0] and str(e[0][0]).startswith("<@")]) == 1


def test_un_bot_n_est_jamais_mentionne():
    envois = []
    cog, message = _cog(), _message(envois)
    bot = discord.Object(id=8)
    bot.mention, bot.bot = "<@8>", True
    asyncio.run(cog._execute_native_action(
        message, ai_actions.ParsedAction("member.ping", {"target": "bot"}, 99, "local"), member=bot,
    ))
    assert "bot" in envois[0][0][0] and not any(str(e[0][0]).startswith("<@8>") for e in envois)


def test_au_hasard_choisit_un_humain_qui_voit_le_salon():
    from cogs.ai import Ai

    def membre(i, bot=False, voit=True):
        m = SimpleNamespace(id=i, bot=bot)
        m._voit = voit
        return m

    auteur, humain, robot, aveugle = membre(42), membre(1), membre(2, bot=True), membre(3, voit=False)
    canal = SimpleNamespace(permissions_for=lambda m: SimpleNamespace(view_channel=m._voit))
    message = SimpleNamespace(guild=SimpleNamespace(members=[auteur, humain, robot, aveugle]),
                              author=auteur, channel=canal)
    for _ in range(20):
        assert Ai._membre_au_hasard(message) is humain


@pytest.mark.parametrize("phrase", ["vzi @ vortex", "@ un mec au hasard pls"])
def test_le_vrai_point_d_entree_atteint_le_ping(phrase):
    from cogs.ai import Ai

    cog = Ai.__new__(Ai)
    cog._take_pending = lambda message: None
    cog._handle_parsed_action = AsyncMock(return_value=True)
    message = SimpleNamespace(guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=2), author=SimpleNamespace(id=42))
    assert asyncio.run(cog._invoke_natural_command(message, phrase, "+")) is True
    assert cog._handle_parsed_action.await_args.args[1].intent == "member.ping"
