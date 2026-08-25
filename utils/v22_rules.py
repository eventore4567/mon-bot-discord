"""Règles pures de compatibilité pour montants, durées et raisons.

Ces helpers ne dépendent pas de Discord et restent utilisés par plusieurs commandes.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

MAX_MONEY_INPUT = 2_000_000_000_000
MAX_REASON_LENGTH = 400

_AMOUNT_RE = re.compile(r"^([0-9]+(?:[.,][0-9]+)?)\s*([kmb]?)$", re.IGNORECASE)
_AMOUNT_MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

# Toujours tester les mots longs avant les unités à une lettre. Sinon « semaine » était
# capturé comme « s » puis rejeté à cause du reste « emaine ».
_DURATION_RE = re.compile(
    r"(?P<value>\d+)\s*(?P<unit>"
    r"secondes|seconde|secs|sec|"
    r"minutes|minute|mins|min|"
    r"heures|heure|"
    r"semaines|semaine|sem|"
    r"jours|jour|"
    r"s|m|h|j|d|w"
    r")",
    re.IGNORECASE,
)
_DURATION_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "seconde": 1, "secondes": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "heure": 3600, "heures": 3600,
    "j": 86400, "d": 86400, "jour": 86400, "jours": 86400,
    "w": 604800, "sem": 604800, "semaine": 604800, "semaines": 604800,
}


def parse_friendly_amount(value: str, available: int | None = None, *, maximum: int = MAX_MONEY_INPUT) -> int | None:
    raw = str(value or "").strip().casefold()
    if raw in {"all", "tout", "max"}:
        if available is None:
            return None
        amount = int(available)
        return amount if 0 < amount <= maximum else None
    compact = raw.replace(" ", "").replace("_", "")
    match = _AMOUNT_RE.fullmatch(compact)
    if not match:
        return None
    try:
        number = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    amount_decimal = number * _AMOUNT_MULTIPLIERS[match.group(2).casefold()]
    if amount_decimal != amount_decimal.to_integral_value():
        return None
    amount = int(amount_decimal)
    return amount if 0 < amount <= int(maximum) else None


def clean_reason(value: str | None, *, maximum: int = MAX_REASON_LENGTH) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return (text or "Aucune raison fournie")[:maximum]


def parse_friendly_duration(value: str | None) -> int | None:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    total, cursor, matched = 0, 0, False
    for match in _DURATION_RE.finditer(text):
        if text[cursor:match.start()].strip(" ,;+/\t"):
            return None
        matched = True
        total += int(match.group("value")) * _DURATION_SECONDS[match.group("unit").casefold()]
        cursor = match.end()
    if not matched or text[cursor:].strip(" ,;+/\t"):
        return None
    return total if total > 0 else None


def safe_penalty(cash: int, requested: int) -> int:
    return max(0, min(max(0, int(cash)), max(0, int(requested))))


def ttl_is_fresh(saved_at: float, now_value: float, ttl: float) -> bool:
    return ttl > 0 and now_value >= saved_at and (now_value - saved_at) < ttl
