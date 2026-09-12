"""services/moderation.py::tempban — Core V2, Phase 2, cinquième commande
migrée.

Forme bespoke (comme mute()) : durée à valider, MP envoyé AVANT l'exécution
(comme ban/kick — un membre banni n'est plus joignable, même temporairement),
et DEUX persistances indépendantes (dossier de sanction + levée automatique
programmée dans tempactions). Ces tests verrouillent l'ordre, l'absence de
plafond de durée (contrairement à mute, borné par le timeout natif Discord),
et l'invariant déjà établi : une exception de persistance — sur l'UNE ou
L'AUTRE des deux écritures — ne doit jamais annuler le succès d'une sanction
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

    def __str__(self):
        return f"membre#{self.id}"


class _FakeGuild:
    def __init__(self, id, *, owner_id, me_top_role_position):
        self.id = id
        self.owner_id = owner_id
        self.me = _FakeMember(999, top_role_position=me_top_role_position)
        self.ban = AsyncMock()


class _FakeDB:
    def __init__(self, *, record_sanction=None, execute=None):
        self.record_sanction = record_sanction or AsyncMock(return_value=7)
        self.execute = execute or AsyncMock()


class _FakeBot:
    def __init__(self, *, record_sanction=None, execute=None):
        self.db = _FakeDB(record_sanction=record_sanction, execute=execute)


def _setup(*, actor_top=10, target_top=1, owner_id=1, bot_top=20, record_sanction=None, execute=None):
    guild = _FakeGuild(555, owner_id=owner_id, me_top_role_position=bot_top)
    actor = _FakeMember(1001, top_role_position=actor_top, guild=guild)
    target = _FakeMember(2002, top_role_position=target_top, guild=guild)
    bot = _FakeBot(record_sanction=record_sanction, execute=execute)
    return bot, guild, actor, target


class HierarchyRejectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuse_une_cible_avec_role_superieur(self):
        bot, guild, actor, target = _setup(actor_top=5, target_top=10)

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h"
        )

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.hierarchy_error)
        guild.ban.assert_not_awaited()


class DurationValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuse_une_duree_illisible(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="pas une durée"
        )

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.validation_error)
        guild.ban.assert_not_awaited()

    async def test_accepte_une_duree_superieure_a_28_jours(self):
        """Contrairement à mute() (timeout natif Discord, plafonné à 28 jours),
        tempban n'a pas de plafond — ce n'est qu'un bannissement classique
        dont la levée est reprogrammée par check_tempactions."""
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="60j"
        )

        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.duration_seconds, 60 * 86400)
        guild.ban.assert_awaited_once()

    async def test_la_hierarchie_est_verifiee_avant_la_duree(self):
        bot, guild, actor, target = _setup(actor_top=1, target_top=10)

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="pas une durée"
        )

        self.assertIsNotNone(outcome.hierarchy_error)
        self.assertIsNone(outcome.validation_error)
        guild.ban.assert_not_awaited()


class DmOrderingTests(unittest.IsolatedAsyncioTestCase):
    """Contrairement à mute()/unmute() (MP après), le MP part AVANT
    l'exécution — même rationale que ban()/kick() : la délivrabilité."""

    async def test_le_mp_part_avant_le_bannissement(self):
        bot, guild, actor, target = _setup()
        ordre: list[str] = []
        guild.ban = AsyncMock(side_effect=lambda *a, **k: ordre.append("ban"))
        target.send = AsyncMock(side_effect=lambda *a, **k: ordre.append("dm"))

        await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
            render_dm_text=lambda secs: "Vous êtes banni temporairement.",
        )

        self.assertEqual(ordre, ["dm", "ban"])

    async def test_render_dm_text_recoit_la_duree_validee_en_secondes(self):
        bot, guild, actor, target = _setup()
        recu = {}

        def capture(secs):
            recu["secondes"] = secs
            return "texte"

        await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="2h",
            render_dm_text=capture,
        )

        self.assertEqual(recu["secondes"], 7200)

    async def test_sans_render_dm_text_n_essaie_pas_d_envoyer(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        target.send.assert_not_awaited()

    async def test_mp_ferme_n_empeche_pas_le_bannissement(self):
        bot, guild, actor, target = _setup()
        target.send = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "MP fermé"))

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
            render_dm_text=lambda secs: "Vous êtes banni temporairement.",
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        guild.ban.assert_awaited_once()


class DualPersistenceTests(unittest.IsolatedAsyncioTestCase):
    """La particularité de tempban : DEUX écritures indépendantes, chacune
    protégée séparément."""

    async def test_les_deux_ecritures_reussissent(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
        )

        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.case_number, 7)
        self.assertIsNone(outcome.persistence_error)
        self.assertIsNone(outcome.tempaction_error)
        bot.db.execute.assert_awaited_once()
        args = bot.db.execute.await_args.args
        self.assertIn("tempactions", args[0])
        self.assertEqual(args[1], (guild.id, target.id, "ban", args[1][3]))

    async def test_echec_du_dossier_de_sanction_n_empeche_pas_la_programmation_de_la_levee(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(record_sanction=echec_db)

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
        )

        self.assertTrue(outcome.executed, "le bannissement Discord a réussi, executed doit rester True")
        guild.ban.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)
        self.assertIsNone(outcome.tempaction_error)
        bot.db.execute.assert_awaited_once()

    async def test_echec_de_la_programmation_de_la_levee_n_empeche_pas_le_dossier(self):
        echec_execute = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(execute=echec_execute)

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
        )

        self.assertTrue(outcome.executed, "le bannissement Discord a réussi, executed doit rester True")
        guild.ban.assert_awaited_once()
        self.assertEqual(outcome.case_number, 7)
        self.assertIsNone(outcome.persistence_error)
        self.assertIsNotNone(outcome.tempaction_error)

    async def test_les_deux_ecritures_peuvent_echouer_sans_annuler_le_bannissement(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        echec_execute = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(record_sanction=echec_db, execute=echec_execute)

        outcome = await moderation_service.tempban(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
        )

        self.assertTrue(outcome.executed)
        guild.ban.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)
        self.assertIsNotNone(outcome.tempaction_error)


if __name__ == "__main__":
    unittest.main()
