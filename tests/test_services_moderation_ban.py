"""services/moderation.py::ban — Core V2, Phase 2, première commande migrée.

Le pipeline (hiérarchie -> notification -> exécution Discord -> persistance)
est testé sans jamais instancier Discord. Le test le plus important est la
correction du vrai trou trouvé en extrayant ce code : une exception de
persistance ne doit JAMAIS annuler le succès d'une sanction déjà appliquée par
Discord (demande initiale, section 17)."""
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

    def __le__(self, other):
        return self.position <= other.position

    def __lt__(self, other):
        return self.position < other.position


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
        self.ban = AsyncMock()


class _FakeDB:
    def __init__(self, *, record_sanction=None):
        self.record_sanction = record_sanction or AsyncMock(return_value=42)


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

        outcome = await moderation_service.ban(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.hierarchy_error)
        guild.ban.assert_not_awaited()
        target.send.assert_not_awaited()

    async def test_refuse_le_proprietaire_du_serveur(self):
        bot, guild, actor, target = _setup(owner_id=2002, target_top=1)

        outcome = await moderation_service.ban(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertFalse(outcome.executed)
        self.assertIn("propriétaire", outcome.hierarchy_error)
        guild.ban.assert_not_awaited()

    async def test_refuse_si_le_role_du_bot_est_trop_bas(self):
        # actor_top doit rester au-dessus de target_top, sinon le check hiérarchie
        # AUTEUR (évalué en premier) rejette avant même d'atteindre celui du bot.
        bot, guild, actor, target = _setup(actor_top=20, target_top=15, bot_top=5)

        outcome = await moderation_service.ban(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertFalse(outcome.executed)
        self.assertIn("SentriX", outcome.hierarchy_error)
        guild.ban.assert_not_awaited()


class SuccessfulBanTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_le_bannissement_et_envoie_le_mp(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.ban(
            bot, guild=guild, actor=actor, target=target, reason="spam", dm_text="Vous avez été banni."
        )

        self.assertTrue(outcome.executed)
        self.assertTrue(outcome.dm_sent)
        self.assertEqual(outcome.case_number, 42)
        self.assertIsNone(outcome.persistence_error)
        guild.ban.assert_awaited_once()
        target.send.assert_awaited_once()

    async def test_sans_texte_de_mp_n_essaie_pas_d_envoyer(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.ban(bot, guild=guild, actor=actor, target=target, reason="spam", dm_text=None)

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        target.send.assert_not_awaited()

    async def test_mp_ferme_n_empeche_pas_le_bannissement(self):
        bot, guild, actor, target = _setup()
        target.send = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "MP fermé"))

        outcome = await moderation_service.ban(
            bot, guild=guild, actor=actor, target=target, reason="spam", dm_text="Vous avez été banni."
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        guild.ban.assert_awaited_once()

    async def test_appelle_guild_ban_avec_la_raison_et_l_auteur(self):
        bot, guild, actor, target = _setup()

        await moderation_service.ban(bot, guild=guild, actor=actor, target=target, reason="spam répété")

        args, kwargs = guild.ban.call_args
        self.assertIs(args[0], target)
        self.assertIn("spam répété", kwargs["reason"])
        self.assertIn(str(actor), kwargs["reason"])
        self.assertEqual(kwargs["delete_message_seconds"], 0)


class PersistenceFailureNeverUndoesSuccessTests(unittest.IsolatedAsyncioTestCase):
    """Le test qui verrouille la correction du vrai trou trouvé en extrayant ce
    code : bot.db.record_sanction() n'était protégé par aucun try/except."""

    async def test_une_exception_de_persistance_laisse_la_sanction_reussie(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(record_sanction=echec_db)

        outcome = await moderation_service.ban(bot, guild=guild, actor=actor, target=target, reason="spam")

        self.assertTrue(outcome.executed, "la sanction Discord a réussi, executed doit rester True")
        guild.ban.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)
        self.assertIn("disque plein", outcome.persistence_error)

    async def test_ne_leve_jamais_d_exception_meme_si_la_persistance_echoue(self):
        echec_db = AsyncMock(side_effect=RuntimeError("boum"))
        bot, guild, actor, target = _setup(record_sanction=echec_db)

        try:
            await moderation_service.ban(bot, guild=guild, actor=actor, target=target, reason="spam")
        except RuntimeError:
            self.fail("ban() ne doit jamais laisser fuir une exception de persistance")


class PersistSanctionDirectTests(unittest.IsolatedAsyncioTestCase):
    async def test_retourne_le_numero_de_dossier_en_cas_de_succes(self):
        bot = _FakeBot(record_sanction=AsyncMock(return_value=7))
        case_number, error = await moderation_service.persist_sanction(
            bot, guild_id=1, target_id=2, actor_id=3, action="ban", reason="r"
        )
        self.assertEqual(case_number, 7)
        self.assertIsNone(error)

    async def test_retourne_none_et_l_erreur_en_cas_d_echec(self):
        bot = _FakeBot(record_sanction=AsyncMock(side_effect=ValueError("cassé")))
        case_number, error = await moderation_service.persist_sanction(
            bot, guild_id=1, target_id=2, actor_id=3, action="ban", reason="r"
        )
        self.assertIsNone(case_number)
        self.assertEqual(error, "cassé")


if __name__ == "__main__":
    unittest.main()
