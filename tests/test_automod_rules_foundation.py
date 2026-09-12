"""Milestone 3 (Modules avancés) : fondation du moteur de règles AutoMod
(automod_rules, cogs/automod.py::get_automod_rule/set_automod_rule/
delete_automod_rule). Purement additif — automod_settings (l'interrupteur
maître par filtre, 11 booléens) reste inchangé et continue d'être la seule
chose lue/écrite par tous ses ~17 appelants existants.

_maybe_escalate (la fonction qui décide réellement mute/kick/ban) ne consulte
PAS encore ces règles : elle est remplacée à l'exécution par trois cogs
différents (owner_sanction_immunity, content_filter_policy,
bot_excellence_runtime) qui se disputent déjà son comportement — câbler cette
table sans résoudre ce conflit d'abord aurait pu n'avoir aucun effet en
production, ou entrer en contradiction avec le système déjà actif. Ces tests
couvrent donc uniquement le stockage, prêt à être branché une fois cette
décision prise par Jayden.
"""
from __future__ import annotations

import asyncio

import pytest

from cogs import automod
from database.db import Database


async def _make_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "automod_rules.db"))
    await db.connect()
    return db


class _FakeBot:
    def __init__(self, db):
        self.db = db


def test_no_rule_returns_none(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            rule = await automod.get_automod_rule(bot, 1, "antispam")
            assert rule is None
        finally:
            await db.close()

    asyncio.run(run())


def test_set_then_get_roundtrips_all_fields(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            await automod.set_automod_rule(
                bot, 1, "antispam",
                threshold=3, window_seconds=300, action="mute",
                excluded_role_ids=[111, 222], excluded_channel_ids=[333],
                message="Trop de messages, calme-toi.",
            )
            rule = await automod.get_automod_rule(bot, 1, "antispam")
            assert rule == {
                "threshold": 3,
                "window_seconds": 300,
                "action": "mute",
                "excluded_role_ids": [111, 222],
                "excluded_channel_ids": [333],
                "message": "Trop de messages, calme-toi.",
            }
        finally:
            await db.close()

    asyncio.run(run())


def test_rules_are_independent_per_filter_and_per_guild(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            await automod.set_automod_rule(bot, 1, "antispam", threshold=3, action="mute")
            await automod.set_automod_rule(bot, 1, "antilink", threshold=1, action="ban")
            await automod.set_automod_rule(bot, 2, "antispam", threshold=10, action="warn")

            assert (await automod.get_automod_rule(bot, 1, "antispam"))["threshold"] == 3
            assert (await automod.get_automod_rule(bot, 1, "antilink"))["action"] == "ban"
            assert (await automod.get_automod_rule(bot, 2, "antispam"))["threshold"] == 10
        finally:
            await db.close()

    asyncio.run(run())


def test_updating_an_existing_rule_overwrites_not_duplicates(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            await automod.set_automod_rule(bot, 1, "antispam", threshold=3, action="mute")
            await automod.set_automod_rule(bot, 1, "antispam", threshold=5, action="kick")

            rule = await automod.get_automod_rule(bot, 1, "antispam")
            assert rule["threshold"] == 5
            assert rule["action"] == "kick"

            rows = await db.fetchall(
                "SELECT * FROM automod_rules WHERE guild_id=1 AND filter_name='antispam'"
            )
            assert len(rows) == 1
        finally:
            await db.close()

    asyncio.run(run())


def test_delete_reverts_to_default_behavior(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            await automod.set_automod_rule(bot, 1, "antispam", threshold=3, action="mute")
            await automod.delete_automod_rule(bot, 1, "antispam")
            assert await automod.get_automod_rule(bot, 1, "antispam") is None
        finally:
            await db.close()

    asyncio.run(run())


def test_unknown_filter_name_is_rejected(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            with pytest.raises(ValueError):
                await automod.get_automod_rule(bot, 1, "not-a-real-filter")
            with pytest.raises(ValueError):
                await automod.set_automod_rule(bot, 1, "not-a-real-filter", action="mute")
        finally:
            await db.close()

    asyncio.run(run())


def test_invalid_action_is_rejected(tmp_path):
    async def run():
        db = await _make_db(tmp_path)
        try:
            bot = _FakeBot(db)
            with pytest.raises(ValueError):
                await automod.set_automod_rule(bot, 1, "antispam", action="explode")
        finally:
            await db.close()

    asyncio.run(run())


def test_maybe_escalate_does_not_yet_read_automod_rules():
    """Garde-fou explicite : tant que le conflit à trois cogs n'est pas résolu
    par Jayden, _maybe_escalate ne doit pas référencer automod_rules — un
    branchement futur doit être un choix délibéré et testé, jamais un effet
    de bord silencieux (même motif que evaluate()/channel_rule, §Milestone 2)."""
    import inspect

    source = inspect.getsource(automod.AutoMod._maybe_escalate)
    assert "automod_rules" not in source
    assert "get_automod_rule" not in source
