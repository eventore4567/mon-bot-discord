"""Vérification et Honeypot : deux modes explicites, sans activation forcée.

Le moteur V5 garde ses ressources existantes ; la distinction est entre
protections ACTIVES, pas entre catégories recréées à chaque changement.
"""
from pathlib import Path

SETUP = Path("cogs/setup_v118_integrations.py").read_text("utf-8")
SECURITY = Path("cogs/setup_security_choice_v75.py").read_text("utf-8")
ENGINE = Path("cogs/honeypot_verification_v48.py").read_text("utf-8")


def test_both_modes_are_selectable_inside_the_same_panel():
    compile(SETUP, "setup_v118_integrations.py", "exec")
    assert 'value="verification"' in SETUP
    assert 'value="both"' in SETUP
    assert "Vérification seule" in SETUP
    assert "Vérification + Honeypot" in SETUP
    assert "min_values=1" in SETUP and "max_values=1" in SETUP
    assert 'mode = self.mode or' in SETUP
    assert "self._apply(interaction)" in SETUP


def test_kick_and_softban_are_options_not_activation_shortcuts():
    assert 'value="softban"' in SETUP
    assert 'value="kick"' in SETUP
    assert "self.sanction = sanction_select.values[0]" in SETUP
    assert "Activer / mettre à jour" in SETUP


def test_choices_require_explicit_apply():
    assert "await self._set_protections(interaction, True, honeypot_on=(mode == \"both\"))" in SETUP
    assert "await self._set_protections(interaction, False)" in SETUP
    assert "Choix non appliqué" in SETUP


def test_verification_only_does_not_disable_the_underlying_verification_engine():
    compile(SECURITY, "setup_security_choice_v75.py", "exec")
    assert "int(bool(honeypot_enabled or verification_enabled))" in SECURITY
    assert 'not (chosen & {"honeypot", "verification"})' in SECURITY


def test_honeypot_is_hidden_and_never_sanctions_in_verification_only():
    compile(ENGINE, "honeypot_verification_v48.py", "exec")
    assert "view_channel=trap_active" in ENGINE
    assert "send_messages=trap_active" in ENGINE
    on_msg = ENGINE.split("    async def on_message(self, message: discord.Message):", 1)[1]
    assert 'if not advanced["honeypot_enabled"]:\n            return' in on_msg
    assert on_msg.index('if not advanced["honeypot_enabled"]') < on_msg.index('sanction = str(conf["sanction"]')
