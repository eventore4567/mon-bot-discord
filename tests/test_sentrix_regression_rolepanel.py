from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "sentrix_regression_runtime.py").read_text(encoding="utf-8")
SHIM = (ROOT / "cogs" / "sentrix_regression_fix.py").read_text(encoding="utf-8")


def test_rolepanel_never_creates_discord_roles():
    assert "create_role(" not in SOURCE
    assert "rôles déjà existants" in SOURCE
    assert "discord.ui.RoleSelect" in SOURCE
    assert "rolepanel_existing_roles_only" in SOURCE


def test_rolepanel_supports_dropdown_and_reaction_modes():
    assert 'value="dropdown"' in SOURCE
    assert 'value="reaction"' in SOURCE
    assert '@rolepanel.command(name="dropdown"' in SOURCE
    assert '@rolepanel.command(name="reaction"' in SOURCE
    assert "on_raw_reaction_add" in SOURCE
    assert "on_raw_reaction_remove" in SOURCE


def test_dashboard_loader_guard_is_injected_into_live_index_html():
    assert "sentrix-final-loader-guard" in SOURCE
    assert "#emptyState.sx-empty-premium.hidden{display:none!important}" in SOURCE
    assert "dashboard.INDEX_HTML = html" in SOURCE


def test_cog_is_only_a_late_bootstrap_shim():
    assert "from sentrix_regression_runtime import setup" in SHIM
