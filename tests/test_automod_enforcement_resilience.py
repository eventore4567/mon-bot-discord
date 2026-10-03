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



def test_security_bypass_is_per_filter_and_strict_channels_take_priority():
    source = (ROOT / "cogs" / "automod.py").read_text(encoding="utf-8")

    assert "async def get_security_filter_policy_cached" in source
    assert "async def security_filter_applies_to" in source
    assert "SECURITY_FILTER_POLICY_KEYS" in source
    assert '"antispam"' in source
    assert '"antilink"' in source
    assert '"antiscam"' in source
    assert '"antiinsult"' in source
    assert 'if conf["antispam"] and await self.security_filter_applies_to(message, "antispam"):' in source

    helper = source[
        source.index("async def security_filter_applies_to"):
        source.index("async def get_antispam_policy_cached")
    ]
    # Le salon strict est évalué avant les rôles bypass, y compris les anciens
    # rôles d'exemption AutoMod globaux.
    assert helper.index("if strict:") < helper.index('if policy["role_ids"]')
    assert helper.index("if strict:") < helper.index("get_exempt_roles_cached")


def test_security_filter_policy_schema_is_persistent_and_legacy_safe():
    source = (ROOT / "database" / "db.py").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS security_filter_bypass_roles" in source
    assert "CREATE TABLE IF NOT EXISTS security_filter_strict_channels" in source
    assert "async def get_security_filter_policy" in source
    assert "async def set_security_filter_policy" in source

    # Les tables V1 restent présentes pendant la migration/rolling deploy.
    assert "CREATE TABLE IF NOT EXISTS antispam_policy" in source
    assert "CREATE TABLE IF NOT EXISTS antispam_exempt_roles" in source
    assert "CREATE TABLE IF NOT EXISTS antispam_protected_channels" in source
