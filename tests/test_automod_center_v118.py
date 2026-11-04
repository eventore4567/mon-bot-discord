"""Regression tests for SentriX's compact AutoMod/logs UI."""
from pathlib import Path

import discord

from cogs.automod import AUTOMOD_TOGGLE_LABELS
from cogs.automod_center_v118 import (
    GROUPS,
    HISTORY_PAGE_SIZE,
    LOG_CATEGORIES,
    AutoModCenterView,
    AutoModLogsView,
    history_clause,
)
from utils import log_service


def test_groups_only_use_real_automod_switches():
    fields = [field for _key, _title, _help, group in GROUPS for field in group]
    assert len(GROUPS) == 4
    assert len(fields) == len(set(fields))
    assert set(fields) <= set(AUTOMOD_TOGGLE_LABELS)
    # The DB deliberately aliases strict links to antilink; never expose both.
    assert set(AUTOMOD_TOGGLE_LABELS) - set(fields) == {"antilink_strict"}


def test_log_categories_use_existing_canonical_log_routes():
    assert LOG_CATEGORIES == ("automod", "spam", "raid")
    assert all(key in log_service.LOG_TYPES for key in LOG_CATEGORIES)
    assert HISTORY_PAGE_SIZE <= 5


def test_history_sql_is_guild_scoped_and_parameterized():
    query, params = history_clause(321, 987, "spam")
    assert query.startswith("guild_id = ? AND user_id = ?")
    assert "filter_name IN" in query
    assert params[:2] == (321, 987)
    assert "987" not in query


def test_history_all_without_member_has_single_guild_filter():
    assert history_clause(55, None, "all") == ("guild_id = ?", (55,))


def test_panels_are_components_v2_and_private():
    assert issubclass(AutoModCenterView, discord.ui.LayoutView)
    assert issubclass(AutoModLogsView, discord.ui.LayoutView)
    source = Path("cogs/automod_center_v118.py").read_text(encoding="utf-8")
    assert "ephemeral=True" in source
    assert "interaction.user.id != self.author_id" in source
    assert "await _can_setup" in source
    assert "automod_logs" in source
    assert "set_log_config" in source
    assert "set_automod" in source


def test_official_setup_opens_both_panels_not_a_duplicate_cog():
    source = Path("cogs/setup_control_center.py").read_text(encoding="utf-8")
    assert "AutoModCenterView(self.bot, self.guild, self.author_id).open(interaction)" in source
    assert "AutoModLogsView(self.bot, self.guild, self.author_id).open(interaction)" in source
