"""Règles pures de SentriX V2.2.

Aucune dépendance Discord ici : ces fonctions sont utilisées par la couche runtime V2.2
et testées séparément en CI. L'objectif est d'améliorer les commandes existantes sans
ajouter une nouvelle surface de commandes.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

MAX_MONEY_INPUT = 2_000_000_000_000
MAX_REASON_LENGTH = 400

_AMOUNT_RE = re.compile(r"^([0-9]+(?:[.,][0-9]+)?)\s*([kmb]?)$", re.IGNORECASE)
_AMOUNT_MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

# Les unités longues passent avant leurs préfixes courts : sinon ``10minutes`` serait
# capturé comme ``10m`` puis rejeté à cause du reste ``inutes``.
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
    """Comprend 1500, 1 500, 1_500, 1.5k, 2m, all/tout/max."""
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
    number_text = match.group(1).replace(",", ".")
    suffix = match.group(2).casefold()
    try:
        number = Decimal(number_text)
    except InvalidOperation:
        return None
    amount_decimal = number * _AMOUNT_MULTIPLIERS[suffix]
    if amount_decimal != amount_decimal.to_integral_value():
        return None
    amount = int(amount_decimal)
    if amount <= 0 or amount > int(maximum):
        return None
    return amount


def clean_reason(value: str | None, *, maximum: int = MAX_REASON_LENGTH) -> str:
    """Nettoie une raison de modération sans perdre son sens ni autoriser un audit énorme."""
    text = str(value or "").replace("\x00", " ").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return "Aucune raison fournie"
    return text[:maximum]


def parse_friendly_duration(value: str | None) -> int | None:
    """Comprend notamment 10m, 1h30m, 2 j 3 h, 1 semaine.

    Du texte parasite n'est pas silencieusement ignoré : ``abc10m`` est refusé.
    """
    text = str(value or "").strip().casefold()
    if not text:
        return None
    total = 0
    cursor = 0
    matched = False
    for match in _DURATION_RE.finditer(text):
        separator = text[cursor:match.start()]
        if separator.strip(" ,;+/"):
            return None
        matched = True
        total += int(match.group("value")) * _DURATION_SECONDS[match.group("unit").casefold()]
        cursor = match.end()
    if not matched or text[cursor:].strip(" ,;+/"):
        return None
    return total if total > 0 else None


def safe_penalty(cash: int, requested: int) -> int:
    """Une amende économique ne peut jamais rendre le portefeuille négatif."""
    return max(0, min(max(0, int(cash)), max(0, int(requested))))


def ttl_is_fresh(saved_at: float, now_value: float, ttl: float) -> bool:
    return ttl > 0 and now_value >= saved_at and (now_value - saved_at) < ttl
