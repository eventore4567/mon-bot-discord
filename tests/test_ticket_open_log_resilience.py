"""Ticket déjà créé : une panne des logs ne déclenche aucun faux échec membre."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import tickets


@pytest.mark.asyncio
async def test_log_ouverture_reussi():
    log_action = AsyncMock(return_value=None)
    cog = SimpleNamespace(log_action=log_action)
    guild = SimpleNamespace(id=123)
    embed = object()
    ok = await tickets.Tickets._send_open_log_safely(cog, guild, embed, 555)
    assert ok is True
    log_action.assert_awaited_once_with(guild, embed, 555)


@pytest.mark.asyncio
async def test_echec_log_n_est_pas_relance_vers_le_gestionnaire_interaction(caplog):
    log_action = AsyncMock(side_effect=RuntimeError("log server unavailable"))
    cog = SimpleNamespace(log_action=log_action)
    guild = SimpleNamespace(id=123)
    ok = await tickets.Tickets._send_open_log_safely(cog, guild, object(), None)
    assert ok is False
    assert "Ticket créé mais journal d'ouverture impossible" in caplog.text
    log_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_annulation_tache_est_preservee():
    # CancelledError ne doit pas être avalée : les arrêts doivent rester sûrs.
    log_action = AsyncMock(side_effect=asyncio.CancelledError())
    cog = SimpleNamespace(log_action=log_action)
    with pytest.raises(asyncio.CancelledError):
        await tickets.Tickets._send_open_log_safely(cog, SimpleNamespace(id=123), object(), 555)
