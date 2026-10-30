"""Vérification en lecture seule des abonnements Discord SentriX Premium.

Pas de SKU configuré = aucune fonction verrouillée et aucune requête réseau.
La monétisation exige une application et un compte éligibles dans le portail
Discord. Aucun achat n'est initié par ce module.
"""
from __future__ import annotations

import logging
import os
import time

import discord

logger = logging.getLogger("bot.premium")
TTL_SECONDS = 300
_CACHE: dict[tuple[int, int], tuple[float, bool]] = {}


def premium_sku_id() -> int | None:
    raw = str(os.getenv("SENTRIX_PREMIUM_SKU_ID", "")).strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if value > 0 else None


def _active(entitlement, guild_id: int, sku_id: int) -> bool:
    if int(getattr(entitlement, "guild_id", 0) or 0) != guild_id:
        return False
    if int(getattr(entitlement, "sku_id", 0) or 0) != sku_id:
        return False
    if getattr(entitlement, "deleted", False):
        return False
    now = discord.utils.utcnow()
    start = getattr(entitlement, "starts_at", None)
    end = getattr(entitlement, "ends_at", None)
    return (start is None or start <= now) and (end is None or end > now)


async def est_premium(bot, guild_id: int) -> bool:
    """Vrai seulement en présence d'un abonnement serveur valide et actif.

    Cache 5 minutes, lecture ciblée des entitlements de ce serveur, pas de
    balayage global des abonnements. En cas d'erreur Discord : fail-closed.
    """
    sku_id = premium_sku_id()
    if sku_id is None or not guild_id:
        return False
    key = (int(guild_id), sku_id)
    cached = _CACHE.get(key)
    now = time.monotonic()
    if cached and now < cached[0]:
        return cached[1]

    result = False
    try:
        iterator = bot.entitlements(
            guild=discord.Object(id=int(guild_id)),
            skus=[discord.Object(id=sku_id)],
            limit=100,
            exclude_ended=True,
            exclude_deleted=True,
        )
        async for entitlement in iterator:
            if _active(entitlement, int(guild_id), sku_id):
                result = True
                break
    except (discord.HTTPException, discord.ClientException, AttributeError, TypeError) as error:
        logger.warning("Vérification Premium indisponible (type=%s).", type(error).__name__)
        return False

    _CACHE[key] = (now + TTL_SECONDS, result)
    return result


def invalider(guild_id: int | None = None) -> None:
    if guild_id is None:
        _CACHE.clear()
    else:
        for key in list(_CACHE):
            if key[0] == int(guild_id):
                _CACHE.pop(key, None)
