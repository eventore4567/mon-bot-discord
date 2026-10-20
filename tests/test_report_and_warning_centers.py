"""Safety, UI and route regression tests for SentriX's staff reporting center."""
from __future__ import annotations

import os
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import report_center, warnings_config, setup_control_center
import sentrix_v103_setup_fix as v103
from database.db import Database
from utils import access_matrix


def test_members_can_access_reporting_context_menu_without_moderation_permissions():
    assert "signaler ce message" in access_matrix.PUBLIC_COMMANDS
    assert access_matrix.module_for_command("signaler ce message") is None



class FakeTree:
    def __init__(self):
        self.group = app_commands.Group(name="config", description="Configuration historique")

    def remove_command(self, name, **kwargs):
        return None

    def get_command(self, name, **kwargs):
        if name == "config":
            return self.group
        return None

    def get_commands(self, **kwargs):
        return [self.group]

    def add_command(self, value, **kwargs):
        self.group = value


def test_report_and_warning_buttons_are_nested_under_moderation_without_exceeding_root_limit():
    bot = SimpleNamespace(tree=FakeTree())
    cog = SimpleNamespace(send_setup=AsyncMock())
    report = SimpleNamespace(open_config=AsyncMock())
    bot.get_cog = lambda key: {"SentriXSetup": cog, "ReportCenter": report}.get(key)
    group = bot.tree.group
    async def noop(interaction):
        pass
    legacy = app_commands.Command(name="ancienne", description="Déjà présent", callback=noop)
    group.add_command(legacy)
    assert v103._replace_setup_slash(bot)
    assert bot.tree.group is group
    assert {x.name for x in group.commands} >= {
        "accueil", "automod", "logs", "tickets", "bienvenue", "moderation",
        "niveaux", "diagnostic", "ancienne",
    }
    assert group.get_command("avertissements") is None
    assert group.get_command("signalements") is None
    source = inspect.getsource(setup_control_center.SetupView.render)
    assert "⚠️ Avertissements" in source
    assert "🚨 Signalements" in source


@pytest.mark.asyncio
async def test_report_schema_defaults_to_disabled(tmp_path):
    db = Database(str(tmp_path / "reports.db"))
    await db.connect()
    try:
        bot = SimpleNamespace(db=db)
        cog = report_center.ReportCenter(bot)
        await cog.ensure_schema()
        assert await db.fetchone(
            "SELECT * FROM member_report_settings WHERE guild_id=?", (77,),
        ) is None
        await db.execute("INSERT INTO member_report_settings(guild_id) VALUES (?)", (77,))
        cfg = await db.fetchone(
            "SELECT * FROM member_report_settings WHERE guild_id=?", (77,),
        )
        assert cfg["enabled"] == 0
        assert cfg["notify_staff"] == 0
        assert cfg["channel_id"] is None
        cur = await db.execute(
            "INSERT INTO member_reports(guild_id,target_id,reporter_id,reason,"
            "staff_channel_id,created_at,updated_at) VALUES (1,2,3,'Spam',4,5,5)"
        )
        assert cur.lastrowid is not None
        row = await cog.get_report(cur.lastrowid)
        assert row["status"] == "pending"
        assert row["claimed_by"] is None
    finally:
        await db._conn.close()


def test_only_private_staff_channels_are_eligible():
    channel = MagicMock(spec=discord.TextChannel)
    role = object()
    member = object()
    guild = SimpleNamespace(default_role=role, me=member)
    perms = SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    channel.permissions_for.side_effect = lambda item: (
        SimpleNamespace(view_channel=False)
        if item is role else perms
    )
    assert report_center.ReportCenter.valid_private_channel(guild, channel)
    channel.permissions_for.side_effect = lambda item: (
        SimpleNamespace(view_channel=True) if item is role else perms
    )
    assert not report_center.ReportCenter.valid_private_channel(guild, channel)


@pytest.mark.asyncio
async def test_disabled_reporting_never_creates_a_case():
    db = SimpleNamespace(fetchone=AsyncMock(return_value=None), execute=AsyncMock())
    bot = SimpleNamespace(db=db)
    cog = report_center.ReportCenter(bot)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=1), user=SimpleNamespace(id=2), response=response
    )
    await cog.submit_report(
        interaction, target=SimpleNamespace(id=8), reason="Message déplacé",
    )
    response.send_message.assert_awaited_once()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_view_uses_persistent_wide_discord_container():
    target_id = 175928847299117063
    row = {
        "id": 20, "guild_id": 1, "target_id": target_id,
        "reporter_id": 5, "reason": "Un message à examiner",
        "source_channel_id": 22, "source_message_id": 33,
        "staff_channel_id": 44, "staff_message_id": 55,
        "status": "pending", "claimed_by": None,
        "created_at": 1720000000, "updated_at": 1720000000,
    }
    db = SimpleNamespace(
        fetchone=AsyncMock(return_value={"n": 0}),
        fetchall=AsyncMock(return_value=[]),
    )
    guild = SimpleNamespace(get_member=lambda uid: None)
    bot = SimpleNamespace(db=db, get_guild=lambda uid: guild)
    cog = report_center.ReportCenter(bot)
    view = report_center.ReportReviewView(cog, row)
    await view.build()
    assert view.timeout is None
    assert len(view.children) == 1
    container = view.children[0]
    assert isinstance(container, discord.ui.Container)
    text = " ".join(
        getattr(child, "content", "") for child in container.children
    )
    assert "Signalement envers" in text
    assert "Prendre en charge" in str([getattr(x, "label", "") for row in container.children for x in getattr(row, "children", [])])


@pytest.mark.asyncio
async def test_denied_member_cannot_use_report_actions():
    report = {"guild_id": 1, "id": 4}
    bot = SimpleNamespace(db=SimpleNamespace(fetchone=AsyncMock(return_value=None)))
    cog = report_center.ReportCenter(bot)
    view = report_center.ReportReviewView(cog, report)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = SimpleNamespace(
        guild_id=1, guild=SimpleNamespace(),
        user=SimpleNamespace(id=20),
        response=response,
    )
    assert await view.interaction_check(interaction) is False
    response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_warning_config_starts_without_implicit_sanction():
    db = SimpleNamespace(
        get_guild_config=AsyncMock(return_value={"warn_ban_threshold": 0, "warn_role": None}),
        fetchone=AsyncMock(side_effect=[None, {"n": 0}]),
    )
    bot = SimpleNamespace(db=db)
    guild = SimpleNamespace(id=1, get_role=lambda uid: None, get_channel=lambda uid: None)
    view = warnings_config.WarningSettingsView(bot, guild, 99)
    from unittest.mock import patch
    with patch("cogs.warnings_config.log_service.get_log_setting", AsyncMock(return_value={"channel_id": None})):
        await view.build()
    assert isinstance(view.children[0], discord.ui.Container)
    assert db.get_guild_config.await_count == 1
    assert not hasattr(db, "set_guild_config")
