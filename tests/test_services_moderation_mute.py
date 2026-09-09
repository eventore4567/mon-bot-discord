"""services/moderation.py::mute — Core V2, Phase 2, troisième commande migrée.

Forme différente de ban()/kick() : durée à valider avant exécution, et MP
envoyé APRÈS le timeout (un membre muet reste joignable, contrairement à
ban/kick) — ces tests verrouillent spécifiquement cet ordre et cette
validation, en plus de l'invariant déjà établi : une exception de persistance
ne doit jamais annuler le succès d'une sanction Discord déjà appliquée."""
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
        self.record_sanction = record_sanction or AsyncMock(return_value=9)


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

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="10m"
        )

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.hierarchy_error)
        target.timeout.assert_not_awaited()


class DurationValidationTests(unittest.IsolatedAsyncioTestCase):
    """La validation de durée est spécifique à mute() — ni ban() ni kick()
    n'en ont besoin, d'où une fonction séparée plutôt qu'un paramètre de plus
    sur _run_sanction_pipeline()."""

    async def test_refuse_une_duree_illisible(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="pas une durée"
        )

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.validation_error)
        self.assertIn("28 jours", outcome.validation_error)
        target.timeout.assert_not_awaited()

    async def test_refuse_une_duree_superieure_a_28_jours(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="30j"
        )

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.validation_error)
        target.timeout.assert_not_awaited()

    async def test_accepte_une_duree_valide(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="10m"
        )

        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.duration_seconds, 600)
        target.timeout.assert_awaited_once()

    async def test_la_hierarchie_est_verifiee_avant_la_duree(self):
        """Une durée invalide ET une hiérarchie invalide -> c'est bien l'erreur
        de hiérarchie qui remonte, jamais un member.timeout() en coulisses."""
        bot, guild, actor, target = _setup(actor_top=1, target_top=10)

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="pas une durée"
        )

        self.assertIsNotNone(outcome.hierarchy_error)
        self.assertIsNone(outcome.validation_error)
        target.timeout.assert_not_awaited()


class DmOrderingTests(unittest.IsolatedAsyncioTestCase):
    """Le test qui verrouille la différence structurelle avec ban()/kick() :
    le MP part APRÈS le timeout, jamais avant."""

    async def test_le_mp_part_apres_le_timeout(self):
        bot, guild, actor, target = _setup()
        ordre: list[str] = []
        target.timeout = AsyncMock(side_effect=lambda *a, **k: ordre.append("timeout"))
        target.send = AsyncMock(side_effect=lambda *a, **k: ordre.append("dm"))

        await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="10m",
            render_dm_text=lambda secs: "Vous êtes muet.",
        )

        self.assertEqual(ordre, ["timeout", "dm"])

    async def test_render_dm_text_recoit_la_duree_validee_en_secondes(self):
        bot, guild, actor, target = _setup()
        recu = {}

        def capture(secs):
            recu["secondes"] = secs
            return "texte"

        await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="1h",
            render_dm_text=capture,
        )

        self.assertEqual(recu["secondes"], 3600)

    async def test_sans_render_dm_text_n_essaie_pas_d_envoyer(self):
        bot, guild, actor, target = _setup()

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="10m",
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        target.send.assert_not_awaited()

    async def test_mp_ferme_n_empeche_pas_le_mute(self):
        bot, guild, actor, target = _setup()
        target.send = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "MP fermé"))

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="10m",
            render_dm_text=lambda secs: "Vous êtes muet.",
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.dm_sent)
        target.timeout.assert_awaited_once()


class PersistenceFailureNeverUndoesSuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_une_exception_de_persistance_laisse_la_sanction_reussie(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(record_sanction=echec_db)

        outcome = await moderation_service.mute(
            bot, guild=guild, actor=actor, target=target, reason="test", duree="10m",
        )

        self.assertTrue(outcome.executed, "le timeout Discord a réussi, executed doit rester True")
        target.timeout.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)


if __name__ == "__main__":
    unittest.main()
