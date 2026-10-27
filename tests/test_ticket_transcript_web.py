"""Regression tests for the private, browser-openable SentriX ticket transcript viewer."""
from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from services import ticket_transcript_links as links
from web import ticket_transcript_viewer as viewer


class FakeDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE tickets (id BIGINT PRIMARY KEY, guild_id BIGINT, "
            "user_id BIGINT, created_at BIGINT, closed_at BIGINT)"
        )
        self.conn.execute(
            "INSERT INTO tickets VALUES (29, 1, 42, 1793124000, 1793127600)"
        )

    async def execute(self, sql, params=()):
        cursor = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cursor

    async def fetchone(self, sql, params=()):
        return self.conn.execute(sql, tuple(params)).fetchone()


def _bot():
    return SimpleNamespace(db=FakeDB(), get_guild=Mock(return_value=SimpleNamespace(name="Support privé")))


async def _publish(bot):
    return await links.publish_link(
        bot, ticket_id=29, guild_id=1, channel_id=456,
        channel_name="ticket-support", viewer_id=42,
        transcript_text="[2026-10-27 18:10] Testeur (42): <script>alert(1)</script>",
        closer_name="Modérateur", close_reason="Résolu",
    )


def test_private_link_is_hashed_and_has_no_query_parameter():
    bot = _bot()
    with patch.dict(os.environ, {"SENTRIX_TRANSCRIPT_PUBLIC_URL": "https://sentrix.example"}):
        url = asyncio.run(_publish(bot))
    parsed = urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.path == "/transcripts"
    assert parsed.query == ""
    token = parsed.fragment
    assert links.TOKEN_RE.fullmatch(token)
    db = bot.db.conn
    stored = db.execute("SELECT token_hash FROM ticket_transcript_links").fetchone()
    assert stored["token_hash"] == hashlib.sha256(token.encode("ascii")).hexdigest()
    assert token not in str(stored)
    result = asyncio.run(links.load_archive(bot, token))
    assert result["viewer_id"] == 42
    assert result["closed_by"] == "Modérateur"
    assert result["archive"]["transcript_text"].endswith("</script>")


def test_expired_token_is_denied():
    bot = _bot()
    with patch.dict(os.environ, {"SENTRIX_TRANSCRIPT_PUBLIC_URL": "https://sentrix.example"}):
        url = asyncio.run(_publish(bot))
    token = urlsplit(url).fragment
    bot.db.conn.execute("UPDATE ticket_transcript_links SET expires_at=1")
    bot.db.conn.commit()
    assert asyncio.run(links.load_archive(bot, token)) is None
    assert asyncio.run(links.load_archive(bot, "not-a-real-token")) is None


def test_viewer_website_and_private_post_end_to_end():
    async def scenario():
        bot = _bot()
        with patch.dict(os.environ, {"SENTRIX_TRANSCRIPT_PUBLIC_URL": "https://sentrix.example"}):
            url = await _publish(bot)
        token = urlsplit(url).fragment
        app = web.Application()
        app["bot"] = bot
        viewer.register_routes(app)
        viewer.register_routes(app)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                response = await client.get("/transcripts")
                assert response.status == 200
                landing = await response.text()
                assert "location.hash" in landing
                assert "/transcripts/view" in landing
                assert "no-store" in response.headers["Cache-Control"]
                assert token not in landing
                response = await client.post("/transcripts/view", json={"token": token})
                assert response.status == 200
                html = await response.text()
                assert "TICKET-0029" in html
                assert "Support privé" in html
                assert "Testeur" in html
                assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
                assert "<script>alert(1)</script>" not in html
                assert response.headers["Referrer-Policy"] == "no-referrer"
                assert response.headers["Cache-Control"].startswith("private, no-store")
                response = await client.post("/transcripts/view", json={"token": "bad"})
                assert response.status == 404
    asyncio.run(scenario())


def test_no_transcript_attachment_in_closure_routes():
    from pathlib import Path
    base = Path(__file__).resolve().parents[1]
    secure = (base / "cogs" / "ticket_claim_security.py").read_text()
    tickets = (base / "cogs" / "tickets.py").read_text()
    assert "file=transcript_file" not in secure
    assert "file=report.transcript_file(transcript_text)" not in secure
    assert "file=ticket_transcript_html.transcript_html_file(" not in secure
    assert "file=ticket_transcript_html.transcript_html_file(" not in tickets
    assert "file=self._transcript_file(channel, transcript_text)" not in tickets
    assert "ticket_transcript_links.publish_link(" in secure
    assert "ticket_transcript_links.publish_link(" in tickets


def test_configured_site_origin_must_use_https():
    with patch.dict(os.environ, {"SENTRIX_TRANSCRIPT_PUBLIC_URL": "http://example.com"}):
        assert links.public_origin() is None
    with patch.dict(os.environ, {"SENTRIX_TRANSCRIPT_PUBLIC_URL": "https://sentrix.example/app"}):
        assert links.public_origin() is None
    with patch.dict(os.environ, {"SENTRIX_TRANSCRIPT_PUBLIC_URL": "https://sentrix.example"}):
        assert links.public_origin() == "https://sentrix.example"
