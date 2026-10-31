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
    assert got["display_name"] == "Arrivées & Départs"
    assert got["enabled"] is True
    assert len([q for q, _ in db.queries if "CREATE TABLE" in q]) == 1
    with pytest.raises(ValueError):
        await profiles.set_profile(bot, 1234, "not-a-log", enabled=True,
                                   display_name="Other", avatar_url="")


def test_old_profile_settings_do_not_override_automatic_log_identity(monkeypatch):
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


def test_auto_profile_is_enabled_without_a_database_or_setup():
    bot = SimpleNamespace(user=SimpleNamespace(
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/icons/sentrix.png")
    ))
    m = asyncio.run(profiles.get_profile(bot, 1, "members"))
    t = asyncio.run(profiles.get_profile(bot, 2, "tickets"))
    assert m == {"enabled": True, "display_name": "Arrivées & Départs",
                 "avatar_url": "https://cdn.discordapp.com/icons/sentrix.png"}
    assert t["enabled"] is True and t["display_name"] == "Tickets"


def test_custom_embed_sender_uses_webhook(monkeypatch):
    class Hook:
        async def send(self, **kwargs):
            assert kwargs["username"] == "Annonces"
            assert kwargs["avatar_url"] == "https://cdn.discordapp.com/announcement.png"
            assert kwargs["wait"] is True
            return SimpleNamespace(id=1234)
    async def get_hook(_channel):
        return Hook()
    monkeypatch.setattr(profiles, "_webhook", get_hook)
    result = asyncio.run(profiles.send_embed_with_identity(
        SimpleNamespace(), sender_name="Annonces",
        sender_avatar_url="https://cdn.discordapp.com/announcement.png",
        content=None, embed=discord.Embed(title="Exemple"),
    ))
    assert result.id == 1234



async def _exercise_application_owned_interactive_webhooks(monkeypatch):
    """Never drop buttons; owned webhooks may send interactive V2 layouts."""
    class FakeTextChannel:
        def __init__(self):
            self.id = 888
            self.guild = SimpleNamespace(
                id=777, me=SimpleNamespace(id=999)
            )

    class Hook:
        def __init__(self, application_id):
            self.application_id = application_id
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)
            return SimpleNamespace(id=555)

    channel = FakeTextChannel()
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container()
    container.add_item(discord.ui.TextDisplay("Message supprimé"))
    container.add_item(discord.ui.ActionRow(
        discord.ui.Button(label="Historique", custom_id="sentrix:history:123")
    ))
    view.add_item(container)
    monkeypatch.setattr(profiles.discord, "TextChannel", FakeTextChannel)
    hook = Hook(application_id=999)
    async def _hook(_channel):
        return hook
    monkeypatch.setattr(profiles, "_webhook", _hook)
    sent = await profiles.send_with_profile(
        channel, view, [], {"enabled": True, "display_name": "Messages",
                            "avatar_url": "https://cdn.discordapp.com/avatar.png"},
        allowed_mentions=discord.AllowedMentions.none()
    )
    assert sent.id == 555
    assert hook.sent and hook.sent[0]["view"] is view
    assert hook.sent[0]["username"] == "Messages"

    # Incoming webhook without app ownership cannot receive interactive buttons.
    non_owned = Hook(application_id=None)
    async def _other(_channel):
        return non_owned
    monkeypatch.setattr(profiles, "_webhook", _other)
    returned = await profiles.send_with_profile(
        channel, view, [], {"enabled": True, "display_name": "Messages",
                            "avatar_url": ""},
        allowed_mentions=discord.AllowedMentions.none()
    )
    assert returned is None
    assert not non_owned.sent

    # A non-interactive log can still use an incoming webhook.
    simple = discord.ui.LayoutView()
    simple.add_item(discord.ui.TextDisplay("Salon renommé"))
    delivered = await profiles.send_with_profile(
        channel, simple, [], {"enabled": True, "display_name": "Salons",
                              "avatar_url": ""},
        allowed_mentions=discord.AllowedMentions.none()
    )
    assert delivered.id == 555
    assert len(non_owned.sent) == 1


def test_application_owned_webhooks_keep_log_actions(monkeypatch):
    asyncio.run(_exercise_application_owned_interactive_webhooks(monkeypatch))
