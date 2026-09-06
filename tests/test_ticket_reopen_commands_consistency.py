"""Deux commandes rouvraient un ticket fermé avec des règles incompatibles :
`+ticket-reopen` (cogs/tickets.py) rouvre tant que `status='ferme'`, sans fenêtre de
temps. `+reopenticket` (cogs/v17_tickets_logs.py) refusait par défaut
("La réouverture n'est pas activée") tant qu'un administrateur n'avait pas explicitement
configuré `+ticketreopenwindow` — alors que `reopen_minutes` ne contrôle en réalité que
la durée de survie du salon avant suppression définitive (auto_delete_v17), pas une
permission de réouverture séparée. Un staff qui ne connaissait que `+reopenticket`
(seule visible dans +help, `+ticket-reopen` étant masquée) se voyait refuser une
réouverture que l'autre commande aurait pourtant acceptée sans problème.

Corrigé en alignant `+reopenticket` sur la même règle que `+ticket-reopen` :
`status='ferme'` suffit. Test d'exécution réel : vraie base SQLite, vrai cog."""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database, now
from cogs.v17_tickets_logs import V17TicketsLogs


class _FakeBot:
    def __init__(self, db: Database):
        self.db = db


class ReopenTicketConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.bot = _FakeBot(self.db)
        self.cog = V17TicketsLogs(self.bot)
        await self.cog.cog_load()

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def _insert_closed_ticket(self, *, guild_id, channel_id, user_id):
        await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, type_id, status, closed_at, created_at) "
            "VALUES (?, ?, ?, 1, 'ferme', ?, 0)",
            (guild_id, channel_id, user_id, now()),
        )
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return row["id"]

    def _fake_ctx(self, guild_id, channel_id):
        channel = SimpleNamespace(
            id=channel_id,
            overwrites_for=lambda member: SimpleNamespace(view_channel=None, send_messages=None, read_message_history=None),
            set_permissions=lambda *a, **k: _noop(),
        )
        guild = SimpleNamespace(id=guild_id, get_member=lambda uid: None)
        return SimpleNamespace(
            guild=guild, channel=channel, author=SimpleNamespace(mention="@staff", id=1),
            interaction=None, send=AsyncMock(),
        )

    async def test_reopenticket_fonctionne_sans_fenetre_configuree(self):
        """C'est exactement le bug rapporté : avant le correctif, ce test échoue
        (le ticket reste 'ferme', message "réouverture non activée"), alors que
        +ticket-reopen aurait accepté exactement la même situation."""
        guild_id, channel_id = 1, 555
        ticket_id = await self._insert_closed_ticket(guild_id=guild_id, channel_id=channel_id, user_id=42)
        # Aucun +ticketreopenwindow configuré : reopen_minutes vaut 0 par défaut (absence de ligne).

        ctx = self._fake_ctx(guild_id, channel_id)
        await self.cog.reopenticket.callback(self.cog, ctx)

        row = await self.db.fetchone("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        self.assertEqual(row["status"], "ouvert")

    async def test_reopenticket_refuse_toujours_un_ticket_deja_ouvert(self):
        guild_id, channel_id = 1, 556
        await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, type_id, status, created_at) VALUES (?, ?, ?, 1, 'ouvert', 0)",
            (guild_id, channel_id, 42),
        )
        ctx = self._fake_ctx(guild_id, channel_id)
        await self.cog.reopenticket.callback(self.cog, ctx)  # ne doit pas planter, juste avertir

    async def test_reopenticket_et_ticket_reopen_acceptent_desormais_la_meme_situation(self):
        """La vraie vérification demandée : les deux commandes doivent maintenant
        prendre la même décision (status='ferme' suffit) pour le même ticket."""
        guild_id = 2
        ticket_id_a = await self._insert_closed_ticket(guild_id=guild_id, channel_id=601, user_id=42)
        ticket_id_b = await self._insert_closed_ticket(guild_id=guild_id, channel_id=602, user_id=43)

        await self.cog.reopenticket.callback(self.cog, self._fake_ctx(guild_id, 601))

        from cogs.tickets import Tickets
        tickets_cog = Tickets.__new__(Tickets)
        tickets_cog.bot = self.bot

        class _Overwrite:
            send_messages = None

        fake_channel = SimpleNamespace(
            id=602,
            overwrites_for=lambda member: _Overwrite(),
            set_permissions=lambda *a, **k: _noop(),
        )
        ctx_b = SimpleNamespace(
            guild=SimpleNamespace(id=guild_id, get_member=lambda uid: None),
            channel=fake_channel,
            interaction=None, send=AsyncMock(),
        )
        await Tickets.ticket_reopen.callback(tickets_cog, ctx_b)

        row_a = await self.db.fetchone("SELECT status FROM tickets WHERE id = ?", (ticket_id_a,))
        row_b = await self.db.fetchone("SELECT status FROM tickets WHERE id = ?", (ticket_id_b,))
        self.assertEqual(row_a["status"], "ouvert")
        self.assertEqual(row_b["status"], "ouvert")


async def _noop():
    return None


if __name__ == "__main__":
    unittest.main()
