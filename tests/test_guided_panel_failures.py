"""Brouillons privés, refus propres et restauration des choix publiés."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
import discord
import pytest
import pytest_asyncio

from cogs.economy_panel_builder import (
    ActivityPublicView,
    EconomyPanelBuilder,
    restore_activity_panels,
)
from cogs.reaction_role_wizard import ReactionRoleWizard, RoleEmojiModal
from database.db import Database


@pytest_asyncio.fixture
async def world(tmp_path):
    db = Database(str(tmp_path / "panels.db"))
    await db.connect()
    role = SimpleNamespace(id=10, name="Joueur")
    message = SimpleNamespace(
        id=123,
        jump_url="https://discord.com/channels/1/2/123",
        add_reaction=AsyncMock(),
        delete=AsyncMock(),
    )
    channel = SimpleNamespace(
        id=2,
        send=AsyncMock(return_value=message),
        permissions_for=lambda _: discord.Permissions.all(),
    )
    guild = SimpleNamespace(
        id=1,
        me=object(),
        get_role=lambda rid: role if rid == 10 else None,
        get_channel=lambda cid: channel if cid == 2 else None,
    )
    bot = SimpleNamespace(db=db, add_view=MagicMock())
    yield SimpleNamespace(
        bot=bot, guild=guild, role=role, channel=channel, message=message
    )
    await db.close()


def interaction(*, admin=True):
    return SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(
            id=42, guild_permissions=SimpleNamespace(administrator=admin)
        ),
        response=SimpleNamespace(
            is_done=lambda: False, defer=AsyncMock(), send_message=AsyncMock()
        ),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_duplicate_emojis_do_not_change_draft_or_publish(world):
    view = ReactionRoleWizard(world.bot, world.guild, 42)
    view.mappings = [("unicode:🎮", "🎮", 99)]
    modal = RoleEmojiModal(view, world.role)
    modal.emoji._value = "🎮"
    i = interaction()
    with patch("cogs.economy._self_assignable_role_error", return_value=None):
        await modal.on_submit(i)
    assert len(view.mappings) == 1
    assert "déjà" in i.response.send_message.call_args.args[0]
    world.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_reaction_failure_leaves_no_empty_panel_or_associations(world):
    view = ReactionRoleWizard(world.bot, world.guild, 42)
    view.mappings, view.channel_id = [("unicode:🎮", "🎮", 10)], 2
    world.message.add_reaction.side_effect = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Emoji inaccessible"
    )
    with patch("cogs.economy._self_assignable_role_error", return_value=None):
        await view.publish(interaction())
    world.message.delete.assert_awaited_once()
    assert not view.published and not view.publishing
    assert not await world.bot.db.fetchall("SELECT * FROM reaction_role_panels")
    assert not await world.bot.db.fetchall("SELECT * FROM reaction_roles")


@pytest.mark.asyncio
async def test_role_permissions_rechecked_at_publication(world):
    view = ReactionRoleWizard(world.bot, world.guild, 42)
    view.mappings, view.channel_id = [("unicode:🎮", "🎮", 10)], 2
    with patch(
        "cogs.economy._self_assignable_role_error", return_value="Rôle au-dessus du bot"
    ):
        await view.publish(interaction())
    world.channel.send.assert_not_awaited()
    assert not view.published


@pytest.mark.asyncio
async def test_activity_publication_is_explicit_and_restores_exact_options(world):
    view = EconomyPanelBuilder(world.bot, world.guild, 42)
    view.channel_id = 2
    view.config = {
        "title": "Mes jeux",
        "text": "À vous !",
        "actions": ["doors", "emojiquiz"],
    }
    world.channel.send.assert_not_awaited()
    i = interaction()
    await view.publish(i)
    assert view.published
    stored = await world.bot.db.fetchall("SELECT * FROM sentrix_public_activity_panels")
    assert len(stored) == 1
    world.bot.add_view.reset_mock()
    await restore_activity_panels(world.bot)
    restored = world.bot.add_view.call_args.args[0]
    assert isinstance(restored, ActivityPublicView) and restored.is_persistent()
    assert restored.config == view.config
    assert world.bot.add_view.call_args.kwargs["message_id"] == 123
    await view.publish(interaction())
    world.channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_admin_cannot_publish_either_panel(world):
    for cls in (ReactionRoleWizard, EconomyPanelBuilder):
        view = cls(world.bot, world.guild, 42)
        i = interaction(admin=False)
        await view.publish(i)
        i.response.send_message.assert_awaited_once()
    world.channel.send.assert_not_awaited()
