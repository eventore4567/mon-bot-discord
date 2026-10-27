"""Régressions du rendu HTML des transcripts SentriX."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock

from services.ticket_transcript_html import (
    parse_transcript,
    render_transcript_html,
    resolve_ticket_recipient,
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

    def test_dm_sends_site_link_without_html_attachment(self):
        guild = SimpleNamespace(name="Serveur test")
        channel = SimpleNamespace(name="ticket-29", guild=guild)
        owner = SimpleNamespace(send=AsyncMock())
        asyncio.run(send_closure_dm(
            owner, guild, channel, self.SOURCE,
            ticket_id=29, created_at=1793124000, closed_at=1793127600,
            closer="Staff", reason="Résolu",
            transcript_url="https://sentrix.example/transcripts#private-link-123",
        ))
        owner.send.assert_awaited_once()
        kwargs = owner.send.call_args.kwargs
        import discord
        from utils.premium_log_banners import BANNER_FILENAME
        self.assertNotIn("embed", kwargs)
        self.assertEqual(kwargs["file"].filename, BANNER_FILENAME)
        self.assertIsInstance(kwargs["view"], discord.ui.LayoutView)
        self.assertEqual(len(kwargs["view"].children), 1)
        card = kwargs["view"].children[0]
        self.assertIsInstance(card, discord.ui.Container)
        self.assertTrue(any(isinstance(item, discord.ui.MediaGallery) for item in card.children))
        body = "\\n".join(
            item.content for item in card.children
            if isinstance(item, discord.ui.TextDisplay)
        )
        self.assertIn("TICKET-0029", body)
        self.assertIn("Serveur test", body)
        section = next(item for item in card.children if isinstance(item, discord.ui.Section))
        self.assertIn("https://sentrix.example/transcripts#", section.children[0].content)
        self.assertEqual(section.accessory.label, "Ouvrir la transcription")
        self.assertEqual(section.accessory.style, discord.ButtonStyle.link)
        self.assertIn("https://sentrix.example/transcripts#", section.accessory.url)
        kwargs["file"].close()

    def test_uncached_guild_member_is_fetched_and_dm_can_be_sent(self):
        member = SimpleNamespace(id=55, send=AsyncMock())
        guild = SimpleNamespace(
            get_member=Mock(return_value=None),
            fetch_member=AsyncMock(return_value=member),
        )
        bot = SimpleNamespace(get_user=Mock(), fetch_user=AsyncMock())
        resolved_member, user = asyncio.run(resolve_ticket_recipient(bot, guild, 55))
        self.assertIs(resolved_member, member)
        self.assertIs(user, member)
        guild.fetch_member.assert_awaited_once_with(55)
        bot.get_user.assert_not_called()
        bot.fetch_user.assert_not_awaited()

    def test_former_member_can_still_receive_transcript(self):
        response = Mock(status=404, reason="Not Found")
        guild = SimpleNamespace(
            get_member=Mock(return_value=None),
            fetch_member=AsyncMock(
                side_effect=__import__("discord").NotFound(response, "Unknown Member")
            ),
        )
        user = SimpleNamespace(id=55, send=AsyncMock())
        bot = SimpleNamespace(
            get_user=Mock(return_value=None),
            fetch_user=AsyncMock(return_value=user),
        )
        resolved_member, recipient = asyncio.run(resolve_ticket_recipient(bot, guild, 55))
        self.assertIsNone(resolved_member)
        self.assertIs(recipient, user)
        bot.fetch_user.assert_awaited_once_with(55)
