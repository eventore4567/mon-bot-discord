"""SentriX V2.5 — qualité runtime sans nouvelle commande.

Cette couche consolide des améliorations transversales qui ne doivent jamais modifier le
catalogue ni les signatures Discord :
- cache très court des réponses NEGATIVES à is_bot_creator() pour éviter deux lectures DB
  répétées sur pratiquement chaque commande d'un membre normal ;
- aucun résultat positif n'est mis en cache, afin qu'un retrait de privilège propriétaire
  soit pris en compte immédiatement ;
- état de santé runtime des protections critiques économie/tickets/jeux/IA ;
- inventaire compact des contrats de commandes contrôlés au démarrage.

Aucune commande publique n'est déclarée ici.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.runtime-quality-v25")

_NEGATIVE_CREATOR_TTL = 15.0
_MAX_NEGATIVE_CACHE = 5000
_INTERNAL_PARAMS = {"ctx", "context", "interaction", "self", "cog", "_ctx"}

# Les commandes ci-dessous ont déjà causé, ou peuvent causer, des régressions très visibles.
# Le contrôle est volontairement petit et strict : il ne modifie jamais la commande.
_CRITICAL_CONTRACTS: dict[str, tuple[str, ...]] = {
    "gamble": ("montant",),
    "pay": ("membre", "montant"),
    "deposit": ("montant",),
    "withdraw": ("montant",),
    "balance": ("membre",),
    "rps": ("choix",),
    "mute": ("membre", "duree", "raison"),
    "tempban": ("membre", "duree", "raison"),
    "ban": ("membre", "raison"),
    "kick": ("membre", "raison"),
}


def _install_negative_creator_cache(bot: commands.Bot) -> None:
    db = getattr(bot, "db", None)
    if db is None:
        return
    current = getattr(db, "is_bot_creator", None)
    if current is None or getattr(current, "_sentrix_v25_negative_cache", False):
        return

    negative_until: dict[int, float] = {}
    stats = {"hits": 0, "misses": 0, "entries": 0}

    async def cached_is_bot_creator(user_id: int) -> bool:
        uid = int(user_id)
        now_value = time.monotonic()
        expires = negative_until.get(uid, 0.0)
        if expires > now_value:
            stats["hits"] += 1
            return False

        # L'appel réel reste la source d'autorité. Un résultat positif n'est JAMAIS mis
        # en cache : une révocation de privilège ne doit pas rester valide à cause du cache.
        result = bool(await current(uid))
        stats["misses"] += 1
        if result:
            negative_until.pop(uid, None)
            return True

        negative_until[uid] = now_value + _NEGATIVE_CREATOR_TTL
        if len(negative_until) > _MAX_NEGATIVE_CACHE:
            stale = [key for key, end in negative_until.items() if end <= now_value]
            for key in stale:
                negative_until.pop(key, None)
            # Si le cache reste énorme malgré le prune, retirer les plus anciens éléments
            # suffit : ce cache n'est qu'une optimisation, jamais une source d'autorité.
            if len(negative_until) > _MAX_NEGATIVE_CACHE:
                overflow = len(negative_until) - _MAX_NEGATIVE_CACHE
                for key in list(negative_until)[:overflow]:
                    negative_until.pop(key, None)
        stats["entries"] = len(negative_until)
        return False

    cached_is_bot_creator._sentrix_v25_negative_cache = True
    cached_is_bot_creator._sentrix_original = current
    db.is_bot_creator = cached_is_bot_creator
    bot._sentrix_v25_creator_cache_stats = stats


def _command_contract_snapshot(bot: commands.Bot) -> dict[str, Any]:
    errors: list[str] = []
    checked = 0

    for command in bot.walk_commands():
        checked += 1
        try:
            names = tuple(str(name) for name in command.clean_params)
        except Exception as exc:
            errors.append(f"{command.qualified_name}: paramètres illisibles ({type(exc).__name__})")
            continue
        leaked = sorted({name.casefold() for name in names} & _INTERNAL_PARAMS)
        if leaked:
            errors.append(f"{command.qualified_name}: paramètre interne visible ({', '.join(leaked)})")

    for name, expected in _CRITICAL_CONTRACTS.items():
        command = bot.get_command(name)
        if command is None:
            # Certaines commandes peuvent être volontairement fusionnées/masquées selon la
            # surface active. Ce n'est critique que si le nom est encore attendu directement.
            continue
        actual = tuple(str(item) for item in command.clean_params)
        if actual != expected:
            errors.append(f"{name}: contrat {actual!r}, attendu {expected!r}")

    return {
        "ready": not errors,
        "errors": tuple(errors),
        "commands_checked": checked,
        "critical_contracts": len(_CRITICAL_CONTRACTS),
    }


def _critical_protection_snapshot(bot: commands.Bot) -> dict[str, bool]:
    return {
        "economy_atomic": bool(getattr(bot, "_sentrix_integrity_economy", False)),
        "ticket_guards": bool(getattr(bot, "_sentrix_integrity_tickets", False)),
        "game_locks": bool(getattr(bot, "_sentrix_integrity_game_locks", False)),
        "permission_guard": bool(getattr(bot, "_sentrix_permission_guard_installed", False)),
        "response_guard": bool(getattr(bot, "_sentrix_response_guard_installed", False)),
        "intelligent_router": bool(
            getattr(bot, "_sentrix_intelligent_router_ready", False)
            or getattr(bot, "_sentrix_v24_primary_ai_listener_guard_fn", None)
        ),
    }


async def _refresh_state_after_ready(bot: commands.Bot) -> None:
    # Les finaliseurs V2.4 sont planifiés pendant le chargement des cogs. Leur laisser un
    # court tour de boucle évite un faux négatif au tout premier on_ready.
    await asyncio.sleep(0.25)
    contracts = _command_contract_snapshot(bot)
    protections = _critical_protection_snapshot(bot)
    cache_stats = getattr(bot, "_sentrix_v25_creator_cache_stats", {})

    bot._sentrix_quality_v25_state = {
        "ready": bool(contracts["ready"]),
        "new_commands": 0,
        "contracts": contracts,
        "protections": protections,
        "creator_cache": dict(cache_stats),
    }

    for error in contracts["errors"]:
        logger.error("V2.5 contrat commande: %s", error)
    if contracts["ready"]:
        logger.info(
            "V2.5 qualité runtime OK : %s commandes et %s contrats critiques contrôlés.",
            contracts["commands_checked"],
            contracts["critical_contracts"],
        )


def install(bot: commands.Bot) -> None:
    """Installation idempotente, sans commande publique et sans mutation de signature."""
    _install_negative_creator_cache(bot)

    if getattr(bot, "_sentrix_quality_v25_installed", False):
        return

    async def refresh_on_ready():
        await _refresh_state_after_ready(bot)

    bot.add_listener(refresh_on_ready, "on_ready")
    bot._sentrix_quality_v25_installed = True
    bot._sentrix_quality_v25_state = {
        "ready": False,
        "new_commands": 0,
        "contracts": {"ready": False, "errors": (), "commands_checked": 0},
        "protections": {},
        "creator_cache": getattr(bot, "_sentrix_v25_creator_cache_stats", {}),
    }
    logger.info("SentriX V2.5 qualité runtime installée : cache DB négatif sûr + contrats; 0 nouvelle commande.")
