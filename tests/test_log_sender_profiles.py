"""Régression des mini-profils : URL sécurisée et fallback des boutons Discord."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from utils import log_sender_profiles as profiles


def test_profile_validation_rejects_bad_names_and_private_urls():
    assert profiles.validate_profile(
        "Joins & Leaves", "https://cdn.discordapp.com/attachments/avatar.png"
    ) == ("Joins & Leaves", "https://cdn.discordapp.com/attachments/avatar.png")
    for url in (
        "http://example.com/avatar.png",
        "https://localhost/test",
        "https://127.0.0.1/photo.png",
        "https://[::1]/private",
        "file:///etc/passwd",
        "https://user:secret@example.com/a",
        "https://example.com/a#token",
    ):
        with pytest.raises(ValueError):
            profiles.validate_profile("Joins & Leaves", url)
    with pytest.raises(ValueError):
        profiles.validate_profile("@everyone", "")
    with pytest.raises(ValueError):
        profiles.validate_profile("", "")


def test_interactive_action_buttons_force_regular_bot_delivery():
    link = discord.ui.View(timeout=None)
    link.add_item(discord.ui.Button(label="Voir le salon",
                                    style=discord.ButtonStyle.link,
                                    url="https://discord.com/channels/123/456"))
    assert profiles.is_noninteractive(link)
    interactive = discord.ui.View(timeout=None)
    interactive.add_item(discord.ui.Button(label="Transcription privée",
                                          custom_id="sentrix:ticket:transcript:81"))
    assert not profiles.is_noninteractive(interactive)
    select = discord.ui.View(timeout=None)
    select.add_item(discord.ui.Select(
        options=[discord.SelectOption(label="Support", value="s")],
        custom_id="ticket_open_select:81",
    ))
    assert not profiles.is_noninteractive(select)


async def _exercise_profile_storage(monkeypatch):
    class Db:
        def __init__(self):
            self.queries = []
            self.row = None

        async def execute(self, sql, values=()):
            self.queries.append((sql, values))
            if "INSERT INTO log_sender_profiles" in sql:
                self.row = {"enabled": values[2], "display_name": values[3],
                            "avatar_url": values[4]}

        async def fetchone(self, sql, values=()):
            self.queries.append((sql, values))
            return self.row

    db = Db()
    bot = SimpleNamespace(db=db)
    monkeypatch.setattr(profiles, "_schema_ready", set())
    monkeypatch.setattr(profiles, "_profile_cache", {})
    out = await profiles.set_profile(bot, 1234, "members",
                                     enabled=True, display_name="Joins & Leaves",
                                     avatar_url="https://cdn.discordapp.com/avatar.png")
    assert out["enabled"]
    got = await profiles.get_profile(bot, 1234, "members")
    assert got["display_name"] == "Joins & Leaves"
    assert len([q for q, _ in db.queries if "CREATE TABLE" in q]) == 1
    with pytest.raises(ValueError):
        await profiles.set_profile(bot, 1234, "not-a-log", enabled=True,
                                   display_name="Other", avatar_url="")


def test_profiles_are_per_guild_and_category(monkeypatch):
    asyncio.run(_exercise_profile_storage(monkeypatch))


async def _exercise_no_bad_interactions(monkeypatch):
    async def forbidden_send(*args, **kwargs):
        raise AssertionError("Should never use an incoming webhook for interactive buttons")
    monkeypatch.setattr(profiles, "_webhook", forbidden_send)
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Fermer", custom_id="close:1"))
    out = await profiles.send_with_profile(
        SimpleNamespace(), view, [], {"enabled": True, "display_name": "Support"},
        allowed_mentions=discord.AllowedMentions.none()
    )
    assert out is None


def test_interactive_logs_do_not_use_incoming_webhook(monkeypatch):
    asyncio.run(_exercise_no_bad_interactions(monkeypatch))
