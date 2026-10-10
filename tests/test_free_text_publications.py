"""End-to-end +say surface: a native framed publication, never a quoted raw block."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs.utility import Utility
from utils.free_text_publications import PublicationCard, publication_parts


def test_rule_number_is_heading_not_inline_code_badge():
    title, content, category = publication_parts("`Règle n°4 : Respectez tous les membres.`")
    assert (title, content, category) == (
        "Règle n°4", "Respectez tous les membres.", "Règlement"
    )


def test_rule_with_separate_body_keeps_all_paragraphs():
    title, content, _ = publication_parts(
        "Règle n°4 :\nLes insultes sont interdites.\n\nMerci de respecter les membres."
    )
    assert title == "Règle n°4"
    assert content == "Les insultes sont interdites.\n\nMerci de respecter les membres."


def test_whole_discord_quote_uses_real_card_instead_of_quote_bar():
    title, content, _ = publication_parts(
        "> Je fais aussi une petite parenthèse.\n> Il va falloir se bouger.\n> Merci."
    )
    assert title == "Message du serveur"
    assert content == (
        "Je fais aussi une petite parenthèse.\nIl va falloir se bouger.\nMerci."
    )
    assert not content.startswith(">")


def test_mixed_quote_retains_user_written_markdown():
    title, content, _ = publication_parts("Annonce importante\n> Extrait cité d'un membre")
    assert title == "Message du serveur"
    assert "> Extrait cité d'un membre" in content


def test_native_card_has_a_single_actual_container_and_separator():
    view = PublicationCard("Règle n°4 : Pas de spam.")
    assert isinstance(view, discord.ui.LayoutView)
    assert len(view.children) == 1
    container = view.children[0]
    assert isinstance(container, discord.ui.Container)
    assert any(isinstance(x, discord.ui.Separator) for x in container.children)
    displays = [x.content for x in container.children if isinstance(x, discord.ui.TextDisplay)]
    assert "## Règle n°4" in displays
    assert "Pas de spam." in displays
    assert displays[-1].startswith("-# Règlement")


def _ctx():
    return SimpleNamespace(
        interaction=None,
        channel=SimpleNamespace(send=AsyncMock()),
        message=SimpleNamespace(delete=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_actual_say_callback_publishes_framed_once_without_pinging():
    ctx = _ctx()
    await Utility.say.callback(object(), ctx, texte="> Une phrase libre.\n> Une suite.")

    ctx.channel.send.assert_awaited_once()
    args, kwargs = ctx.channel.send.await_args
    assert args == ()
    assert isinstance(kwargs["view"], PublicationCard)
    allowed = kwargs["allowed_mentions"]
    assert allowed.everyone is False and allowed.roles is False
    assert allowed.users is False and allowed.replied_user is False
    ctx.message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_brut_mode_keeps_legacy_text_without_pings():
    ctx = _ctx()
    await Utility.say.callback(object(), ctx, texte="--brut > Texte libre")
    ctx.channel.send.assert_awaited_once()
    args, kwargs = ctx.channel.send.await_args
    assert args == ("> Texte libre",)
    assert kwargs["allowed_mentions"].everyone is False
    assert "view" not in kwargs


@pytest.mark.asyncio
async def test_too_long_publication_preserves_source_and_never_truncates_silently():
    ctx = _ctx()
    from utils import sentrix_panels
    with patch.object(sentrix_panels, "texte_court", AsyncMock()) as error:
        await Utility.say.callback(object(), ctx, texte="x" * 3501)

    ctx.channel.send.assert_not_awaited()
    ctx.message.delete.assert_not_awaited()
    error.assert_awaited_once()
    assert "3 500" in error.await_args.args[1]
