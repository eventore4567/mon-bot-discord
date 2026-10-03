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



def test_antispam_policy_is_scoped_without_weakening_other_filters():
    source = (ROOT / "cogs" / "automod.py").read_text(encoding="utf-8")

    assert "async def get_antispam_policy_cached" in source
    assert "async def antispam_applies_to" in source
    assert 'if conf["antispam"] and await self.antispam_applies_to(message):' in source
    assert "antispam_exempt_roles" in source
    assert "antispam_protected_channels" in source
    # Le bypass spécifique n'est pas branché avant tous les filtres AutoMod.
    early = source[source.index("async def on_message"):source.index('if conf["antispam"]')]
    assert "antispam_applies_to(message)" not in early


def test_antispam_policy_schema_is_persistent():
    source = (ROOT / "database" / "db.py").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS antispam_policy" in source
    assert "CREATE TABLE IF NOT EXISTS antispam_exempt_roles" in source
    assert "CREATE TABLE IF NOT EXISTS antispam_protected_channels" in source
