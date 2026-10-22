from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.setup_control_center import SetupView
from utils import sentrix_panels as panels


def _interaction(done=False):
    return SimpleNamespace(response=SimpleNamespace(is_done=lambda: done, defer=AsyncMock(), send_message=AsyncMock()),
                           followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())


@pytest.mark.asyncio
async def test_setup_refresh_acknowledges_before_slow_database_reads():
    interaction = _interaction()
    async def compose():
        interaction.response.defer.assert_awaited_once()
    owner = SimpleNamespace(composer=compose, fichiers=lambda: [])
    await SetupView.refresh(owner, interaction)
    interaction.edit_original_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_setup_refresh_can_complete_an_already_deferred_action():
    interaction = _interaction(done=True)
    owner = SimpleNamespace(composer=AsyncMock(), fichiers=lambda: [])
    await SetupView.refresh(owner, interaction)
    interaction.response.defer.assert_not_awaited()
    owner.composer.assert_awaited_once()
    interaction.edit_original_response.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("done", [True, False])
async def test_interactive_panels_report_failed_action_without_claiming_success(done):
    interaction = _interaction(done)
    panel = panels.Panneau(titre="Test", banniere=False)
    await panel.on_error(interaction, RuntimeError("database unavailable"), SimpleNamespace())
    sender = interaction.followup.send if done else interaction.response.send_message
    sender.assert_awaited_once()
    assert "Vérifiez son résultat" in sender.await_args.args[0]
    assert sender.await_args.kwargs["ephemeral"]


@pytest.mark.asyncio
async def test_legacy_buttons_keep_the_new_user_visible_error_handler():
    import discord
    source = discord.ui.View()
    source.add_item(discord.ui.Button(label="Action"))
    panel = panels.avec_composants(panels.Panneau(titre="Test", banniere=False), source)
    assert panel.on_error.__func__ is panels.Panneau.on_error


@pytest.mark.asyncio
async def test_custom_legacy_error_handler_is_preserved():
    import discord
    source = discord.ui.View()
    source.on_error = AsyncMock()
    source.add_item(discord.ui.Button(label="Action"))
    panel = panels.avec_composants(panels.Panneau(titre="Test", banniere=False), source)
    assert panel.on_error is source.on_error
