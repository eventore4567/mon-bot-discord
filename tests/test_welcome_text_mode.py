"""Bienvenue / Départs : mode « message simple » (choisi depuis le dashboard).

Le mode par défaut reste l'encadré historique ; en mode ``text`` le bot envoie le texte seul,
avec la mention en tête hors test. Le champ Membres de l'encadré est correctement accordé.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import setup_v2_completion  # noqa: E402
from tests.test_welcome_single_source_of_truth import _FakeBot, _fake_channel  # noqa: E402


def _member(guild):
    member = Mock(spec=discord.Member)
    member.id = 111
    member.mention = "<@111>"
    member.display_name = "Jayden"
    member.name = "jayden"
    member.guild = guild
    member.display_avatar = Mock(url="https://cdn.discordapp.com/embed/avatars/0.png")
    return member


def _guild(channel, members=57):
    guild = Mock(spec=discord.Guild)
    guild.id = 900
    guild.name = "Le Repaire"
    guild.member_count = members
    guild.get_channel = Mock(return_value=channel)
    guild.me = Mock()
    return guild


def test_text_mode_sends_plain_content_without_embed():
    channel = _fake_channel()
    guild = _guild(channel)
    bot = _FakeBot({"welcome_channel": 42, "welcome_message": "Bienvenue {member} sur {server} !"}, {"title": "x", "show_avatar": 1, "show_member_count": 1, "mode": "text"})

    ok, message = asyncio.run(setup_v2_completion._send_welcome(bot, _member(guild), test=False))
    assert ok, message
    kwargs = channel.send.call_args.kwargs
    assert "embed" not in kwargs
    assert kwargs["content"] == "<@111>\nBienvenue <@111> sur Le Repaire !"

    channel.send.reset_mock()
    ok, _ = asyncio.run(setup_v2_completion._send_welcome(bot, _member(guild), test=True))
    assert ok
    assert channel.send.call_args.kwargs["content"] == "Bienvenue <@111> sur Le Repaire !"


def test_default_and_legacy_rows_stay_in_embed_mode():
    channel = _fake_channel()
    guild = _guild(channel, members=1)
    # Ligne historique sans colonne mode → encadré, comme avant.
    bot = _FakeBot({"welcome_channel": 42, "welcome_message": "Salut {member}"}, {"title": "Titre", "show_avatar": 1, "show_member_count": 1})
    ok, _ = asyncio.run(setup_v2_completion._send_welcome(bot, _member(guild), test=False))
    assert ok
    embed = channel.send.call_args.kwargs["embed"]
    assert embed.title == "Titre"
    members_field = next(f for f in embed.fields if f.name == "Membres")
    assert members_field.value == "1 membre"


def test_goodbye_text_mode_sends_plain_content():
    channel = _fake_channel()
    guild = _guild(channel)
    # Le mode des départs est indépendant de celui de la bienvenue.
    bot = _FakeBot({"goodbye_channel": 42, "goodbye_message": "{username} a quitté {server}."}, {"title": "x", "show_avatar": 1, "show_member_count": 1, "mode": "embed", "goodbye_mode": "text"})
    result = asyncio.run(setup_v2_completion._send_goodbye(bot, _member(guild)))
    assert result is channel
    kwargs = channel.send.call_args.kwargs
    assert kwargs["content"] == "jayden a quitté Le Repaire."
    assert "embed" not in kwargs
