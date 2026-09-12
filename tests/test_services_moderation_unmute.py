"""services/moderation.py::unmute — Core V2, Phase 2, quatrième commande migrée.

Réutilise _run_sanction_pipeline() (même partage que ban()/kick()), avec
dm_after=True : le MP part APRÈS le retrait du timeout, comme pour mute() —
un membre qu'on démute reste sur le serveur, la délivrabilité n'est pas en
jeu. Ce test verrouille spécifiquement cet ordre et l'invariant déjà établi :
une exception de persistance ne doit jamais annuler le succès d'une sanction
Discord déjà appliquée."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from services import moderation as moderation_service


class _FakeRole:
    def __init__(self, position: int):
        self.position = position

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position


class _FakeMember:
    def __init__(self, id, *, top_role_position, guild=None):
        self.id = id
        self.top_role = _FakeRole(top_role_position)
        self.guild = guild
        self.send = AsyncMock()
        self.timeout = AsyncMock()

    def __str__(self):
        return f"membre#{self.id}"


class _FakeGuild:
    def __init__(self, id, *, owner_id, me_top_role_position):
        self.id = id
        self.owner_id = owner_id
        self.me = _FakeMember(999, top_role_position=me_top_role_position)


class _FakeDB:
    def __init__(self, *, record_sanction=None):
        self.record_sanction = record_sanction or AsyncMock(return_value=3)


class _FakeBot:
    def __init__(self, *, record_sanction=None):
        self.db = _FakeDB(record_sanction=record_sanction)


def _setup(*, actor_top=10, target_top=1, owner_id=1, bot_top=20, record_sanction=None):
    guild = _FakeGuild(555, owner_id=owner_id, me_top_role_position=bot_top)
    actor = _FakeMember(1001, top_role_position=actor_top, guild=guild)
    target = _FakeMember(2002, top_role_position=target_top, guild=guild)
    bot = _FakeBot(record_sanction=record_sanction)
    return bot, guild, actor, target


class HierarchyRejectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuse_une_cible_avec_role_superieur(self):
        bot, guild, actor, target = _setup(actor_top=5, target_top=10)

        outcome = await moderation_service.unmute(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertFalse(outcome.executed)
        target.timeout.assert_not_awaited()


class SuccessfulUnmuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_retire_le_timeout_et_envoie_le_mp(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.unmute(
            bot, guild=guild, actor=actor, target=target, reason="comportement corrigé", dm_text="Vous n'êtes plus muet."
        )

        self.assertTrue(outcome.executed)
        self.assertTrue(outcome.dm_sent)
        self.assertEqual(outcome.case_number, 3)
        target.timeout.assert_awaited_once_with(None, reason=f"{actor} : comportement corrigé")

    async def test_mp_ferme_n_empeche_pas_le_retrait_du_mute(self):
        bot, guild, actor, target = _setup()
        target.send = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "MP fermé"))

        outcome = await moderation_service.unmute(
            bot, guild=guild, actor=actor, target=target, reason="test", dm_text="Vous n'êtes plus muet."
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        target.timeout.assert_awaited_once()


class DmOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_le_mp_part_apres_le_retrait_du_timeout(self):
        bot, guild, actor, target = _setup()
        ordre: list[str] = []
        target.timeout = AsyncMock(side_effect=lambda *a, **k: ordre.append("timeout"))
        target.send = AsyncMock(side_effect=lambda *a, **k: ordre.append("dm"))

        await moderation_service.unmute(
            bot, guild=guild, actor=actor, target=target, reason="test", dm_text="Vous n'êtes plus muet."
        )

        self.assertEqual(ordre, ["timeout", "dm"])


class PersistenceFailureNeverUndoesSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_une_exception_de_persistance_laisse_la_sanction_reussie(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(record_sanction=echec_db)

        outcome = await moderation_service.unmute(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertTrue(outcome.executed, "le retrait du timeout a réussi, executed doit rester True")
        target.timeout.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)


if __name__ == "__main__":
    unittest.main()
