"""services/moderation.py::warn — Core V2, Phase 2, sixième commande migrée.

Forme la plus large : pas UNE sanction mais potentiellement DEUX (l'avertissement,
toujours ; un bannissement automatique par seuil, conditionnel, au nom du BOT et
non de l'acteur), plus des effets annexes (comptage, rôle automatique). Ces tests
verrouillent : l'ordre des étapes, le fail-soft du comptage ET des deux dossiers
(avertissement / bannissement automatique) sans jamais annuler une écriture ou
une action Discord déjà réussie, et le comportement inchangé du rôle automatique
(seule discord.HTTPException est tolérée)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from services import moderation as moderation_service


class _FakeRole:
    def __init__(self, position: int, *, mention="@Role"):
        self.position = position
        self.mention = mention

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)


class _FakeMember:
    def __init__(self, id, *, top_role_position, guild=None, roles=None):
        self.id = id
        self.top_role = _FakeRole(top_role_position)
        self.guild = guild
        self.roles = roles if roles is not None else []
        self.send = AsyncMock()
        self.add_roles = AsyncMock()

    def __str__(self):
        return f"membre#{self.id}"


class _FakeClientUser:
    def __init__(self, id):
        self.id = id

    def __str__(self):
        return "SentriX"


class _FakeGuild:
    def __init__(self, id, *, owner_id, me_top_role_position):
        self.id = id
        self.owner_id = owner_id
        self.me = _FakeMember(999, top_role_position=me_top_role_position)
        self.ban = AsyncMock()


class _FakeDB:
    def __init__(self, *, record_sanction=None, execute=None, fetchall=None):
        self.record_sanction = record_sanction or AsyncMock(return_value=5)
        self.execute = execute or AsyncMock()
        self.fetchall = fetchall or AsyncMock(return_value=[{"id": 1}])


class _FakeBot:
    def __init__(self, *, record_sanction=None, execute=None, fetchall=None, user_id=42):
        self.db = _FakeDB(record_sanction=record_sanction, execute=execute, fetchall=fetchall)
        self.user = _FakeClientUser(user_id)


def _setup(*, actor_top=10, target_top=1, owner_id=1, bot_top=20, record_sanction=None, execute=None, fetchall=None):
    guild = _FakeGuild(555, owner_id=owner_id, me_top_role_position=bot_top)
    actor = _FakeMember(1001, top_role_position=actor_top, guild=guild)
    target = _FakeMember(2002, top_role_position=target_top, guild=guild)
    bot = _FakeBot(record_sanction=record_sanction, execute=execute, fetchall=fetchall)
    return bot, guild, actor, target


class HierarchyRejectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuse_une_cible_avec_role_superieur(self):
        bot, guild, actor, target = _setup(actor_top=5, target_top=10)

        outcome = await moderation_service.warn(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertFalse(outcome.executed)
        self.assertIsNotNone(outcome.hierarchy_error)
        bot.db.execute.assert_not_awaited()


class BasicWarnTests(unittest.IsolatedAsyncioTestCase):
    async def test_avertissement_reussi_enregistre_et_compte(self):
        bot, guild, actor, target = _setup(fetchall=AsyncMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}]))

        outcome = await moderation_service.warn(bot, guild=guild, actor=actor, target=target, reason="spam")

        self.assertTrue(outcome.executed)
        self.assertEqual(outcome.total_warnings, 3)
        self.assertEqual(outcome.case_number, 5)
        bot.db.execute.assert_awaited_once()
        args = bot.db.execute.await_args.args
        self.assertIn("warnings", args[0])
        self.assertEqual(args[1], (guild.id, target.id, actor.id, "spam", args[1][4]))

    async def test_echec_du_comptage_n_empeche_pas_l_avertissement(self):
        echec_fetchall = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(fetchall=echec_fetchall)

        outcome = await moderation_service.warn(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertTrue(outcome.executed, "l'INSERT a réussi, executed doit rester True")
        bot.db.execute.assert_awaited_once()
        self.assertIsNone(outcome.total_warnings)
        self.assertIsNotNone(outcome.count_error)

    async def test_echec_du_dossier_n_empeche_pas_l_avertissement(self):
        echec_db = AsyncMock(side_effect=RuntimeError("disque plein"))
        bot, guild, actor, target = _setup(record_sanction=echec_db)

        outcome = await moderation_service.warn(bot, guild=guild, actor=actor, target=target, reason="test")

        self.assertTrue(outcome.executed)
        bot.db.execute.assert_awaited_once()
        self.assertIsNone(outcome.case_number)
        self.assertIsNotNone(outcome.persistence_error)

    async def test_l_insert_qui_echoue_propage_vraiment(self):
        """Contrairement aux étapes suivantes, l'INSERT initial n'a encore
        rien fait réussir — le laisser remonter est le comportement honnête
        et existant (rien à protéger, rien n'a été fait)."""
        bot, guild, actor, target = _setup(execute=AsyncMock(side_effect=RuntimeError("disque plein")))

        with self.assertRaises(RuntimeError):
            await moderation_service.warn(bot, guild=guild, actor=actor, target=target, reason="test")


class WarnRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_attribue_le_role_si_absent(self):
        bot, guild, actor, target = _setup()
        role = _FakeRole(3)

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", warn_role=role,
        )

        self.assertTrue(outcome.role_assigned)
        self.assertIsNone(outcome.role_error)
        target.add_roles.assert_awaited_once()

    async def test_n_essaie_pas_si_le_role_est_deja_present(self):
        bot, guild, actor, target = _setup()
        role = _FakeRole(3)
        target.roles = [role]

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", warn_role=role,
        )

        self.assertFalse(outcome.role_assigned)
        self.assertIsNone(outcome.role_error)
        target.add_roles.assert_not_awaited()

    async def test_httpexception_sur_le_role_est_toleree(self):
        bot, guild, actor, target = _setup()
        role = _FakeRole(3)
        target.add_roles = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "refusé"))

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", warn_role=role,
        )

        self.assertTrue(outcome.executed)
        self.assertFalse(outcome.role_assigned)
        self.assertIsNotNone(outcome.role_error)


