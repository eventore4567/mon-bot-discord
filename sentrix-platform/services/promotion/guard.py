"""P6 canary promotion and destructive-schema guards."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DESTRUCTIVE_SQL = re.compile(
    r"\b(?:DROP\s+(?:TABLE|COLUMN|CONSTRAINT|TYPE)|ALTER\s+(?:TABLE\s+\S+\s+)?COLUMN\s+\S+\s+TYPE|TRUNCATE\s+TABLE)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CanaryResult:
    healthy: bool
    started_at: float
    observed_until: float
    application_id: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    allowed: bool
    reason: str
    requires_human_confirmation: bool = False


def contains_destructive_migration(sql: str) -> bool:
    # Strip simple comments before scanning to avoid obvious false positives in
    # documentation. This is a guard, not a SQL parser: unknown constructs fail
    # conservatively at review time.
    cleaned = re.sub(r"--[^\n]*", "", sql)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    return bool(_DESTRUCTIVE_SQL.search(cleaned))


def decide_promotion(
    *,
    prod_application_id: str,
    canary: CanaryResult,
    bake_seconds: float,
    migration_sql: str = "",
    human_confirmed_destructive: bool = False,
) -> PromotionDecision:
    if not canary.application_id or canary.application_id == prod_application_id:
        return PromotionDecision(False, "canary must use a distinct Discord application")
    if not canary.healthy:
        return PromotionDecision(False, "canary is unhealthy")
    if canary.observed_until - canary.started_at < bake_seconds:
        return PromotionDecision(False, "canary bake time incomplete")
    if contains_destructive_migration(migration_sql) and not human_confirmed_destructive:
        return PromotionDecision(
            False, "destructive migration requires explicit human confirmation", True
        )
    return PromotionDecision(True, "promotion gates passed")
