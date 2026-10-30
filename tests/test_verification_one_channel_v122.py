"""SentriX V122 : seul le portail web est créé en mode Vérification seule.

Le mode Honeypot crée son salon seulement sur activation explicite, et
un ancien salon contenant des messages de membres est toujours conservé.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.automatic_verification_v5 import AutomaticVerificationV5


V4 = Path("cogs/automatic_verification_v4.py").read_text("utf-8")
V5 = Path("cogs/automatic_verification_v5.py").read_text("utf-8")
SETUP = Path("cogs/setup_v118_integrations.py").read_text("utf-8")
RECOVERY = Path("cogs/honeypot_verification_v48.py").read_text("utf-8")
SECURITY_UI = Path("cogs/setup_security_choice_v75.py").read_text("utf-8")


def test_verification_only_never_creates_second_channel():
    compile(V4, "automatic_verification_v4.py", "exec")
    block = V4.split("    async def create_or_refresh_system(", 1)[1].split(
        "    async def disable_system(", 1
    )[0]
    assert 'if honeypot_enabled and not isinstance(trap, discord.TextChannel):' in block
    assert 'view_channel=honeypot_enabled' in block
    assert 'if publish_panels and honeypot_enabled and isinstance(trap, discord.TextChannel):' in block
    assert 'if isinstance(trap, discord.TextChannel):\n            excluded_channels.add(trap.id)' in block


def test_v5_can_refresh_without_honeypot_channel_and_create_it_when_opted_in():
    compile(V5, "automatic_verification_v5.py", "exec")
    block = V5.split("    async def refresh_existing_panels(", 1)[1].split(
        "    async def create_or_refresh_system(", 1
    )[0]
    assert "if honeypot_enabled and not isinstance(trap, discord.TextChannel):" in block
    assert 'trap.id if isinstance(trap, discord.TextChannel) else None' in block
    assert "_retire_unused_honeypot_channel(" in block
    assert 'if honeypot_enabled:' in block
    assert 'self._remembered_panel_message(' in block


def test_restart_restores_portal_without_requiring_disabled_trap():
    assert 'mode["honeypot_enabled"] and not isinstance(trap_channel, discord.TextChannel)' in RECOVERY
    assert 'honeypot_enabled=(mode == "both")' in SETUP


def test_setup_offers_per_filter_automod_settings_without_auto_activation():
    assert 'policy_select = discord.ui.Select(' in SECURITY_UI
    assert 'placeholder="Configurer un filtre précis (sanction, whitelist, seuils)"' in SECURITY_UI
    assert 'security_ui._security_policy_setup_panel(' in SECURITY_UI


class DummyCategory:
    def __init__(self, id=10):
        self.id = id
        self.name = "SentriX • Vérification"


class DummyChannel:
    def __init__(self, messages):
        self.name = "stay-muted"
        self.category_id = 10
        self.messages = messages
        self.delete = AsyncMock()

    async def history(self, *, limit):
        for item in self.messages[:limit]:
            yield item


@pytest.mark.asyncio
async def test_unused_bot_only_trap_is_removed_without_touching_other_channels(monkeypatch):
    monkeypatch.setattr(discord, "TextChannel", DummyChannel)
    monkeypatch.setattr(discord, "CategoryChannel", DummyCategory)
    bot = SimpleNamespace(user=SimpleNamespace(id=777), db=SimpleNamespace(execute=AsyncMock()))
    guild = SimpleNamespace(id=42, get_channel=lambda id: DummyCategory(id) if id == 10 else None)
    # Do not call Cog.__init__; test the isolated cleanup method, not Discord gateway.
    cog = SimpleNamespace(bot=bot, _looks_like_own_panel=lambda msg, kind: True)
    trap = DummyChannel([SimpleNamespace(author=SimpleNamespace(id=777))])
    changed = await AutomaticVerificationV5._retire_unused_honeypot_channel(
        cog, guild, {"category_id": 10}, trap,
    )
    assert changed is True
    trap.delete.assert_awaited_once()
    bot.db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_trap_with_member_message_is_never_deleted(monkeypatch):
    monkeypatch.setattr(discord, "TextChannel", DummyChannel)
    monkeypatch.setattr(discord, "CategoryChannel", DummyCategory)
    bot = SimpleNamespace(user=SimpleNamespace(id=777), db=SimpleNamespace(execute=AsyncMock()))
    guild = SimpleNamespace(id=42, get_channel=lambda id: DummyCategory(id) if id == 10 else None)
    cog = SimpleNamespace(bot=bot, _looks_like_own_panel=lambda msg, kind: True)
    trap = DummyChannel([SimpleNamespace(author=SimpleNamespace(id=123))])
    changed = await AutomaticVerificationV5._retire_unused_honeypot_channel(
        cog, guild, {"category_id": 10}, trap,
    )
    assert changed is False
    trap.delete.assert_not_awaited()
    bot.db.execute.assert_not_awaited()
