from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from services.companion.doctor import SentrixDoctor
from services.companion.main import create_app
from services.companion.models import (
    DependencyReport,
    DoctorReport,
    RescueReport,
    SentrixEndpointReport,
)


class FakeDoctor(SentrixDoctor):
    def __init__(self, report: DoctorReport) -> None:
        self.report = report

    async def run(self) -> DoctorReport:
        return self.report


def healthy_report() -> DoctorReport:
    return DoctorReport(
        severity="healthy",
        primary=SentrixEndpointReport(
            name="primary",
            reachable=True,
            http_status=200,
            ok=True,
            discord_ready=True,
            failover_enabled=True,
            state="leader",
            role="primary",
            leader="main",
        ),
        standby=SentrixEndpointReport(
            name="standby",
            reachable=True,
            http_status=200,
            ok=True,
            discord_ready=False,
            failover_enabled=True,
            state="standby",
            role="standby",
            leader="main",
        ),
        redis=DependencyReport(name="redis", configured=True, healthy=True),
        postgres=DependencyReport(name="postgres", configured=True, healthy=True),
        rescue=RescueReport(
            ready=True,
            automatic_failover=True,
            leader_count=1,
            reason="ready",
        ),
        incidents=[],
    )


@pytest.fixture
async def companion_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    report = healthy_report()
    monkeypatch.setenv("COMPANION_ACCESS_TOKEN", "a" * 48)
    monkeypatch.setenv("COMPANION_COOKIE_SECURE", "0")
    app = create_app(lambda: FakeDoctor(report))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_doctor_api_is_private(companion_client: httpx.AsyncClient) -> None:
    response = await companion_client.get("/api/doctor")
    assert response.status_code == 401


async def test_login_then_doctor_report(companion_client: httpx.AsyncClient) -> None:
    login = await companion_client.post("/api/login", json={"access_key": "a" * 48})
    assert login.status_code == 200

    response = await companion_client.get("/api/doctor")
    assert response.status_code == 200
    body = response.json()
    assert body["severity"] == "healthy"
    assert body["rescue"]["ready"] is True
    assert body["rescue"]["leader_count"] == 1
    assert "a" * 48 not in response.text


def test_split_brain_is_critical() -> None:
    primary = healthy_report().primary.model_copy(update={"state": "leader"})
    standby = healthy_report().standby.model_copy(update={"state": "leader"})
    redis = DependencyReport(name="redis", configured=True, healthy=True)
    postgres = DependencyReport(name="postgres", configured=True, healthy=True)

    incidents = SentrixDoctor._incidents(primary, standby, redis, postgres)

    assert any(incident.code == "SPLIT_BRAIN" for incident in incidents)
    assert any(incident.severity == "critical" for incident in incidents)


def test_redis_failure_is_critical() -> None:
    report = healthy_report()
    redis = DependencyReport(name="redis", configured=True, healthy=False)

    incidents = SentrixDoctor._incidents(report.primary, report.standby, redis, report.postgres)

    assert any(incident.code == "REDIS_UNAVAILABLE" for incident in incidents)
