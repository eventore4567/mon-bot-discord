"""Régression : le mode Vérification seule ne publie jamais un Honeypot actif."""
from pathlib import Path

ENGINE = Path("cogs/honeypot_verification_v48.py").read_text(encoding="utf-8")
SETUP = Path("cogs/setup_v118_integrations.py").read_text(encoding="utf-8")
SECURITY = Path("cogs/security_verification_v71.py").read_text(encoding="utf-8")


def test_modes_are_forwarded_to_both_engine_paths():
    compile(ENGINE, "cogs/honeypot_verification_v48.py", "exec")
    compile(SETUP, "cogs/setup_v118_integrations.py", "exec")
    assert 'honeypot_enabled=(mode == "both")' in SETUP
    assert 'self._set_protections(interaction, True, honeypot_on=(mode == "both"))' in SETUP
    assert 'honeypot_enabled: bool = True' in ENGINE


def test_mode_one_never_publishes_trap_panel_on_initial_install():
    block = ENGINE.split('    async def create_or_refresh_system(', 1)[1].split(
        '    async def ensure_verified_panel_hidden(', 1
    )[0]
    assert 'view_channel=honeypot_enabled' in block
    assert 'send_messages=honeypot_enabled' in block
    assert 'if honeypot_enabled:\n            await panels.envoyer(' in block
    assert 'await self.ensure_verified_panel_hidden(' in block


def test_mode_one_does_not_require_ban_or_kick_permissions():
    block = ENGINE.split('    async def create_or_refresh_system(', 1)[1].split(
        '        old = await self.config(', 1
    )[0]
    assert 'self._missing_permissions(guild, sanction if honeypot_enabled else "")' in block


def test_mode_one_does_not_republish_existing_trap_panel():
    block = ENGINE.split('    async def refresh_existing_panels(', 1)[1].split(
        '    async def disable_system(', 1
    )[0]
    assert 'honeypot_enabled=honeypot_enabled' in block
    assert 'if honeypot_enabled:\n            await panels.envoyer(' in block
    assert 'await _purge_bot_messages(trap_channel, bot_user_id)' in block


def test_no_honeypot_enforcement_without_enabled_setting():
    from_legacy = ENGINE.split('    async def on_message(self, message: discord.Message):', 1)[1]
    from_modern = SECURITY.split('    async def on_message(self, message: discord.Message) -> None:', 1)[1]
    assert 'if not advanced["honeypot_enabled"]:\n            return' in from_legacy
    assert 'if not cfg["honeypot_enabled"]:\n            return' in from_modern


def test_sanction_choice_disabled_for_verification_only():
    assert 'item.disabled = selected != "both"' in SETUP
    assert 'selected == "both" and planned_sanction != sanction' in SETUP
