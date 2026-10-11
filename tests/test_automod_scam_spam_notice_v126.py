"""Tests de la présentation AutoMod et de la priorité anti-arnaque.

Ces scénarios isolent les corrections sans dépendre des anciennes simulations
de base de données et de sanctions propres aux commandes historiques.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import automod as automod_module
from cogs.automod import AutoMod


def test_link_notice_is_a_compact_colored_native_v2_card():
    view = AutoMod._content_notice_view("<@123>", "antilink")
    assert isinstance(view, discord.ui.LayoutView)
    assert len(view.children) == 1
    container = view.children[0]
    assert isinstance(container, discord.ui.Container)
    assert container.accent_colour is not None
    assert len(container.children) == 1
    text = container.children[0]
    assert isinstance(text, discord.ui.TextDisplay)
    assert "Lien supprimé" in text.content
    assert "<@123>" in text.content
    assert "8 s" in text.content
    assert not any(isinstance(c, discord.ui.MediaGallery) for c in container.children)


def test_scam_notice_contains_no_suspect_url():
    view = AutoMod._content_notice_view("<@123>", "antiscam")
    text = view.children[0].children[0].content
    assert "Arnaque suspectée" in text
    assert "http" not in text


@pytest.mark.parametrize("content", [
    "discοrd.com/nitro",  # lettre grecque ο
    "dіscord.gg/invite",  # lettre cyrillique і
    "xn--discrd-jua.com/verify",  # punycode, visuellement ressemblant
])
def test_bare_unicode_brand_impersonation_is_caught(content):
    assert automod_module._scam_hit(content) is not None, content


@pytest.mark.parametrize("content", [
    "discord.com/developers",
    "discord.gg/help",
    "roblox.com/games",
    "Mon ami cite discord.com et pense que c'est un scam.",
    "je cherche une page github.com sur les faux liens Discord",
])
def test_legitimate_links_and_discussion_are_not_scam(content):
    assert automod_module._scam_hit(content) is None, content


@pytest.mark.asyncio
async def test_phishing_is_labelled_scam_before_generic_link_rejection():
    guild = Mock(spec=discord.Guild)
    guild.id = 111
    guild.owner_id = 99
    author = Mock(spec=discord.Member)
    author.id = 23
    author.bot = False
    author.guild = guild
    author.guild_permissions = SimpleNamespace(administrator=False, manage_guild=False)
    author.roles = []
    message = Mock(spec=discord.Message)
    message.guild = guild
    message.author = author
    message.content = "get nitro https://discord.com@fake-nitro.example/claim"

    bot = SimpleNamespace(db=SimpleNamespace())
    cog = AutoMod(bot)
    cog.get_automod_cached = AsyncMock(return_value={"antiscam": 1, "antilink": 1})
    cog.get_immunity_override_cached = AsyncMock(return_value=None)
    cog.security_filter_applies_to = AsyncMock(return_value=True)
    cog._delete_and_warn = AsyncMock()

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()
    assert cog._delete_and_warn.await_args.args[2] == "antiscam"


def test_spam_incident_cooldown_is_shorter_than_global_incident_window():
    # L'excès de spam ne doit pas supprimer 30 secondes de conversation
    # après la rafale. La fenêtre progressive reste configurée à 8 secondes.
    assert automod_module.SPAM_INCIDENT_WINDOW_SECONDS <= 10
    assert automod_module.SPAM_INCIDENT_WINDOW_SECONDS < automod_module.INCIDENT_WINDOW_SECONDS
