"""Ensure /setup is private at its first acknowledgement, never deleted."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs import setup_invitations


@pytest.mark.asyncio
async def test_private_first_ack_guard_overrides_public_legacy_defer(monkeypatch):
    before_defer = AsyncMock()
    before_send = AsyncMock()
    monkeypatch.setattr(discord.InteractionResponse, "defer", before_defer)
    monkeypatch.setattr(discord.InteractionResponse, "send_message", before_send)
    setup_invitations._install_setup_initial_response_guard()

    interaction = SimpleNamespace(
        type=discord.InteractionType.application_command,
        data={"name": "setup"},
        command=None,
        extras={},
    )
    reply = SimpleNamespace(_parent=interaction)
    await discord.InteractionResponse.defer(reply, ephemeral=False, thinking=False)
    before_defer.assert_awaited_once_with(reply, ephemeral=True, thinking=True)
    assert interaction.extras["_sentrix_setup_private_initial"] is True
    await discord.InteractionResponse.send_message(reply, "Panneau", ephemeral=False)
    before_send.assert_awaited_once_with(reply, "Panneau", ephemeral=True)


@pytest.mark.asyncio
async def test_private_guard_does_not_affect_other_slash_or_buttons(monkeypatch):
    before_defer = AsyncMock()
    monkeypatch.setattr(discord.InteractionResponse, "defer", before_defer)
    setup_invitations._install_setup_initial_response_guard()

    for type_, name in (
        (discord.InteractionType.application_command, "balance"),
        (discord.InteractionType.component, "setup"),
    ):
        interaction = SimpleNamespace(type=type_, data={"name": name}, command=None, extras={})
        await discord.InteractionResponse.defer(
            SimpleNamespace(_parent=interaction), ephemeral=False
        )
        assert not interaction.extras
    assert before_defer.await_count == 2
    assert all(not call.kwargs.get("ephemeral") for call in before_defer.await_args_list)


@pytest.mark.asyncio
async def test_private_ack_never_deletes_original_deferred_message():
    original = SimpleNamespace(
        response=SimpleNamespace(
            is_done=lambda: True,
            type=discord.InteractionResponseType.deferred_channel_message,
        ),
        extras={"_sentrix_setup_private_initial": True},
        delete_original_response=AsyncMock(),
        edit_original_response=AsyncMock(),
    )
    assert await setup_invitations._prepare_private_setup_interaction(original) is False
    original.delete_original_response.assert_not_awaited()
    original.edit_original_response.assert_not_awaited()
