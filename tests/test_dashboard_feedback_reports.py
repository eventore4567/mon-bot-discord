from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_feedback_backend_stores_minimal_safe_context():
    source = (ROOT / "web" / "dashboard_feedback_reports.py").read_text(encoding="utf-8")

    assert "dashboard_feedback_reports" in source
    assert "guild_id INTEGER NOT NULL" in source
    assert "user_id INTEGER NOT NULL" in source
    assert "kind TEXT NOT NULL" in source
    assert "message TEXT NOT NULL" in source
    assert "technical TEXT NOT NULL" in source
    assert "release TEXT NOT NULL" in source
    assert "peername" not in source
    assert "authorization" not in source.casefold()
    assert "oauth_token" not in source.casefold()


def test_dashboard_feedback_requires_managed_guild_csrf_and_rate_limit():
    source = (ROOT / "web" / "dashboard_feedback_reports.py").read_text(encoding="utf-8")

    assert "_manageable_guild" in source
    assert "_require_csrf" in source
    assert '"dashboard-feedback"' in source
    assert "now - last < 10" in source


def test_dashboard_contains_feedback_button_dialog_and_api_call():
    source = (ROOT / "web" / "dashboard.py").read_text(encoding="utf-8")

    assert 'id="feedbackButton"' in source
    assert 'id="feedbackDialog"' in source
    assert 'id="feedbackMessage"' in source
    assert 'id="feedbackTechnical"' in source
    assert "/api/guilds/${state.guildId}/feedback" in source
    assert "register_feedback_routes" in source


def test_feedback_inbox_is_owner_only_and_visible_in_dashboard():
    backend = (ROOT / "web" / "dashboard_feedback_reports.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "web" / "dashboard.py").read_text(encoding="utf-8")

    assert "await bot.is_owner(" in backend
    assert "Accès réservé au propriétaire du bot." in backend
    assert "ORDER BY id DESC" in backend
    assert "LIMIT 50" in backend
    assert 'id="feedbackAdmin"' in dashboard
    assert 'id="feedbackRefresh"' in dashboard
    assert "loadFeedbackReports" in dashboard
    assert "state.developer=Boolean(me.developer)" in dashboard
