"""Non-destructive ticket panel presentation and migration checks."""

import os
import struct
import tempfile
import unittest
import zlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from utils.ticket_panel_design import SlimTicketPanel, thin_banner_png


def _panel(**overrides):
    row = {
        "id": 42,
        "guild_id": 1,
        "title": "Assistance",
        "description": "Contactez notre équipe.",
        "color": 0x7658E8,
        "image_url": None,
        "thumbnail_url": None,
        "footer_text": "Service client",
        "banner_enabled": 1,
    }
    row.update(overrides)
    return row


class TicketPanelDesignTests(unittest.TestCase):
    def test_banner_is_valid_four_pixel_png(self):
        data = thin_banner_png(0x7658E8)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (960, 4))
        idat_position = data.index(b"IDAT")
        compressed_length = struct.unpack(">I", data[idat_position - 4:idat_position])[0]
        raw = zlib.decompress(data[idat_position + 4:idat_position + 4 + compressed_length])
        self.assertEqual(len(raw), height * (1 + 3 * width))

    def test_banner_can_be_disabled_without_erasing_text(self):
        pane = SlimTicketPanel(_panel(banner_enabled=0))
        self.assertEqual(pane.fichiers(), [])
        self.assertEqual(len(pane.children), 1)
        container = pane.children[0]
        self.assertEqual(len(container.children), 2)
        text = " ".join(getattr(child, "content", "") for child in container.children)
        self.assertIn("Assistance", text)
        self.assertIn("Contactez notre équipe.", text)
        self.assertIn("Service client", text)

    def test_banner_asset_is_one_attachment(self):
        pane = SlimTicketPanel(_panel())
        files = pane.fichiers()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, "sentrix-ticket-strip.png")
        for file in files:
            file.close()


class TicketPanelMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_panel_settings_survive_banner_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Database(os.path.join(temp, "test.sqlite"))
            await db.connect()
            try:
                await db.execute(
                    "INSERT INTO ticket_panels_v2 (guild_id,name,title,description,color,enabled) "
                    "VALUES (?,?,?,?,?,?)",
                    (1, "Support", "Un titre perso", "Une description perso", 0xFF00AA, 0),
                )
                row = await db.fetchone(
                    "SELECT * FROM ticket_panels_v2 WHERE guild_id=?", (1,)
                )
                self.assertEqual(row["title"], "Un titre perso")
                self.assertEqual(row["description"], "Une description perso")
                self.assertEqual(row["color"], 0xFF00AA)
                self.assertEqual(row["enabled"], 0)
                self.assertEqual(row["banner_enabled"], 1)
            finally:
                await db._conn.close()


if __name__ == "__main__":
    unittest.main()
