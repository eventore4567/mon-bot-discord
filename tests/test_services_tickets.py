"""services/tickets.py — deux extractions de cogs/tickets.py et
cogs/ticket_claim_security.py, testées directement comme pour les autres
extractions Core V2 (services/economy.py, services/levels.py) :

- count_genuinely_open_tickets() : voir tests/test_ticket_reopen_after_
  channel_deleted.py, qui continue de l'appeler via cogs.tickets (ré-export)
  et reste vert après ce déplacement.
- safe_ticket_log() : la garantie « une panne de log ne casse jamais une
  action de ticket déjà réussie », utilisée par Tickets.close_ticket (après
  remplacement par cogs/ticket_claim_security.py::secure_close_ticket,
  seule implémentation active — confirmée par réassignation de classe sans
  aucun appelant qui la reprendrait ensuite).
- claim_decision()/unclaim_decision() : qui peut prendre en charge ou
  abandonner un ticket, extrait de secure_claim()/secure_unclaim() (les
  seules implémentations de +claim/+unclaim)."""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from database.db import Database
from services import tickets as tickets_service


class _FakeBot:
    def __init__(self, db: Database):
        self.db = db


class _FakeGuild:
    def __init__(self, id_: int, existing_channel_ids: set[int]):
        self.id = id_
        self._existing = existing_channel_ids

    def get_channel(self, channel_id: int):
        return object() if channel_id in self._existing else None


class CountGenuinelyOpenTicketsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.bot = _FakeBot(self.db)

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def _insert_ticket(self, *, guild_id, channel_id, user_id, type_id, status="ouvert"):
        await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, type_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (guild_id, channel_id, user_id, type_id, status),
        )

    async def test_ne_compte_rien_sans_ticket(self):
        guild = _FakeGuild(id_=1, existing_channel_ids=set())
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 0)

    async def test_compte_un_ticket_dont_le_salon_existe(self):
        guild = _FakeGuild(id_=1, existing_channel_ids={999})
        await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7)
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 1)

    async def test_ignore_et_repare_un_ticket_dont_le_salon_a_disparu(self):
        guild = _FakeGuild(id_=1, existing_channel_ids=set())
        await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7)
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 0)
        row = await self.db.fetchone("SELECT status FROM tickets WHERE channel_id = 999")
        self.assertEqual(row["status"], "supprime")

    async def test_ignore_les_tickets_fermes(self):
        guild = _FakeGuild(id_=1, existing_channel_ids={999})
        await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7, status="ferme")
        count = await tickets_service.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)
        self.assertEqual(count, 0)


class SafeTicketLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_retourne_vrai_quand_lenvoi_reussit(self):
        bot = SimpleNamespace()
        guild = SimpleNamespace(id=1)
        embed = discord.Embed(title="Test")
        with patch("services.tickets.log_service.send_log", AsyncMock(return_value=True)) as send_log:
            result = await tickets_service.safe_ticket_log(bot, guild, "ticket_close", embed)
        self.assertTrue(result)
        send_log.assert_awaited_once_with(bot, guild, "ticket_close", embed)

    async def test_retourne_faux_sans_lever_si_la_route_est_desactivee(self):
        bot = SimpleNamespace()
        guild = SimpleNamespace(id=1)
        embed = discord.Embed(title="Test")
        with patch("services.tickets.log_service.send_log", AsyncMock(return_value=False)):
            result = await tickets_service.safe_ticket_log(bot, guild, "ticket_close", embed)
        self.assertFalse(result)

    async def test_avale_toute_exception_sans_jamais_la_laisser_remonter(self):
        """La garantie même de cette fonction : une panne de log (réseau, permissions,
        configuration invalide...) ne doit jamais empêcher l'appelant de continuer —
        c'est ce qui protège Tickets.close_ticket d'un « échec » après une fermeture
        déjà réussie."""
        bot = SimpleNamespace()
        guild = SimpleNamespace(id=1)
        embed = discord.Embed(title="Test")
        with patch(
            "services.tickets.log_service.send_log",
            AsyncMock(side_effect=RuntimeError("Discord indisponible")),
        ):
            result = await tickets_service.safe_ticket_log(bot, guild, "ticket_close", embed)
        self.assertFalse(result)

    async def test_transmet_les_kwargs_optionnels_a_send_log(self):
        bot = SimpleNamespace()
        guild = SimpleNamespace(id=1)
        embed = discord.Embed(title="Test")
        with patch("services.tickets.log_service.send_log", AsyncMock(return_value=True)) as send_log:
            await tickets_service.safe_ticket_log(
                bot, guild, "ticket_close", embed, event_key="abc", identity_name="Membre"
            )
        send_log.assert_awaited_once_with(bot, guild, "ticket_close", embed, event_key="abc", identity_name="Membre")


