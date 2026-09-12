"""services/moderation.py::kick — Core V2, Phase 2, deuxième commande migrée.

Même pipeline que ban() (hiérarchie -> notification -> exécution Discord ->
persistance), partagé via _run_sanction_pipeline() — voir
tests/test_services_moderation_ban.py pour le test original qui a trouvé et
corrigé le trou de persistance non protégée. Ces tests confirment que le
partage du pipeline n'a rien affaibli pour kick spécifiquement."""
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

    def __str__(self):
        return f"membre#{self.id}"


class _FakeGuild:
    def __init__(self, id, *, owner_id, me_top_role_position):
        self.id = id
        self.owner_id = owner_id
        self.me = _FakeMember(999, top_role_position=me_top_role_position)
        self.kick = AsyncMock()


class _FakeDB:
    def __init__(self, *, record_sanction=None):
        self.record_sanction = record_sanction or AsyncMock(return_value=17)


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

        outcome = await moderation_service.kick(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.hierarchy_error)
        guild.kick.assert_not_awaited()
        target.send.assert_not_awaited()

    async def test_refuse_le_proprietaire_du_serveur(self):
        bot, guild, actor, target = _setup(owner_id=2002, target_top=1)

        outcome = await moderation_service.kick(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertFalse(outcome.executed)
        self.assertIn("propriétaire", outcome.hierarchy_error)
        guild.kick.assert_not_awaited()


class SuccessfulKickTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_l_expulsion_et_envoie_le_mp(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.kick(
            bot, guild=guild, actor=actor, target=target, reason="spam", dm_text="Vous avez été expulsé."
        )

        self.assertTrue(outcome.executed)
        self.assertTrue(outcome.dm_sent)
        self.assertEqual(outcome.case_number, 17)
        self.assertIsNone(outcome.persistence_error)
        guild.kick.assert_awaited_once()
        target.send.assert_awaited_once()

    async def test_mp_ferme_n_empeche_pas_l_expulsion(self):
        bot, guild, actor, target = _setup()
        target.send = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "MP fermé"))

        outcome = await moderation_service.kick(
            bot, guild=guild, actor=actor, target=target, reason="spam", dm_text="Vous avez été expulsé."
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        guild.kick.assert_awaited_once()

    async def test_appelle_guild_kick_avec_la_raison_et_l_auteur_sans_suppression_de_messages(self):
        """Contrairement à ban(), kick() ne passe pas delete_message_seconds :
        Discord n'en propose pas pour un kick, ce n'est pas un oubli."""
        bot, guild, actor, target = _setup()

        await moderation_service.kick(bot, guild=guild, actor=actor, target=target, reason="spam répété")

        args, kwargs = guild.kick.call_args
        self.assertIs(args[0], target)
        self.assertIn("spam répété", kwargs["reason"])
        self.assertIn(str(actor), kwargs["reason"])
        self.assertNotIn("delete_message_seconds", kwargs)


class PersistenceFailureNeverUndoesSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_une_exception_de_persistance_laisse_la_sanction_reussie(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(record_sanction=echec_db)

        outcome = await moderation_service.kick(bot, guild=guild, actor=actor, target=target, reason="spam")

        self.assertTrue(outcome.executed, "l'expulsion Discord a réussi, executed doit rester True")
        guild.kick.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)


if __name__ == "__main__":
    unittest.main()
