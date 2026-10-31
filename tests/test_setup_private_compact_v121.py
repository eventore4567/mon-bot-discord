"""SentriX /setup privé et sobre, activation après configuration."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_setup_private_interactions_and_short_prefix_notice():
    s = source("cogs/setup_experience_v74.py")
    area = s[s.index("async def _send_setup_v74("):s.index("\ndef install(", s.index("async def _send_setup_v74("))]
    assert "ephemeral=True" in area
    assert "delete_after=15" in area
    assert "/setup" in area


def test_one_select_setup_home_does_not_toggle_modules():
    s = source("cogs/setup_experience_v74.py")
    a = s.index("    async def _build_home(self)")
    b = s.index("    async def _build_home_complet(self)", a)
    home = s[a:b]
    assert home.count("discord.ui.Select(") == 1
    assert "ModuleSwitchSelect" not in home
    assert "toggle_module_switch" not in home
    assert "discord.ui.Button(label=\"Fermer\"" in home
    assert "Installer" not in home


def test_configuring_log_channel_activates_logs():
    s = source("cogs/setup_security_choice_v75.py")
    start = s.index("    async def choose_channel(interaction:")
    end = s.index("    channel_select.callback = choose_channel",start)
    frag=s[start:end]
    assert "set_log_channel(" in frag
    assert "set_log_enabled(" in frag
    assert "core.set_module_enabled(" in frag
    assert ' "logs", True' in frag


def test_ticket_panel_activates_after_publication():
    s=source("cogs/tickets.py")
    fragment=s[s.index("    async def _send_panel_locked"):s.index("    async def start_ticket_flow")]
    assert fragment.index("if old is None:") < fragment.index("await setup_core.set_module_enabled(")
    assert fragment.index("await setup_core.set_module_enabled(") < fragment.index("confirmation = (")
    assert "ModuleSetupRequired" in fragment


def test_embed_only_shows_embed_content_not_sender_profile():
    s=source("cogs/embed_builder.py")
    a=s.index("    def status_summary(self)")
    b=s.index("    def to_dict(self)",a)
    assert "Mini-profil" not in s[a:b]
    assert "Mini-profil du message" not in s
    # Existing sender metadata remains loadable to preserve older templates.
    assert '"sender_name": self.sender_name' in s
    assert '"sender_avatar_url": self.sender_avatar_url' in s


def test_all_modified_modules_parse():
    for name in ("cogs/setup_experience_v74.py","cogs/setup_control_center.py","cogs/setup_security_choice_v75.py",
                 "cogs/embed_builder.py","cogs/tickets.py","cogs/slash_command_budget.py"):
        ast.parse(source(name),filename=name)
