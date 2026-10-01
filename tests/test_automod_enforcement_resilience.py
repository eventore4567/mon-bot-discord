from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_automod_enforcement_survives_telemetry_failures():
    source = (ROOT / "cogs" / "automod.py").read_text(encoding="utf-8")

    assert "Historique AutoMod indisponible après suppression" in source
    assert "Score de risque AutoMod indisponible" in source
    assert "Escalade AutoMod indisponible" in source
    assert "Historique de sanction AutoMod indisponible" in source


def test_automod_incident_defaults_are_defined_before_escalation():
    source = (ROOT / "cogs" / "automod.py").read_text(encoding="utf-8")

    assert "action = None" in source
    assert "infraction_count = 0" in source
    assert "spam_public_text = None" in source
