"""Régressions du rendu HTML des transcripts SentriX."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock

from services.ticket_transcript_html import (
    parse_transcript,
    render_transcript_html,
    send_closure_dm,
    transcript_html_file,
)


class TicketTranscriptHTMLTests(TestCase):
    SOURCE = (
        "[2026-10-27 18:10] Alice (123): Bonjour\n"
        "encore un texte\n"
        "  [Pièce jointe] https://cdn.discordapp.com/attachments/123/a.png\n"
        "[2026-10-27 18:11] Modérateur (456): Réponse"
    )

    def test_messages_multiline_and_attachments(self):
        messages = parse_transcript(self.SOURCE)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], ["Bonjour", "encore un texte"])
        self.assertEqual(messages[0]["attachments"], [
            "https://cdn.discordapp.com/attachments/123/a.png"
        ])

    def test_standalone_html_page(self):
        html = render_transcript_html(
            self.SOURCE, guild_name="Serveur test", ticket_label="TICKET-0029",
            subject="Support", created_at=1793124000, closed_at=1793127600,
            closed_by="Modérateur", close_reason="Résolu",
        )
        self.assertIn("<!doctype html>", html)
        self.assertIn('lang="fr"', html)
        self.assertIn("TICKET-0029", html)
        self.assertIn("Serveur test", html)
        self.assertIn("Alice", html)
        self.assertIn("Modérateur", html)
        self.assertIn("Messages", html)
        self.assertIn(">2</span>", html)
        self.assertIn("Résolu", html)
        self.assertIn("rel=\"noopener noreferrer\"", html)
        self.assertIn("Message", html)

    def test_escapes_untrusted_message_and_fields(self):
        source = "[2026-10-27 18:10] <img src=x onerror=alert(1)> (1): <script>alert(1)</script>"
        html = render_transcript_html(
            source, guild_name="<b>bad</b>", ticket_label="TICKET-1",
            close_reason="<a href='javascript:x'>", closed_by="<bad>",
        )
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<b>bad</b>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;", html)
        self.assertIn("&lt;bad&gt;", html)
        self.assertNotIn("<a href='javascript:", html)

    def test_blocks_malicious_attachment_scheme(self):
        source = "[2026-10-27 18:10] Alice (1): bonjour\n  [Pièce jointe] javascript:alert(1)"
        html = render_transcript_html(
            source, guild_name="Test", ticket_label="TICKET-1",
        )
        self.assertIn("Pièce jointe indisponible", html)
        self.assertNotIn('href="javascript:', html)

    def test_html_file_extension(self):
        guild = SimpleNamespace(name="Serveur")
        channel = SimpleNamespace(name="ticket-support", guild=guild)
        file = transcript_html_file(channel, self.SOURCE, ticket_id=29)
        self.assertEqual(file.filename, "TICKET-0029.html")
        self.assertIn(b"<!doctype html>", file.fp.getvalue())
        file.close()

    def test_dm_sends_one_embed_and_html_file(self):
        guild = SimpleNamespace(name="Serveur test")
        channel = SimpleNamespace(name="ticket-29", guild=guild)
        owner = SimpleNamespace(send=AsyncMock())
        asyncio.run(send_closure_dm(
            owner, guild, channel, self.SOURCE,
            ticket_id=29, created_at=1793124000, closed_at=1793127600,
            closer="Staff", reason="Résolu",
        ))
        owner.send.assert_awaited_once()
        kwargs = owner.send.call_args.kwargs
        self.assertEqual(kwargs["file"].filename, "TICKET-0029.html")
        self.assertEqual(kwargs["embed"].title, "Transcription — TICKET-0029")
        self.assertEqual(len(kwargs["embed"].fields), 4)
        kwargs["file"].close()
