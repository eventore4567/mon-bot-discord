"""Régression V121 : la vraie classe HoneypotVerification en production est V5.

PR #571 corrigeait la classe héritée v48, pas l'autorité V5 : le setup
plantait (méthode absente) et V4 pouvait encore sanctionner en mode simple.
"""
from pathlib import Path

V5 = Path("cogs/automatic_verification_v5.py").read_text(encoding="utf-8")
V4 = Path("cogs/automatic_verification_v4.py").read_text(encoding="utf-8")
SETUP = Path("cogs/setup_v118_integrations.py").read_text(encoding="utf-8")


def test_real_v5_cog_supports_visibility_and_mode_aware_panel_refresh():
    compile(V5, "automatic_verification_v5.py", "exec")
    assert "async def ensure_verified_panel_hidden(" in V5
    assert "async def refresh_existing_panels(" in V5
    assert "honeypot_enabled: bool | None = None" in V5
    assert "if honeypot_enabled:" in V5
    assert "await self._remembered_panel_message(" in V5
    assert "await old_trap_panel.delete()" in V5
    assert "trap_message.id if trap_message is not None else None" in V5


def test_real_v5_cog_forwards_mode_to_v4_and_does_not_post_old_panels():
    section = V5.split("    async def create_or_refresh_system(", 1)[1].split(
        "    @commands.Cog.listener()", 1
    )[0]
    assert "honeypot_enabled: bool = True" in section
    assert "honeypot_enabled=honeypot_enabled" in section
    assert "publish_panels=False" in section
    assert "self.refresh_existing_panels(" in section
    assert "honeypot_enabled=honeypot_enabled" in section


def test_v4_inherited_honeypot_listener_never_sanctions_when_mode_one():
    compile(V4, "automatic_verification_v4.py", "exec")
    section = V4.split(
        "    async def on_message(self, message: discord.Message):", 1
    )[1].split("\n\nasync def install(", 1)[0]
    assert 'if not advanced["honeypot_enabled"]:\n            return' in section
    assert section.index('if not advanced["honeypot_enabled"]') < section.index("await message.delete()")


def test_v4_initial_install_hides_trap_and_skips_legacy_panels_in_mode_one():
    section = V4.split("    async def create_or_refresh_system(", 1)[1].split(
        "    async def disable_system(", 1
    )[0]
    assert 'view_channel=honeypot_enabled' in section
    assert 'send_messages=honeypot_enabled' in section
    assert 'if publish_panels and honeypot_enabled:' in section
    assert 'if honeypot_enabled and sanction == "softban":' in section


def test_setup_targets_true_runtime_cog_methods():
    assert "honeypot = self.bot.get_cog(\"HoneypotVerification\")" in SETUP
    assert 'honeypot_enabled=(mode == "both")' in SETUP
