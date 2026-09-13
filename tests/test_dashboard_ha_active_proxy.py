from __future__ import annotations

from web import persistent_dashboard_sessions as ha


def test_primary_uses_standby_internal_url(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ROLE", "primary")
    monkeypatch.setenv(
        "SENTRIX_HA_STANDBY_INTERNAL_URL",
        "sentrix-standby.railway.internal:8080",
    )
    monkeypatch.delenv("RAILWAY_SERVICE_SENTRIX_STANDBY_URL", raising=False)

    assert ha._peer_dashboard_url() == "http://sentrix-standby.railway.internal:8080"


def test_standby_uses_primary_internal_url(monkeypatch):
    monkeypatch.setenv("SENTRIX_FAILOVER_ROLE", "standby")
    monkeypatch.setenv(
        "SENTRIX_HA_PRIMARY_INTERNAL_URL",
        "http://mon-bot-discord.railway.internal:8080",
    )
    monkeypatch.delenv("RAILWAY_SERVICE_MON_BOT_DISCORD_URL", raising=False)

    assert ha._peer_dashboard_url() == "http://mon-bot-discord.railway.internal:8080"


def test_only_discord_dependent_dashboard_apis_are_proxy_candidates():
    assert ha._proxy_candidate_path("/api/public")
    assert ha._proxy_candidate_path("/api/guilds")
    assert ha._proxy_candidate_path("/api/guilds/123")
    assert ha._proxy_candidate_path("/api/guilds/123/settings")

    assert not ha._proxy_candidate_path("/api/me")
    assert not ha._proxy_candidate_path("/health")
    assert not ha._proxy_candidate_path("/app")
