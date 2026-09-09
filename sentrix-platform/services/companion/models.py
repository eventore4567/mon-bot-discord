"""Modeles publics du diagnostic SentriX Companion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["healthy", "warning", "critical"]


class SentrixEndpointReport(BaseModel):
    """Etat observe d'une instance SentriX via son endpoint /health."""

    name: str
    reachable: bool
    http_status: int | None = None
    latency_ms: int | None = None
    ok: bool = False
    discord_ready: bool = False
    failover_enabled: bool = False
    state: str | None = None
    role: str | None = None
    leader: str | None = None
    error: str | None = None


class DependencyReport(BaseModel):
    """Etat d'une dependance partagee, sans exposer sa chaine de connexion."""

    name: str
    configured: bool
    healthy: bool
    latency_ms: int | None = None
    error_type: str | None = None


class Incident(BaseModel):
    """Incident deduit des sondes et accompagne d'une action recommandee."""

    code: str
    severity: Literal["warning", "critical"]
    title: str
    detail: str
    recommendation: str


class RescueReport(BaseModel):
    """Capacite du standby a prendre la main proprement."""

    ready: bool
    automatic_failover: bool
    leader_count: int
    reason: str


class DoctorReport(BaseModel):
    """Rapport complet et redige pour etre directement exploitable par l'app."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    severity: Severity
    primary: SentrixEndpointReport
    standby: SentrixEndpointReport
    redis: DependencyReport
    postgres: DependencyReport
    rescue: RescueReport
    incidents: list[Incident]