class ClaimDecisionTests(unittest.TestCase):
    def test_ticket_libre_est_toujours_reclamable(self):
        decision = tickets_service.claim_decision(
            current_claimant_id=None, member_id=1, is_admin=False, is_owner=False
        )
        self.assertEqual(decision, "ok")

    def test_ne_peut_pas_reprendre_sa_propre_prise_en_charge(self):
        """Même un admin ne peut pas « re-réclamer » un ticket qu'il a déjà pris en
        charge — ce cas est distinct de reprendre la charge de QUELQU'UN D'AUTRE."""
        decision = tickets_service.claim_decision(
            current_claimant_id=1, member_id=1, is_admin=True, is_owner=False
        )
        self.assertEqual(decision, "self_already")

    def test_membre_ordinaire_ne_peut_pas_voler_une_prise_en_charge(self):
        decision = tickets_service.claim_decision(
            current_claimant_id=1, member_id=2, is_admin=False, is_owner=False
        )
        self.assertEqual(decision, "taken")

    def test_admin_peut_reprendre_la_charge_dun_autre_membre(self):
        decision = tickets_service.claim_decision(
            current_claimant_id=1, member_id=2, is_admin=True, is_owner=False
        )
        self.assertEqual(decision, "ok")

    def test_proprietaire_du_serveur_peut_reprendre_la_charge_dun_autre_membre(self):
        decision = tickets_service.claim_decision(
            current_claimant_id=1, member_id=2, is_admin=False, is_owner=True
        )
        self.assertEqual(decision, "ok")


class UnclaimDecisionTests(unittest.TestCase):
    def test_ticket_non_pris_en_charge_ne_peut_pas_etre_abandonne(self):
        decision = tickets_service.unclaim_decision(
            current_claimant_id=None, member_id=1, is_admin=False, is_owner=False
        )
        self.assertEqual(decision, "not_claimed")

    def test_le_titulaire_peut_toujours_abandonner_sa_propre_prise_en_charge(self):
        decision = tickets_service.unclaim_decision(
            current_claimant_id=1, member_id=1, is_admin=False, is_owner=False
        )
        self.assertEqual(decision, "ok")

    def test_membre_ordinaire_ne_peut_pas_abandonner_la_prise_en_charge_dun_autre(self):
        decision = tickets_service.unclaim_decision(
            current_claimant_id=1, member_id=2, is_admin=False, is_owner=False
        )
        self.assertEqual(decision, "forbidden")

    def test_admin_peut_forcer_labandon_de_la_prise_en_charge_dun_autre(self):
        decision = tickets_service.unclaim_decision(
            current_claimant_id=1, member_id=2, is_admin=True, is_owner=False
        )
        self.assertEqual(decision, "ok")

    def test_proprietaire_du_serveur_peut_forcer_labandon_de_la_prise_en_charge_dun_autre(self):
        decision = tickets_service.unclaim_decision(
            current_claimant_id=1, member_id=2, is_admin=False, is_owner=True
        )
        self.assertEqual(decision, "ok")


if __name__ == "__main__":
    unittest.main()
