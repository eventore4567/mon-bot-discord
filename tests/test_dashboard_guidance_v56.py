from __future__ import annotations

from pathlib import Path

SOURCE = Path("web/dashboard_guidance_v56.py").read_text(encoding="utf-8")
INIT_SOURCE = Path("web/__init__.py").read_text(encoding="utf-8")


def test_guidance_v56_is_wired_into_dashboard():
    assert "dashboard_guidance_v56 as _dashboard_guidance_v56" in INIT_SOURCE
    assert "_dashboard_guidance_v56.install(_dashboard)" in INIT_SOURCE


def test_feedback_collects_only_minimal_technical_context():
    assert "dashboard_feedback_v1" in SOURCE
    assert '"tab": _clean(technical.get("tab"), 40)' in SOURCE
    assert '"error": _clean(technical.get("error"), 240)' in SOURCE
    assert '"viewport": _clean(technical.get("viewport"), 40)' in SOURCE
    assert "cookies" not in SOURCE.casefold()
    assert "user-agent" not in SOURCE.casefold()
    assert "stack" not in SOURCE.casefold()


def test_feedback_is_rate_limited_and_csrf_protected():
    assert "write=True" in SOURCE
    assert "created_at>=?" in SOURCE
    assert ">= 3" in SOURCE
    assert "429" in SOURCE


def test_diagnostic_covers_requested_core_systems():
    for marker in (
        "Permissions Discord incomplètes",
        "Hiérarchie des rôles à corriger",
        "Routes de logs cassées",
        "Tickets à terminer",
        "IA activée mais fournisseur indisponible",
        "Accueil non configuré",
    ):
        assert marker in SOURCE


def test_only_safe_reversible_repairs_are_automatic():
    assert 'action == "disable_invalid_logs"' in SOURCE
    assert 'action == "disable_orphan_ticket_panels"' in SOURCE
    assert "channel_id=None" in SOURCE
    assert "SET enabled=0" in SOURCE
    assert "create_channel(" not in SOURCE
    assert "create_category(" not in SOURCE
    assert "create_role(" not in SOURCE


def test_onboarding_is_exactly_security_logs_tickets_welcome():
    start = SOURCE.index("onboarding = [")
    end = SOURCE.index("systems = [", start)
    onboarding = SOURCE[start:end]
    for name in ("Sécurité", "Logs", "Tickets", "Bienvenue"):
        assert name in onboarding
    assert onboarding.count('"key":') == 4


def test_dashboard_has_feedback_and_guidance_entries():
    assert 'id="sentrix-guidance-v56-js"' in SOURCE
    assert "Centre de diagnostic" in SOURCE
    assert "Configuration guidée" in SOURCE
    assert "Bug / Avis" in SOURCE
    assert "/diagnostic" in SOURCE
    assert "/onboarding" in SOURCE


def test_routes_are_guild_scoped_and_use_manageable_guild():
    assert "dashboard._manageable_guild(request, guild_id)" in SOURCE
    assert "/api/guilds/{guild_id}/diagnostic-v1" in SOURCE
    assert "/api/guilds/{guild_id}/feedback-v1" in SOURCE
