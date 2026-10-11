"""Régressions de restauration des panneaux de vérification SentriX."""
import asyncio
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automatic_verification_v5 import AutomaticVerificationV5
from cogs import honeypot_verification_v48 as honeypot
from cogs import verification


def _bot_message(message_id, *, title=None, text=None, author_id=55):
    embeds = [SimpleNamespace(title=title, description="")] if title else []
    components = [SimpleNamespace(content=text, children=[], components=[])] if text else []
    return SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(id=author_id),
        content=None,
        embeds=embeds,
        components=components,
    )


def _channel(messages):
    obj = SimpleNamespace()
    obj.fetch_message = AsyncMock(side_effect=lambda id: next(m for m in messages if m.id == id))

    async def history(limit=30):
        for msg in messages[:limit]:
            yield msg

    obj.history = history
    return obj


def test_repair_does_not_overwrite_unrelated_bot_messages():
    async def run():
        unrelated = _bot_message(1, title="Bienvenue sur le serveur")
        panel = _bot_message(2, title="Vérification web SentriX")
        cog = AutomaticVerificationV5(SimpleNamespace(user=SimpleNamespace(id=55)))
        found = await cog._remembered_panel_message(
            _channel([unrelated, panel]), None, kind="verify",
        )
        assert found is panel
        empty = await cog._remembered_panel_message(
            _channel([unrelated]), None, kind="verify",
        )
        assert empty is None

    asyncio.run(run())


def test_persisted_id_must_be_own_verification_panel():
    async def run():
        unrelated = _bot_message(1, title="Ticket #123")
        portal = _bot_message(2, text="Se vérifier sur SentriX")
        cog = AutomaticVerificationV5(SimpleNamespace(user=SimpleNamespace(id=55)))
        found = await cog._remembered_panel_message(
            _channel([unrelated, portal]), 1, kind="verify",
        )
        assert found is portal
        wrong_author = _bot_message(3, title="Vérification web SentriX", author_id=99)
        found = await cog._remembered_panel_message(
            _channel([wrong_author, unrelated]), 3, kind="verify",
        )
        assert found is None

    asyncio.run(run())


def test_verification_and_honeypot_panels_are_not_confused():
    assert AutomaticVerificationV5._looks_like_own_panel(
        _bot_message(1, text="NE PAS ENVOYER DE MESSAGE DANS CE SALON"),
        "trap",
    )
    assert not AutomaticVerificationV5._looks_like_own_panel(
        _bot_message(1, text="NE PAS ENVOYER DE MESSAGE DANS CE SALON"),
        "verify",
    )


def test_startup_retries_only_locked_database(monkeypatch):
    async def run():
        class FakeTextChannel:
            pass

        monkeypatch.setattr(honeypot.discord, "TextChannel", FakeTextChannel)
        channel = FakeTextChannel()
        guild = SimpleNamespace(id=12, get_channel=lambda _: channel)
        conf = {"verify_channel_id": 1, "trap_channel_id": 2}
        cog = SimpleNamespace(
            config=AsyncMock(return_value=conf),
            refresh_existing_panels=AsyncMock(side_effect=[
                sqlite3.OperationalError("database is locked"),
                ({"removed_verify_messages": 0, "removed_trap_messages": 0}, None),
            ]),
        )
        bot = SimpleNamespace(
            guilds=[guild],
            wait_until_ready=AsyncMock(),
            get_cog=lambda _: cog,
        )
        pause = AsyncMock()
        monkeypatch.setattr(honeypot.asyncio, "sleep", pause)
        await honeypot._repair_enabled_systems(bot)
        assert cog.refresh_existing_panels.await_count == 2
        assert pause.await_count == 2

    asyncio.run(run())


def test_verify_repair_reports_missing_permissions_without_publishing(monkeypatch):
    async def run():
        class FakeTextChannel:
            def __init__(self, id):
                self.id = id
                self.mention = f"<#{id}>"

            def permissions_for(self, member):
                return SimpleNamespace(
                    view_channel=True, send_messages=False, read_message_history=True,
                )

        monkeypatch.setattr(verification.discord, "TextChannel", FakeTextChannel)
        guild = SimpleNamespace(
            id=12,
            me=object(),
            get_channel=lambda id: FakeTextChannel(id),
        )
        cog = SimpleNamespace(
            config=AsyncMock(return_value={"verify_channel_id": 1, "trap_channel_id": 2}),
            refresh_existing_panels=AsyncMock(),
        )
        bot = SimpleNamespace(get_cog=lambda _: cog)
        ctx = SimpleNamespace(guild=guild, send=AsyncMock())
        verification_cog = verification.Verification(bot)
        await verification_cog.verify_repair.callback(verification_cog, ctx)
        assert ctx.send.await_count == 1
        assert "Envoyer des messages" in ctx.send.await_args.args[0]
        cog.refresh_existing_panels.assert_not_awaited()

    asyncio.run(run())


def test_verify_panel_routes_to_active_web_gateway(monkeypatch):
    async def run():
        guild = SimpleNamespace(id=14)
        destination = SimpleNamespace(mention="<#42>")
        portal = SimpleNamespace(
            config=AsyncMock(return_value={"enabled": 1}),
            refresh_existing_panels=AsyncMock(return_value=(
                {"verify": destination}, None,
            )),
        )
        bot = SimpleNamespace(get_cog=lambda name: portal if name == "HoneypotVerification" else None)
        cog = verification.Verification(bot)
        ctx = SimpleNamespace(guild=guild, send=AsyncMock())

        # Une vérification web active doit primer sur le bouton simple.
        send_simple = AsyncMock()
        monkeypatch.setattr(verification.panels, "envoyer", send_simple)
        await cog.verify_panel.callback(cog, ctx)
        portal.refresh_existing_panels.assert_awaited_once_with(guild)
        send_simple.assert_not_awaited()
        assert "<#42>" in ctx.send.await_args.args[0]

    asyncio.run(run())


def test_legacy_portal_does_not_erase_messages_before_send(monkeypatch):
    async def run():
        class FakeTextChannel:
            def __init__(self, id):
                self.id = id

        monkeypatch.setattr(honeypot.discord, "TextChannel", FakeTextChannel)
        channels = {7: FakeTextChannel(7), 8: FakeTextChannel(8)}
        guild = SimpleNamespace(id=14, get_channel=lambda id: channels.get(id))
        portal = honeypot.HoneypotVerification(SimpleNamespace())
        portal.config = AsyncMock(return_value={
            "verify_channel_id": 7, "trap_channel_id": 8,
            "sanction": "softban",
        })
        portal.ensure_verified_panel_hidden = AsyncMock()
        monkeypatch.setattr(honeypot, "_web_panel", AsyncMock(return_value="webpanel"))
        monkeypatch.setattr(honeypot, "_purge_bot_messages", AsyncMock())
        sender = AsyncMock(side_effect=RuntimeError("Discord a refusé l'envoi"))
        monkeypatch.setattr(honeypot.panels, "envoyer", sender)

        try:
            await portal.refresh_existing_panels(guild)
        except RuntimeError:
            pass
        else:
            raise AssertionError("L'échec d'envoi devait être visible")
        honeypot._purge_bot_messages.assert_not_awaited()
        sender.assert_awaited_once()

    asyncio.run(run())
