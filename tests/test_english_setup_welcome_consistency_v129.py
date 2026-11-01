"""Régressions EN cohérent : /setup, bienvenue, carte PNG, cache Railway.

Pas de traduction du nom du serveur et pas de réécriture des textes
personnalisés par l'administrateur.
"""
from __future__ import annotations

import io
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest
from PIL import Image

from cogs import language_runtime, setup_v2_completion
from utils.member_event_cards import build_member_event_card


@pytest.mark.asyncio
async def test_language_cache_is_refreshed_across_two_railway_processes():
    state = {"language": "fr"}
    async def fetchone(_sql, params=()):
        return {"language": state["language"]}
    db = SimpleNamespace(execute=AsyncMock(), fetchone=AsyncMock(side_effect=fetchone))
    bot = SimpleNamespace(db=db)

    assert await language_runtime.get_language(bot, 123456) == "fr"
    state["language"] = "en"
    assert await language_runtime.get_language(bot, 123456) == "fr"  # courte TTL
    bot._sentrix_language_checked_at[123456] = time.monotonic() - 15
    assert await language_runtime.get_language(bot, 123456) == "en"
    assert bot.guild_language_cache[123456] == "en"


def test_english_setup_strings_are_complete_without_franglais():
    text = "Disable cette catégorie"
    assert language_runtime.english_ui_text(text, setup=True) == "Disable this category"
    for fr, en in {
        "État des fonctionnalités": "Feature status",
        "Que veux-tu configurer ?": "What would you like to configure?",
        "Choisir un module ou une fonction…": "Choose a module or feature…",
    }.items():
        assert language_runtime.english_ui_text(fr, setup=True) == en
    # L'ID et le nom du serveur doivent rester EXACTEMENT ceux de Discord.
    name = "Serveur des Amis"
    actual = language_runtime.english_ui_text(
        f"Configuration SentriX · {name}", setup=True, protect=(name,)
    )
    assert name in actual


def test_default_welcome_templates_translate_but_custom_are_never_edited():
    formatter = setup_v2_completion._localized_default_template
    assert formatter(setup_v2_completion.WELCOME_DEFAULT_TITLE, "welcome_title", "en") == "Welcome to {server}"
    assert formatter(setup_v2_completion._LEGACY_FR_WELCOME, "welcome_text", "en") == "Welcome to **{server}**."
    assert formatter(setup_v2_completion.GOODBYE_DEFAULT_TEXT, "goodbye_text", "en").startswith("Goodbye")
    custom = "Bonjour à toutes et à tous, {member} !"
    assert formatter(custom, "welcome_text", "en") == custom


def test_welcome_card_png_renders_actual_english_labels():
    guild = SimpleNamespace(name="Misara", id=42)
    member = SimpleNamespace(
        guild=guild, id=10, display_name="Tomioka", name="Tomioka",
    )
    with patch("utils.member_event_cards._fit_text", wraps=__import__(
        "utils.member_event_cards", fromlist=["_fit_text"]
    )._fit_text) as fitted:
        f = build_member_event_card(member, kind="welcome", language="en")
    labels = [call.args[1] for call in fitted.call_args_list]
    assert labels[:3] == ["Welcome", "Tomioka", "joined Misara"]
    with Image.open(f.fp) as png:
        assert png.format == "PNG"
        assert png.size[0] >= 1000
    f.close()


@pytest.mark.asyncio
async def test_english_welcome_published_and_french_custom_welcome_preserved():
    guild = Mock(spec=discord.Guild)
    guild.id = 900
    guild.name = "Misara"
    guild.me = Mock()
    channel = Mock(spec=discord.TextChannel)
    channel.mention = "#welcome"
    channel.send = AsyncMock()
    channel.permissions_for = Mock(return_value=discord.Permissions.all())
    guild.get_channel = Mock(return_value=channel)
    member = Mock(spec=discord.Member)
    member.guild = guild
    member.id = 777
    member.name = member.display_name = "Tomioka"
    member.mention = "<@777>"
    member.display_avatar = Mock(url="https://cdn.discordapp.com/embed/avatars/0.png")

    config = {
        "welcome_channel": 55,
        "welcome_message": setup_v2_completion._LEGACY_FR_WELCOME,
        "welcome_image_url": None,
    }
    class DB:
        async def get_guild_config(self, guild_id):
            return config
        async def execute(self, *_args):
            return None
        async def fetchone(self, sql, *_args):
            return None
    bot = SimpleNamespace(db=DB())
    with patch("cogs.language_runtime.get_language", AsyncMock(return_value="en")):
        with patch("cogs.setup_v2_completion._welcome_presentation", AsyncMock(
            return_value={
                "title": setup_v2_completion.WELCOME_DEFAULT_TITLE,
                "show_avatar": True, "show_member_count": True,
                "mode": "embed", "ping": False, "dm": False,
            }
        )):
            with patch("cogs.setup_v2_completion._welcome_destination",
                       AsyncMock(return_value=(channel, None))):
                ok, _ = await setup_v2_completion._send_welcome(bot, member, test=True)
    assert ok
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.title == "Welcome to Misara"
    assert embed.description == "Welcome to **Misara**."
    card = channel.send.await_args.kwargs["file"]
    with Image.open(card.fp) as png:
        assert png.format == "PNG"
    card.close()
