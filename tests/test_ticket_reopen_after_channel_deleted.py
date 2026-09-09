"""Reproduit puis vérifie la correction du bug rapporté : après suppression du salon
d'un ticket (fermeture manuelle par un staff, purge anti-nuke...), l'utilisateur ne
pouvait plus jamais rouvrir un nouveau ticket du même type, car la vérification
"a-t-il déjà un ticket ouvert" ne regardait que la colonne `status` en base, jamais si
le salon Discord existait encore. Tests d'exécution réels : vraie base SQLite temporaire,
vrai cycle écriture/lecture, pas seulement une lecture de code source.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from cogs import tickets


class _FakeBot:
    def __init__(self, db: Database):
        self.db = db


class _FakeGuild:
    """Simule un serveur où un des deux salons de ticket a été supprimé."""

    def __init__(self, id_: int, existing_channel_ids: set[int]):
        self.id = id_
        self._existing = existing_channel_ids

    def get_channel(self, channel_id: int):
        return object() if channel_id in self._existing else None


class TicketReopenAfterChannelDeletedTests(unittest.IsolatedAsyncioTestCase):
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
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return row["id"]

    async def test_ticket_dont_le_salon_a_disparu_ne_bloque_plus_la_reouverture(self):
        """C'est EXACTEMENT le bug rapporté : sans le correctif, ce test échoue avec
        open_count == 1 (le ticket fantôme bloque indéfiniment une nouvelle ouverture)."""
        guild = _FakeGuild(id_=1, existing_channel_ids=set())  # le salon n'existe plus
        ticket_id = await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7)

        open_count = await tickets.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)

        self.assertEqual(open_count, 0, "un ticket dont le salon n'existe plus ne doit jamais bloquer une réouverture")

        row = await self.db.fetchone("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        self.assertEqual(row["status"], "supprime", "la ligne fantôme doit être auto-réparée, pas laissée à 'ouvert'")

    async def test_ticket_dont_le_salon_existe_bloque_toujours_normalement(self):
        """Non-régression : un ticket réellement ouvert doit continuer à compter et à
        bloquer une seconde ouverture au-delà de la limite."""
        guild = _FakeGuild(id_=1, existing_channel_ids={999})
        ticket_id = await self._insert_ticket(guild_id=1, channel_id=999, user_id=42, type_id=7)

        open_count = await tickets.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)

        self.assertEqual(open_count, 1)
        row = await self.db.fetchone("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        self.assertEqual(row["status"], "ouvert", "un ticket réellement ouvert ne doit jamais être touché")

    async def test_seul_le_ticket_de_l_utilisateur_et_du_type_concernes_est_compte(self):
        guild = _FakeGuild(id_=1, existing_channel_ids={111, 222})
        await self._insert_ticket(guild_id=1, channel_id=111, user_id=42, type_id=7)
        await self._insert_ticket(guild_id=1, channel_id=222, user_id=999, type_id=7)  # autre utilisateur

        open_count = await tickets.count_genuinely_open_tickets(self.bot, guild, user_id=42, type_id=7)

        self.assertEqual(open_count, 1)

    async def test_on_guild_channel_delete_repare_immediatement_le_ticket_fantome(self):
        """Le listener proactif : dès que Discord notifie la suppression du salon, la
        ligne doit être réparée tout de suite, sans attendre qu'un nouveau ticket soit
        tenté."""
        cog = tickets.Tickets.__new__(tickets.Tickets)
        cog.bot = self.bot
        ticket_id = await self._insert_ticket(guild_id=1, channel_id=555, user_id=42, type_id=7)

        fake_channel = type("FakeChannel", (), {"id": 555})()
        await tickets.Tickets.on_guild_channel_delete(cog, fake_channel)

        row = await self.db.fetchone("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        self.assertEqual(row["status"], "supprime")

    async def test_on_guild_channel_delete_ignore_les_salons_qui_ne_sont_pas_des_tickets(self):
        cog = tickets.Tickets.__new__(tickets.Tickets)
        cog.bot = self.bot
        ticket_id = await self._insert_ticket(guild_id=1, channel_id=555, user_id=42, type_id=7)

        fake_channel = type("FakeChannel", (), {"id": 777})()  # un salon quelconque, pas un ticket
        await tickets.Tickets.on_guild_channel_delete(cog, fake_channel)

        row = await self.db.fetchone("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        self.assertEqual(row["status"], "ouvert", "un salon sans rapport ne doit jamais toucher un ticket existant")


if __name__ == "__main__":
    unittest.main()
