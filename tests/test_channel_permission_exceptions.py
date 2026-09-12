"""Milestone 2 (Configuration Platform), Permission Center : exceptions salon/
catégorie par commande (command_channel_permissions, cogs/setup_v2_core.py) +
utils/access_matrix.py::Backend.channel_rule.

Volontairement PAS branché dans utils/access_matrix.py::evaluate() (la
décision de sécurité centrale) dans ce lot : le point d'intégration exact dans
sa chaîne (avant/après le bypass Administrateur ou propriétaire, notamment)
est une décision produit, pas un détail d'implémentation — laissée à Jayden.
Ces tests couvrent donc le stockage et la résolution, prêts à être branchés,
sans toucher au chemin de décision réellement actif aujourd'hui.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import setup_v2_core as core
from database.db import Database
from utils import access_matrix


async def _make_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "perms.db"))
    await db.connect()
    return db


def _guild(guild_id: int = 1):
    return SimpleNamespace(id=guild_id)


def _channel(channel_id: int, category_id: int | None = None):
    return SimpleNamespace(id=channel_id, category_id=category_id)


# --------------------------------------------------------- storage layer --

def test_no_rule_returns_none(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            decision = await core.get_channel_command_decision(bot, _guild(), _channel(100), "ban")
            assert decision is None
        finally:
            await db.close()

    asyncio.run(run())


def test_set_then_get_roundtrips(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            await core.set_channel_command_decision(bot, 1, 100, "ban", "allow")
            decision = await core.get_channel_command_decision(bot, _guild(), _channel(100), "ban")
            assert decision == "allow"
        finally:
            await db.close()

    asyncio.run(run())


def test_deny_wins_over_allow_between_channel_and_category(tmp_path):
    """Même précédence que command_role_permissions : un refus explicite sur
    N'IMPORTE LAQUELLE des portées applicables (le salon ou sa catégorie)
    l'emporte sur une autorisation explicite sur l'autre."""
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            await core.set_channel_command_decision(bot, 1, 100, "ban", "allow")  # le salon
            await core.set_channel_command_decision(bot, 1, 999, "ban", "deny")   # sa catégorie
            decision = await core.get_channel_command_decision(
                bot, _guild(), _channel(100, category_id=999), "ban"
            )
            assert decision == "deny"
        finally:
            await db.close()

    asyncio.run(run())


def test_category_only_rule_applies_to_channels_inside_it(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            await core.set_channel_command_decision(bot, 1, 999, "ban", "deny")
            decision = await core.get_channel_command_decision(
                bot, _guild(), _channel(100, category_id=999), "ban"
            )
            assert decision == "deny"
            # Un salon SANS cette catégorie ne doit pas hériter de la règle.
            other = await core.get_channel_command_decision(
                bot, _guild(), _channel(200, category_id=None), "ban"
            )
            assert other is None
        finally:
            await db.close()

    asyncio.run(run())


def test_set_default_deletes_the_rule(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            await core.set_channel_command_decision(bot, 1, 100, "ban", "deny")
            await core.set_channel_command_decision(bot, 1, 100, "ban", "default")
            decision = await core.get_channel_command_decision(bot, _guild(), _channel(100), "ban")
            assert decision is None
        finally:
            await db.close()

    asyncio.run(run())


def test_set_rejects_invalid_decision(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            with pytest.raises(ValueError):
                await core.set_channel_command_decision(bot, 1, 100, "ban", "maybe")
        finally:
            await db.close()

    asyncio.run(run())


def test_updating_an_existing_rule_overwrites_not_duplicates(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            await core.set_channel_command_decision(bot, 1, 100, "ban", "allow")
            await core.set_channel_command_decision(bot, 1, 100, "ban", "deny")
            rows = await db.fetchall(
                "SELECT decision FROM command_channel_permissions WHERE guild_id=1 AND channel_id=100 AND command_name='ban'"
            )
            assert len(rows) == 1
            assert rows[0]["decision"] == "deny"
        finally:
            await db.close()

    asyncio.run(run())


def test_no_guild_or_channel_returns_none_without_touching_db(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            assert await core.get_channel_command_decision(bot, None, _channel(100), "ban") is None
            assert await core.get_channel_command_decision(bot, _guild(), None, "ban") is None
        finally:
            await db.close()

    asyncio.run(run())


# ------------------------------------------------- Backend.channel_rule --

def test_backend_channel_rule_translates_deny_to_false(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            await core.set_channel_command_decision(bot, 1, 100, "ban", "deny")
            backend = access_matrix.Backend(bot)
            result = await backend.channel_rule(1, _guild(), _channel(100), "ban")
            assert result is False
        finally:
            await db.close()

    asyncio.run(run())


def test_backend_channel_rule_translates_allow_to_true(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            await core.set_channel_command_decision(bot, 1, 100, "ban", "allow")
            backend = access_matrix.Backend(bot)
            result = await backend.channel_rule(1, _guild(), _channel(100), "ban")
            assert result is True
        finally:
            await db.close()

    asyncio.run(run())


def test_backend_channel_rule_is_none_without_any_configured_exception(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        bot = SimpleNamespace(db=db)
        try:
            backend = access_matrix.Backend(bot)
            result = await backend.channel_rule(1, _guild(), _channel(100), "ban")
            assert result is None
        finally:
            await db.close()

    asyncio.run(run())


def test_backend_channel_rule_fails_closed_to_none_on_db_error():
    """Fail-safe, pas fail-open : une erreur de lecture ne doit jamais se
    traduire par une autorisation, seulement par 'aucune exception connue'
    (le reste de evaluate() continue de décider normalement)."""
    bot = SimpleNamespace(db=AsyncMock())
    bot.db.fetchall = AsyncMock(side_effect=RuntimeError("boom"))

    async def run():
        backend = access_matrix.Backend(bot)
        return await backend.channel_rule(1, _guild(), _channel(100), "ban")

    assert asyncio.run(run()) is None


def test_evaluate_does_not_yet_call_channel_rule():
    """Garde-fou explicite : tant que le point d'intégration n'est pas
    tranché par Jayden, evaluate() ne doit PAS interroger channel_rule — la
    fonctionnalité doit rester un no-op sur le chemin de décision actif."""
    import inspect

    source = inspect.getsource(access_matrix.evaluate)
    assert "channel_rule" not in source
