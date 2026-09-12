"""services/moderation.py::unban — Core V2, Phase 2, septième et dernière
commande de sanction migrée.

Forme distincte de toutes les autres : la cible n'est pas un discord.Member
résolu en amont par Discord (donc aucune hiérarchie à vérifier), mais un
identifiant brut résolu DANS le pipeline via ``fetch_user`` injecté par
l'appelant. Ces tests verrouillent cette résolution, le cas NotFound déjà
géré par le code existant, et l'invariant déjà établi : une exception de
persistance ne doit jamais annuler le succès d'un débannissement Discord déjà
appliqué."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from services import moderation as moderation_service


class _FakeUser:
    def __init__(self, id):
        self.id = id
        self.send = AsyncMock()

    def __str__(self):
        return f"utilisateur#{self.id}"


class _FakeMember:
    def __init__(self, id):
        self.id = id

    def __str__(self):
        return f"membre#{self.id}"


class _FakeGuild:
    def __init__(self, id):
        self.id = id
        self.unban = AsyncMock()


class _FakeDB:
    def __init__(self, *, record_sanction=None):
        self.record_sanction = record_sanction or AsyncMock(return_value=8)


class _FakeBot:
    def __init__(self, *, record_sanction=None):
        self.db = _FakeDB(record_sanction=record_sanction)


def _setup(*, record_sanction=None):
    guild = _FakeGuild(555)
    actor = _FakeMember(1001)
    bot = _FakeBot(record_sanction=record_sanction)
    return bot, guild, actor


class NotFoundTests(unittest.IsolatedAsyncioTestCase):
    async def test_utilisateur_introuvable_ne_tente_jamais_le_debannissement(self):
        bot, guild, actor = _setup()
        fetch_user = AsyncMock(side_effect=discord.NotFound(Mock(status=404), "introuvable"))

        outcome = await moderation_service.unban(
            bot, guild=guild, actor=actor, user_id=999, reason="test", fetch_user=fetch_user,
        )

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.validation_error)
        guild.unban.assert_not_awaited()

    async def test_pas_banni_leve_par_guild_unban_est_gere_pareillement(self):
        bot, guild, actor = _setup()
        user = _FakeUser(2002)
        fetch_user = AsyncMock(return_value=user)
        guild.unban = AsyncMock(side_effect=discord.NotFound(Mock(status=404), "pas banni"))

        outcome = await moderation_service.unban(
            bot, guild=guild, actor=actor, user_id=2002, reason="test", fetch_user=fetch_user,
        )

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.validation_error)


class SuccessfulUnbanTests(unittest.IsolatedAsyncioTestCase):
    async def test_debannit_et_expose_l_utilisateur_resolu(self):
        bot, guild, actor = _setup()
        user = _FakeUser(2002)
        fetch_user = AsyncMock(return_value=user)

        outcome = await moderation_service.unban(
            bot, guild=guild, actor=actor, user_id=2002, reason="erreur de modération", fetch_user=fetch_user,
        )

        self.assertTrue(outcome.executed)
        self.assertIs(outcome.resolved_target, user)
        self.assertEqual(outcome.case_number, 8)
        guild.unban.assert_awaited_once_with(user, reason=f"{actor} : erreur de modération")

    async def test_render_dm_text_recoit_l_utilisateur_resolu(self):
        bot, guild, actor = _setup()
        user = _FakeUser(2002)
        fetch_user = AsyncMock(return_value=user)
        recu = {}

        def capture(u):
            recu["user"] = u
            return "texte"

        await moderation_service.unban(
            bot, guild=guild, actor=actor, user_id=2002, reason="test", fetch_user=fetch_user,
            render_dm_text=capture,
        )

        self.assertIs(recu["user"], user)
        user.send.assert_awaited_once()

    async def test_sans_render_dm_text_n_essaie_pas_d_envoyer(self):
        bot, guild, actor = _setup()
        user = _FakeUser(2002)
        fetch_user = AsyncMock(return_value=user)

        outcome = await moderation_service.unban(
            bot, guild=guild, actor=actor, user_id=2002, reason="test", fetch_user=fetch_user,
        )

        self.assertFalse(outcome.dm_sent)
        user.send.assert_not_awaited()

    async def test_mp_ferme_n_empeche_pas_le_debannissement(self):
        bot, guild, actor = _setup()
        user = _FakeUser(2002)
        user.send = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "MP fermé"))
        fetch_user = AsyncMock(return_value=user)

        outcome = await moderation_service.unban(
            bot, guild=guild, actor=actor, user_id=2002, reason="test", fetch_user=fetch_user,
            render_dm_text=lambda u: "texte",
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)


class PersistenceFailureNeverUndoesSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_une_exception_de_persistance_laisse_le_debannissement_reussi(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor = _setup(record_sanction=echec_db)
        user = _FakeUser(2002)
        fetch_user = AsyncMock(return_value=user)

        outcome = await moderation_service.unban(
            bot, guild=guild, actor=actor, user_id=2002, reason="test", fetch_user=fetch_user,
        )

        self.assertTrue(outcome.executed, "le débannissement Discord a réussi, executed doit rester True")
        guild.unban.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)


if __name__ == "__main__":
    unittest.main()
