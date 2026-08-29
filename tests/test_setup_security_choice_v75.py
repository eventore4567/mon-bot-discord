from pathlib import Path


SOURCE = Path("cogs/setup_security_choice_v75.py").read_text(encoding="utf-8")


def test_v75_compiles():
    compile(SOURCE, "cogs/setup_security_choice_v75.py", "exec")


def test_security_protections_are_individually_selectable():
    assert "Choisir les protections anti à activer" in SOURCE
    assert "setup_ui.AUTOMOD" in SOURCE
    assert '"honeypot"' in SOURCE
    assert '"verification"' in SOURCE
    assert "min_values=0" in SOURCE
    assert "max_values=total" in SOURCE


def test_command_permissions_are_not_manual_security_options():
    assert "Les permissions **Kick, Ban, Timeout" in SOURCE
    assert "permissions Discord réelles" in SOURCE
    assert "Aucun rôle `kick`, `ban` ou autre n'est à configurer" in SOURCE


def test_module_state_tracks_selected_protections():
    assert '"security",\n        bool(chosen)' in SOURCE
    assert 'states["security"] = "● ACTIF" if selected else "○ INACTIF"' in SOURCE