class AutoBanThresholdTests(unittest.IsolatedAsyncioTestCase):
    async def test_pas_de_ban_automatique_sous_le_seuil(self):
        bot, guild, actor, target = _setup(fetchall=AsyncMock(return_value=[{"id": 1}]))

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", ban_threshold=3,
        )

        self.assertFalse(outcome.auto_ban_triggered)
        guild.ban.assert_not_awaited()

    async def test_pas_de_ban_automatique_si_seuil_desactive(self):
        bot, guild, actor, target = _setup(fetchall=AsyncMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}]))

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", ban_threshold=0,
        )

        self.assertFalse(outcome.auto_ban_triggered)
        guild.ban.assert_not_awaited()

    async def test_pas_de_ban_automatique_si_comptage_inconnu(self):
        """Le seuil ne peut pas être évalué sans savoir combien
        d'avertissements le membre a au total — fail closed."""
        bot, guild, actor, target = _setup(fetchall=AsyncMock(side_effect=RuntimeError("disque plein")))

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", ban_threshold=3,
        )

        self.assertFalse(outcome.auto_ban_triggered)
        guild.ban.assert_not_awaited()

    async def test_ban_automatique_declenche_au_seuil_agit_au_nom_du_bot(self):
        bot, guild, actor, target = _setup(
            fetchall=AsyncMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}]),
        )

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", ban_threshold=3,
        )

        self.assertTrue(outcome.auto_ban_triggered)
        self.assertTrue(outcome.auto_ban_executed)
        guild.ban.assert_awaited_once()
        self.assertEqual(bot.db.record_sanction.await_args_list[-1].args[2], bot.user.id)

    async def test_echec_discord_du_ban_automatique_est_rapporte(self):
        bot, guild, actor, target = _setup(fetchall=AsyncMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}]))
        guild.ban = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "refusé"))

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", ban_threshold=3,
        )

        self.assertTrue(outcome.auto_ban_triggered)
        self.assertIsNone(outcome.auto_ban_hierarchy_error)
        self.assertIsNotNone(outcome.auto_ban_execution_error)
        self.assertFalse(outcome.auto_ban_executed)

    async def test_echec_du_dossier_du_ban_automatique_n_empeche_pas_le_ban(self):
        appels = {"n": 0}

        async def record_sanction(*args, **kwargs):
            appels["n"] += 1
            if appels["n"] == 1:
                return 5  # dossier de l'avertissement : succès
            raise RuntimeError("disque plein")  # dossier du ban automatique : échec

        bot, guild, actor, target = _setup(
            fetchall=AsyncMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}]),
            record_sanction=AsyncMock(side_effect=record_sanction),
        )

        outcome = await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", ban_threshold=3,
        )

        self.assertTrue(outcome.auto_ban_executed, "le bannissement Discord a réussi, doit rester True")
        guild.ban.assert_awaited_once()
        self.assertIsNone(outcome.auto_ban_case_number)
        self.assertIsNotNone(outcome.auto_ban_persistence_error)

    async def test_le_mp_du_ban_automatique_part_avant_le_bannissement(self):
        bot, guild, actor, target = _setup(fetchall=AsyncMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}]))
        ordre: list[str] = []
        guild.ban = AsyncMock(side_effect=lambda *a, **k: ordre.append("ban"))
        target.send = AsyncMock(side_effect=lambda *a, **k: ordre.append("dm"))

        await moderation_service.warn(
            bot, guild=guild, actor=actor, target=target, reason="test", ban_threshold=3,
            render_ban_dm_text=lambda: "Vous avez été banni.",
        )

        self.assertEqual(ordre, ["dm", "ban"])


if __name__ == "__main__":
    unittest.main()
