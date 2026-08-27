from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELP_PATH = ROOT / "cogs" / "help.py"
HELP_SOURCE = HELP_PATH.read_text(encoding="utf-8")
HELP_TREE = ast.parse(HELP_SOURCE)


def _literal_assignment(name: str):
    for node in HELP_TREE.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Affectation {name!r} introuvable")


def test_help_exposes_discreet_growth_links():
    assert '"Ajouter SentriX"' in HELP_SOURCE
    assert '"Dashboard"' in HELP_SOURCE
    assert '"Serveur support"' in HELP_SOURCE
    assert "_add_growth_links(self, bot)" in HELP_SOURCE
    assert "discord.ButtonStyle.link" in HELP_SOURCE
    assert "row=3" in HELP_SOURCE


def test_invite_uses_real_bot_id_and_slash_scope():
    assert 'getattr(getattr(bot, "user", None), "id", None)' in HELP_SOURCE
    assert "discord.utils.oauth_url" in HELP_SOURCE
    assert 'scopes=("bot", "applications.commands")' in HELP_SOURCE


def test_invite_permissions_are_explicit_and_not_administrator():
    permission_names = _literal_assignment("INVITE_PERMISSION_NAMES")
    assert "administrator" not in permission_names
    for required in (
        "view_channel",
        "manage_channels",
        "manage_roles",
        "manage_messages",
        "moderate_members",
        "kick_members",
        "ban_members",
        "embed_links",
        "attach_files",
        "connect",
        "speak",
    ):
        assert required in permission_names


def test_dashboard_has_production_config_fallback():
    assert 'os.getenv("DASHBOARD_URL", "")' in HELP_SOURCE
    assert 'getattr(config, "DASHBOARD_APP_URL", "")' in HELP_SOURCE


def test_support_button_requires_a_configured_url():
    assert '"SENTRIX_SUPPORT_URL"' in HELP_SOURCE
    assert '"SUPPORT_SERVER_URL"' in HELP_SOURCE
    # Les liens ne sont créés que lorsqu'une URL valide a réellement été résolue.
    assert "if url:" in HELP_SOURCE
    assert "view.add_item" in HELP_SOURCE


def test_growth_feature_does_not_add_advertising_listeners():
    # La croissance doit rester passive : uniquement dans la vue ouverte volontairement
    # par +help ou /help, jamais via un listener qui pousse de la publicité aux membres.
    assert "@commands.Cog.listener" not in HELP_SOURCE
    assert "on_message" not in HELP_SOURCE
    assert "on_member_join" not in HELP_SOURCE
    assert "on_guild_join" not in HELP_SOURCE
