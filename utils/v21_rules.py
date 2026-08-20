"""Règles métier pures de SentriX V2.1.

Ce module reste volontairement sans dépendance Discord/config afin d'être testable en CI.
Il centralise les limites du marché, les succès et les défis affichés par la couche V2.1.
"""
from __future__ import annotations

from dataclasses import dataclass

MARKET_FEE_BPS = 200  # 2 %, détruit de la circulation pour limiter l'inflation.
MARKET_MAX_ACTIVE_PER_USER = 20
MARKET_MAX_QUANTITY = 1_000
MARKET_MAX_UNIT_PRICE = 1_000_000_000
MARKET_MAX_TOTAL = 2_000_000_000_000


@dataclass(frozen=True)
class MarketTotals:
    quantity: int
    unit_price: int
    subtotal: int
    fee: int
    seller_receives: int


def market_totals(quantity: int, unit_price: int, fee_bps: int = MARKET_FEE_BPS) -> MarketTotals:
    quantity = int(quantity)
    unit_price = int(unit_price)
    fee_bps = int(fee_bps)
    if not 1 <= quantity <= MARKET_MAX_QUANTITY:
        raise ValueError("quantité hors limites")
    if not 1 <= unit_price <= MARKET_MAX_UNIT_PRICE:
        raise ValueError("prix unitaire hors limites")
    if not 0 <= fee_bps <= 10_000:
        raise ValueError("taxe invalide")
    subtotal = quantity * unit_price
    if subtotal > MARKET_MAX_TOTAL:
        raise ValueError("total de vente trop élevé")
    fee = (subtotal * fee_bps + 9_999) // 10_000 if fee_bps else 0
    fee = min(fee, subtotal)
    return MarketTotals(quantity, unit_price, subtotal, fee, subtotal - fee)


def clean_market_query(value: str, *, max_length: int = 60) -> str:
    query = " ".join(str(value or "").strip().split())
    if not query:
        raise ValueError("recherche vide")
    return query[:max_length]


def achievement_rows(stats: dict, *, streak: int = 0, best_streak: int = 0,
                     total_claims: int = 0, joined_days: int = 0) -> list[dict]:
    """Retourne tous les succès V2.1 avec leur état, sans accès à la base."""
    messages = max(0, int(stats.get("message_count", 0) or 0))
    level = max(0, int(stats.get("current_level", stats.get("level", 0)) or 0))
    money = max(0, int(stats.get("total_money", 0) or 0))
    reputation = max(0, int(stats.get("reputation", 0) or 0))
    voice = max(0, int(stats.get("voice_time", stats.get("voice_seconds", 0)) or 0))
    total_xp = max(0, int(stats.get("total_xp", 0) or 0))
    streak = max(0, int(streak or 0))
    best_streak = max(streak, int(best_streak or 0))
    total_claims = max(0, int(total_claims or 0))
    joined_days = max(0, int(joined_days or 0))

    specs = (
        ("Premier pas", "Envoyer son premier message ou gagner son premier niveau", messages > 0 or level > 0),
        ("Actif", "Envoyer 100 messages", messages >= 100),
        ("Pilier", "Envoyer 1 000 messages", messages >= 1_000),
        ("Légende du chat", "Envoyer 5 000 messages", messages >= 5_000),
        ("Niveau 10", "Atteindre le niveau 10", level >= 10),
        ("Vétéran XP", "Atteindre le niveau 25", level >= 25),
        ("Maître XP", "Atteindre le niveau 50", level >= 50),
        ("XP colossal", "Accumuler 100 000 XP", total_xp >= 100_000),
        ("Fortuné", "Posséder 10 000 pièces", money >= 10_000),
        ("Millionnaire", "Posséder 1 000 000 pièces", money >= 1_000_000),
        ("Respecté", "Atteindre 10 de réputation", reputation >= 10),
        ("Icône", "Atteindre 100 de réputation", reputation >= 100),
        ("Voix du serveur", "Passer 10 h en vocal", voice >= 36_000),
        ("Toujours connecté", "Passer 100 h en vocal", voice >= 360_000),
        ("Série 7", "7 check-ins consécutifs", best_streak >= 7),
        ("Série 30", "30 check-ins consécutifs", best_streak >= 30),
        ("Fidèle", "Effectuer 100 check-ins", total_claims >= 100),
        ("Ancien", "Être présent depuis 180 jours", joined_days >= 180),
        ("Vétéran du serveur", "Être présent depuis 365 jours", joined_days >= 365),
    )
    return [{"name": name, "description": desc, "unlocked": bool(ok)} for name, desc, ok in specs]


def challenge_rows(stats: dict, *, streak: int = 0) -> list[dict]:
    """Défis permanents à progression visible. Aucun gain n'est attribué ici."""
    messages = max(0, int(stats.get("message_count", 0) or 0))
    level = max(0, int(stats.get("current_level", stats.get("level", 0)) or 0))
    money = max(0, int(stats.get("total_money", 0) or 0))
    reputation = max(0, int(stats.get("reputation", 0) or 0))
    voice_hours = max(0, int(stats.get("voice_time", stats.get("voice_seconds", 0)) or 0) // 3600)
    streak = max(0, int(streak or 0))
    values = (
        ("Discussion", messages, 1_000, "messages"),
        ("Progression", level, 50, "niveaux"),
        ("Fortune", money, 1_000_000, "pièces"),
        ("Communauté", reputation, 100, "réputation"),
        ("Vocal", voice_hours, 100, "heures"),
        ("Régularité", streak, 30, "jours"),
    )
    return [
        {
            "name": name,
            "current": min(current, target),
            "target": target,
            "unit": unit,
            "percent": min(100, round((current / target) * 100)) if target else 100,
            "complete": current >= target,
        }
        for name, current, target, unit in values
    ]
