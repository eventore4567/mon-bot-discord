from __future__ import annotations

from pathlib import Path

from cogs.dashboard_runtime_patch import MANAGE_GUILD, _patch_recovery_loader, _patch_switch_html
from cogs.giveaway_v2 import BuilderState, _weighted_unique
from cogs.setup_invitations import CATEGORY as INVITATIONS_CATEGORY


ROOT = Path(__file__).resolve().parents[1]


def test_new_runtime_files_compile():
    """Catch syntax/import regressions in the five files loaded by giveaway_center."""
    for relative in (
        "cogs/dashboard_runtime_patch.py",
        "cogs/giveaway_center.py",
        "cogs/giveaway_v2.py",
        "cogs/infinite_counter.py",
        "cogs/setup_invitations.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        compile(source, relative, "exec")


def test_giveaway_only_requires_base_fields_by_default():
    state = BuilderState(author_id=1, guild_id=2)
    assert state.required_roles == []
    assert state.excluded_roles == []
    assert state.bonus_roles == []
    assert state.ping_role_id is None
    assert state.image_url is None
    assert state.min_invites == 0
    assert state.min_account_age_days == 0
    assert state.min_server_age_days == 0
    assert state.custom_condition is None


def test_weighted_draw_is_unique_even_with_multiple_winners():
    pool = [(10, 1), (20, 2), (30, 8), (40, 1)]
    winners = _weighted_unique(pool, 4)
    assert len(winners) == 4
    assert len(set(winners)) == 4
    assert set(winners) == {10, 20, 30, 40}


def test_dashboard_switch_patch_drops_stale_native_payloads():
    source = (
        "before\n"
        "    async function selectGuild(value){OLD}\n"
        "    function optionList(type,current){return '';}\n"
        "after"
    )
    patched, ok = _patch_switch_html(source)
    assert ok is True
    assert "guildLoadToken" in patched
    # selectGuild normalise déjà value avec String(value) avant cette garde.
    assert "String(state.guildId)!==value" in patched
    assert "Les données précédentes ont été retirées" in patched
    assert "{OLD}" not in patched


def test_dashboard_recovery_loader_checks_current_selector_too():
    marker = '      if(!applyGuildData(id,data)) throw new Error("Les données du serveur ont été reçues mais leur affichage a échoué.");'
    patched, ok = _patch_recovery_loader(marker)
    assert ok is True
    assert "selectedNow" in patched
    assert "selectedNow!==id" in patched


def test_manage_server_bit_and_live_permission_are_explicit():
    source = (ROOT / "cogs/dashboard_runtime_patch.py").read_text(encoding="utf-8")
    assert MANAGE_GUILD == 1 << 5
    assert "perms.manage_guild" in source
    assert "perms.administrator" in source
    assert "guild.owner_id == user_id" in source


def test_invitation_setup_is_a_dedicated_category_with_required_log_permissions():
    source = (ROOT / "cogs/setup_invitations.py").read_text(encoding="utf-8")
    assert INVITATIONS_CATEGORY == "invitations"
    assert 'LEGACY_CATEGORY_KEYS["dossiers"] = CATEGORY' in source
    assert '"invite_create", "invite_delete"' in source
    assert '"attach_files"' in source
    assert "log_service.LOG_TYPES[CATEGORY]" not in source


def test_infinite_counter_persists_and_never_resets_on_invalid_input():
    source = (ROOT / "cogs/infinite_counter.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS infinite_counter_config" in source
    assert "last_user_id" in source
    assert "asyncio.Lock" in source
    assert "delete_after=10" in source
    assert "await asyncio.sleep(2)" in source
    # Progress only advances in the valid branch; invalid branches return before this UPDATE.
    assert "next_number=?,last_user_id=?" in source
    assert "next_number=1" not in source
