"""Diagnostic operationnel de SentriX et de sa chaine de secours.

Le Doctor reste volontairement en lecture seule : un diagnostic ne doit jamais
pouvoir provoquer un failover, casser un lease Redis ou modifier la production.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import asyncpg
import httpx
from redis.asyncio import Redis

from services.companion.models import (
    DependencyReport,
    DoctorReport,
    Incident,
    RescueReport,
    SentrixEndpointReport,
    Severity,
)

_HTTP_TIMEOUT_SECONDS = 4.0
_DEPENDENCY_TIMEOUT_SECONDS = 3.0


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _http_error_name(exc: Exception) -> str:
    """Retourne une erreur utile sans risquer de recopier URL/token/DSN."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection_error"
    return type(exc).__name__


class SentrixDoctor:
    """Sonde les deux instances et les dependances necessaires au failover."""

    def __init__(
        self,
        *,
        primary_url: str | None = None,
        standby_url: str | None = None,
        redis_url: str | None = None,
        postgres_url: str | None = None,
        http_timeout: float = _HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.primary_url = (primary_url or os.environ.get("SENTRIX_PRIMARY_URL", "")).rstrip("/")
        self.standby_url = (standby_url or os.environ.get("SENTRIX_STANDBY_URL", "")).rstrip("/")
        self.redis_url = (
            redis_url or os.environ.get("COMPANION_REDIS_URL") or os.environ.get("REDIS_URL", "")
        )
        self.postgres_url = (
            postgres_url
            or os.environ.get("COMPANION_DATABASE_URL")
            or os.environ.get("DATABASE_URL", "")
        )
        self.http_timeout = http_timeout

    async def _probe_sentrix(self, name: str, base_url: str) -> SentrixEndpointReport:
        if not base_url:
            return SentrixEndpointReport(name=name, reachable=False, error="not_configured")

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self.http_timeout,
                follow_redirects=False,
            ) as client:
                response = await client.get(f"{base_url}/health")
            latency_ms = round((time.perf_counter() - started) * 1000)
            try:
                raw: Any = response.json()
            except ValueError:
                return SentrixEndpointReport(
                    name=name,
                    reachable=True,
                    http_status=response.status_code,
                    latency_ms=latency_ms,
                    error="invalid_json",
                )
            if not isinstance(raw, dict):
                return SentrixEndpointReport(
                    name=name,
                    reachable=True,
                    http_status=response.status_code,
                    latency_ms=latency_ms,
                    error="invalid_payload",
                )

            failover_raw = raw.get("failover", {})
            failover = failover_raw if isinstance(failover_raw, dict) else {}
            return SentrixEndpointReport(
                name=name,
                reachable=True,
                http_status=response.status_code,
                latency_ms=latency_ms,
                ok=bool(raw.get("ok", response.is_success)),
                discord_ready=bool(raw.get("discord_ready", False)),
                failover_enabled=bool(failover.get("enabled", False)),
                state=_as_text(failover.get("state")),
                role=_as_text(failover.get("role")),
                leader=_as_text(failover.get("leader")),
                error=_as_text(failover.get("error")),
            )
        except httpx.HTTPError as exc:
            return SentrixEndpointReport(
                name=name,
                reachable=False,
                latency_ms=round((time.perf_counter() - started) * 1000),
                error=_http_error_name(exc),
            )

    async def _probe_redis(self) -> DependencyReport:
        if not self.redis_url:
            return DependencyReport(name="redis", configured=False, healthy=False)

        started = time.perf_counter()
        client = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=_DEPENDENCY_TIMEOUT_SECONDS,
            socket_timeout=_DEPENDENCY_TIMEOUT_SECONDS,
        )
        try:
            pong = await asyncio.wait_for(client.ping(), timeout=_DEPENDENCY_TIMEOUT_SECONDS)
            return DependencyReport(
                name="redis",
                configured=True,
                healthy=bool(pong),
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - une sonde doit convertir toute panne en rapport.
            return DependencyReport(
                name="redis",
                configured=True,
                healthy=False,
                latency_ms=round((time.perf_counter() - started) * 1000),
                error_type=type(exc).__name__,
            )
        finally:
            await client.aclose()

    async def _probe_postgres(self) -> DependencyReport:
        if not self.postgres_url:
            return DependencyReport(name="postgres", configured=False, healthy=False)

        started = time.perf_counter()
        connection: asyncpg.Connection | None = None
        try:
            connection = await asyncio.wait_for(
                asyncpg.connect(self.postgres_url, timeout=_DEPENDENCY_TIMEOUT_SECONDS),
                timeout=_DEPENDENCY_TIMEOUT_SECONDS,
            )
            value = await asyncio.wait_for(
                connection.fetchval("SELECT 1"), timeout=_DEPENDENCY_TIMEOUT_SECONDS
            )
            return DependencyReport(
                name="postgres",
                configured=True,
                healthy=value == 1,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - idem : jamais de DSN dans la reponse.
            return DependencyReport(
                name="postgres",
                configured=True,
                healthy=False,
                latency_ms=round((time.perf_counter() - started) * 1000),
                error_type=type(exc).__name__,
            )
        finally:
            if connection is not None:
                await connection.close()

    @staticmethod
    def _incidents(
        primary: SentrixEndpointReport,
        standby: SentrixEndpointReport,
        redis: DependencyReport,
        postgres: DependencyReport,
    ) -> list[Incident]:
        incidents: list[Incident] = []
        leaders = sum(report.state == "leader" for report in (primary, standby))

        if leaders > 1:
            incidents.append(
                Incident(
                    code="SPLIT_BRAIN",
                    severity="critical",
                    title="Deux leaders detectes",
                    detail="Le principal et le standby declarent simultanement l'etat leader.",
                    recommendation=(
                        "Bloquer toute promotion manuelle et verifier immediatement le lease Redis."
                    ),
                )
            )

        if redis.configured and not redis.healthy:
            incidents.append(
                Incident(
                    code="REDIS_UNAVAILABLE",
                    severity="critical",
                    title="Redis indisponible",
                    detail="Le coordinateur HA ne peut plus prouver la possession du lease.",
                    recommendation="Retablir Redis avant toute intervention sur le failover.",
                )
            )

        if postgres.configured and not postgres.healthy:
            incidents.append(
                Incident(
                    code="POSTGRES_UNAVAILABLE",
                    severity="warning",
                    title="PostgreSQL indisponible",
                    detail=(
                        "La restauration durable et les snapshots de secours "
                        "ne peuvent pas etre verifies."
                    ),
                    recommendation=(
                        "Retablir PostgreSQL puis verifier un snapshot avant de tester Rescue."
                    ),
                )
            )

        if not primary.reachable and not standby.reachable:
            incidents.append(
                Incident(
                    code="BOT_CLUSTER_UNREACHABLE",
                    severity="critical",
                    title="Cluster SentriX injoignable",
                    detail="Aucune des deux instances ne repond au healthcheck.",
                    recommendation=(
                        "Verifier l'hebergeur, les domaines et les derniers deploiements."
                    ),
                )
            )
        elif not primary.reachable and standby.state == "leader":
            incidents.append(
                Incident(
                    code="FAILOVER_ACTIVE",
                    severity="warning",
                    title="Rescue a pris la main",
                    detail="Le principal est injoignable et le standby est devenu leader.",
                    recommendation="Diagnostiquer le principal sans interrompre le standby actif.",
                )
            )
        elif primary.state == "leader" and not standby.reachable:
            incidents.append(
                Incident(
                    code="STANDBY_UNREACHABLE",
                    severity="warning",
                    title="Standby injoignable",
                    detail="SentriX fonctionne, mais la redondance n'est plus disponible.",
                    recommendation=(
                        "Retablir le standby avant le prochain deploiement du principal."
                    ),
                )
            )

        failover_expected = primary.failover_enabled or standby.failover_enabled
        if failover_expected and leaders == 0 and (primary.reachable or standby.reachable):
            incidents.append(
                Incident(
                    code="NO_LEADER",
                    severity="critical",
                    title="Aucun leader HA",
                    detail=(
                        "Les instances repondent, mais aucune ne possede "
                        "actuellement le lease leader."
                    ),
                    recommendation=(
                        "Verifier Redis et les journaux HA avant de redemarrer une instance."
                    ),
                )
            )

        for report in (primary, standby):
            if report.reachable and report.http_status is not None and report.http_status >= 500:
                incidents.append(
                    Incident(
                        code=f"{report.name.upper()}_UNHEALTHY",
                        severity="warning",
                        title=f"{report.name.capitalize()} non sain",
                        detail=f"Le healthcheck repond HTTP {report.http_status}.",
                        recommendation="Consulter les logs de cette instance et son etat Discord.",
                    )
                )

        return incidents

    async def run(self) -> DoctorReport:
        primary, standby, redis, postgres = await asyncio.gather(
            self._probe_sentrix("primary", self.primary_url),
            self._probe_sentrix("standby", self.standby_url),
            self._probe_redis(),
            self._probe_postgres(),
        )

        incidents = self._incidents(primary, standby, redis, postgres)
        leader_count = sum(report.state == "leader" for report in (primary, standby))
        automatic_failover = bool(
            redis.healthy
            and primary.failover_enabled
            and standby.failover_enabled
            and leader_count <= 1
        )
        rescue_ready = bool(
            standby.reachable
            and standby.ok
            and redis.healthy
            and postgres.healthy
            and standby.failover_enabled
            and leader_count <= 1
        )

        if rescue_ready:
            rescue_reason = "Standby, lease Redis et stockage durable sont disponibles."
        elif not standby.reachable:
            rescue_reason = "Le standby est injoignable."
        elif not redis.healthy:
            rescue_reason = "Redis ne permet pas de garantir un leader unique."
        elif not postgres.healthy:
            rescue_reason = "PostgreSQL ne permet pas de verifier la restauration durable."
        else:
            rescue_reason = "La chaine de failover n'est pas completement prete."

        severity: Severity
        if any(incident.severity == "critical" for incident in incidents):
            severity = "critical"
        elif incidents:
            severity = "warning"
        else:
            severity = "healthy"

        return DoctorReport(
            severity=severity,
            primary=primary,
            standby=standby,
            redis=redis,
            postgres=postgres,
            rescue=RescueReport(
                ready=rescue_ready,
                automatic_failover=automatic_failover,
                leader_count=leader_count,
                reason=rescue_reason,
            ),
            incidents=incidents,
        )
