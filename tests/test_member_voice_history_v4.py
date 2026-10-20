"""Vocal staff history: opt-in, persistence, restart and Discord UI contracts."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio

from database.db import Database
from services import voice_history
from cogs.logs import Logs
from cogs.voice_history_config import VoiceHistoryConfigView


@pytest_asyncio.fixture
async def voice_db(tmp_path):
    db = Database(str(tmp_path / "voice-history.db"))
    await db.connect()
    try:
        yield db
    finally:
        await db._conn.close()


@pytest.mark.asyncio
async def test_default_voice_tracking_is_opt_in(voice_db):
    bot = SimpleNamespace(db=voice_db)
    opts = await voice_history.get_settings(bot, 11)
    assert opts == {
        "enabled": False, "track_moves": True, "track_duration": True,
    }
    assert await voice_history.record_transition(
        bot, 11, 99, None, 123, now=1000
    ) is None
    assert (await voice_history.get_member_summary(bot, 11, 99))["session"] is None


@pytest.mark.asyncio
async def test_persistent_join_move_leave_and_precise_duration(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 11, "enabled", True)
    join = await voice_history.record_transition(
        bot, 11, 99, None, 123, now=1000,
    )
    assert join.kind == "voice_join"
    assert join.archive
    move = await voice_history.record_transition(
        bot, 11, 99, 123, 456, now=1060,
    )
    assert move.kind == "voice_move"
    assert move.segment_seconds == 60
    summary = await voice_history.get_member_summary(bot, 11, 99)
    assert summary["session"]["started_at"] == 1000
    assert summary["session"]["channel_id"] == 456
    leave = await voice_history.record_transition(
        bot, 11, 99, 456, None, now=1120,
    )
    assert leave.kind == "voice_leave"
    assert leave.duration_seconds == 120
    assert leave.segment_seconds == 60
    summary = await voice_history.get_member_summary(bot, 11, 99)
    assert summary["session"] is None
    assert summary["seconds"] == 120
    assert summary["completed_sessions"] == 1
    assert voice_history.duration_label(summary["seconds"]) == "2 min 0 s"


@pytest.mark.asyncio
async def test_motion_flag_does_not_break_duration_calculation(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    await voice_history.set_setting(bot, 1, "track_moves", False)
    await voice_history.record_transition(bot, 1, 9, None, 2, now=1000)
    move = await voice_history.record_transition(bot, 1, 9, 2, 3, now=1035)
    assert not move.archive
    final = await voice_history.record_transition(bot, 1, 9, 3, None, now=1050)
    assert final.duration_seconds == 50


@pytest.mark.asyncio
async def test_duration_unknown_when_session_was_not_observed(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    final = await voice_history.record_transition(bot, 1, 9, 2, None, now=1000)
    assert final.duration_seconds is None
    assert (await voice_history.get_member_summary(bot, 1, 9))["seconds"] == 0


@pytest.mark.asyncio
async def test_disabling_tracking_discards_open_sessions_but_keeps_completed_totals(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    await voice_history.record_transition(bot, 1, 9, None, 2, now=1000)
    await voice_history.record_transition(bot, 1, 9, 2, None, now=1100)
    await voice_history.record_transition(bot, 1, 9, None, 2, now=1120)
    await voice_history.set_setting(bot, 1, "enabled", False)
    summary = await voice_history.get_member_summary(bot, 1, 9)
    assert summary["session"] is None
    assert summary["seconds"] == 100
    assert summary["enabled"] is False


@pytest.mark.asyncio
async def test_restart_reconciliation_preserves_only_verified_active_session(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    await voice_history.record_transition(bot, 1, 9, None, 2, now=1000)
    await voice_history.record_transition(bot, 1, 10, None, 4, now=1000)
    guild = SimpleNamespace(
        id=1,
        voice_channels=[
            SimpleNamespace(id=2, members=[SimpleNamespace(id=9, bot=False)]),
            SimpleNamespace(id=3, members=[SimpleNamespace(id=11, bot=False)]),
        ],
    )
    await voice_history.reconcile_guild(bot, guild, now=1400)
    kept = await voice_history.get_member_summary(bot, 1, 9)
    removed = await voice_history.get_member_summary(bot, 1, 10)
    new = await voice_history.get_member_summary(bot, 1, 11)
    assert kept["session"]["started_at"] == 1000
    assert removed["session"] is None
    assert new["session"]["started_at"] == 1400
    assert new["session"]["channel_id"] == 3


@pytest.mark.asyncio
async def test_unconfigured_voice_log_still_archives_when_tracking_is_enabled(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    cog = Logs(bot)
    cog._send = AsyncMock(return_value=False)
    panel = discord.Embed(title="Activité vocale")
    panel.add_field(name="Membre", value="<@123456789012345678>")
    cog._embed = MagicMock(return_value=panel)
    user = SimpleNamespace(
        id=123456789012345678,
        guild=SimpleNamespace(id=1), bot=False,
    )
    old = SimpleNamespace(channel=None, self_mute=False, self_deaf=False)
    new = SimpleNamespace(channel=SimpleNamespace(id=44), self_mute=False, self_deaf=False)
    with patch("cogs.logs.log_service.is_primary_process", return_value=True), patch(
        "cogs.logs.voice_history.archive_undelivered_event", AsyncMock()
    ) as archive:
        await cog.on_voice_state_update(user, old, new)
    archive.assert_awaited_once()
    assert archive.call_args.args[:2] == (1, "voice_join")


@pytest.mark.asyncio
async def test_no_duplicate_archive_when_vocal_log_was_sent(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    cog = Logs(bot)
    cog._send = AsyncMock(return_value=True)
    cog._embed = MagicMock(return_value=discord.Embed(title="Activité vocale"))
    member = SimpleNamespace(id=12, guild=SimpleNamespace(id=1), bot=False)
    before = SimpleNamespace(channel=None, self_mute=False, self_deaf=False)
    after = SimpleNamespace(channel=SimpleNamespace(id=34), self_mute=False, self_deaf=False)
    with patch("cogs.logs.log_service.is_primary_process", return_value=True), patch(
        "cogs.logs.voice_history.archive_undelivered_event", AsyncMock()
    ) as archive:
        await cog.on_voice_state_update(member, before, after)
    archive.assert_not_awaited()


@pytest.mark.asyncio
async def test_premium_config_panel_has_independent_tracking_and_publishing(voice_db):
    bot = SimpleNamespace(db=voice_db)
    guild = SimpleNamespace(id=1, get_channel=lambda _: None)
    view = VoiceHistoryConfigView(bot, guild, owner_id=99)
    with patch(
        "cogs.voice_history_config.log_service.get_log_setting",
        AsyncMock(return_value={"enabled": False, "channel_id": None}),
    ):
        await view.build()
    assert len(view.children) == 1
    card = view.children[0]
    assert isinstance(card, discord.ui.Container)
    rows = [x for x in card.children if isinstance(x, discord.ui.ActionRow)]
    assert len(rows) == 3
    assert len(rows[0].children) == 3
    assert "Désactivées" in card.children[2].content
    assert len(view.children) == 1


@pytest.mark.asyncio
async def test_invalid_voice_setting_is_rejected_before_any_sql(voice_db):
    bot = SimpleNamespace(db=voice_db)
    with pytest.raises(ValueError):
        await voice_history.set_setting(bot, 1, "enabled;DROP TABLE levels", True)



@pytest.mark.asyncio
async def test_move_disabled_prevents_both_public_and_private_movement_logs(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    await voice_history.set_setting(bot, 1, "track_moves", False)
    await voice_history.record_transition(bot, 1, 12, None, 33, now=1000)
    cog = Logs(bot)
    cog._send = AsyncMock(return_value=True)
    cog._embed = MagicMock(return_value=discord.Embed(title="Activité vocale"))
    member = SimpleNamespace(id=12, guild=SimpleNamespace(id=1), bot=False)
    before = SimpleNamespace(channel=SimpleNamespace(id=33), self_mute=False, self_deaf=False)
    after = SimpleNamespace(channel=SimpleNamespace(id=44), self_mute=False, self_deaf=False)
    with patch("cogs.logs.log_service.is_primary_process", return_value=True), patch(
        "cogs.logs.voice_history.archive_undelivered_event", AsyncMock()
    ) as archive:
        await cog.on_voice_state_update(member, before, after)
    cog._send.assert_not_awaited()
    archive.assert_not_awaited()
    info = await voice_history.get_member_summary(bot, 1, 12)
    assert info["session"]["channel_id"] == 44


def test_setup_panel_exposes_vocal_config_without_new_slash_root():
    import inspect
    from cogs.setup_control_center import CategorySelect, SetupView, OfficialSetup
    source = inspect.getsource(CategorySelect.callback)
    assert "open_voice_history_config" in source
    assert "surveillance" in source
    assert "👁️ Surveillance" in inspect.getsource(SetupView.render)
    assert OfficialSetup.config_group.get_command("surveillance") is None



@pytest.mark.asyncio
async def test_sessions_counted_but_duration_private_when_duration_option_off(voice_db):
    bot = SimpleNamespace(db=voice_db)
    await voice_history.set_setting(bot, 1, "enabled", True)
    await voice_history.set_setting(bot, 1, "track_duration", False)
    await voice_history.record_transition(bot, 1, 23, None, 45, now=100)
    exit_event = await voice_history.record_transition(
        bot, 1, 23, 45, None, now=160,
    )
    assert exit_event.duration_seconds is None
    stats = await voice_history.get_member_summary(bot, 1, 23)
    assert stats["completed_sessions"] == 1
    assert stats["seconds"] == 0



@pytest.mark.asyncio
async def test_surveillance_category_opens_private_center_directly():
    from cogs.setup_control_center import CategorySelect
    owner = SimpleNamespace(bot=SimpleNamespace(), guild=SimpleNamespace(id=1))
    select = CategorySelect(owner)
    assert any(item.value == "surveillance" for item in select.options)
    select._values = ["surveillance"]
    interaction = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=12))
    with patch("cogs.voice_history_config.open_voice_history_config", AsyncMock()) as open_panel:
        await select.callback(interaction)
    open_panel.assert_awaited_once_with(owner.bot, interaction)
