"""Mesure du temps passé par chaque écouteur de messages (09/11/2026).

« SentriX est lent » : chaque message passe par environ 35 écouteurs ``on_message``.
Avant de les regrouper, il faut savoir lesquels coûtent vraiment. Cette mesure
chronomètre chaque écouteur ``on_message`` (temps total et nombre d'appels) et
journalise toutes les 10 minutes les plus lents, sans rien changer à leur exécution.

Une seule pose sur ``discord.Client._run_event`` (aucun autre module ne le remplace).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

import discord

logger = logging.getLogger("bot.mesure-ecouteurs")

INTERVALLE_RAPPORT = 600
EVENEMENTS_MESURES = frozenset({"on_message"})

_totaux: dict[str, list[float]] = defaultdict(lambda: [0.0, 0, 0.0])  # total s, appels, max s
_original_run_event = discord.Client._run_event


def _nom(coro) -> str:
    fonction = getattr(coro, "__func__", coro)
    module = getattr(fonction, "__module__", "?") or "?"
    return f"{module.rsplit('.', 1)[-1]}.{getattr(fonction, '__qualname__', '?')}"


async def _run_event_mesure(self, coro, event_name, *args, **kwargs):
    if event_name not in EVENEMENTS_MESURES:
        return await _original_run_event(self, coro, event_name, *args, **kwargs)
    debut = time.perf_counter()
    try:
        return await _original_run_event(self, coro, event_name, *args, **kwargs)
    finally:
        duree = time.perf_counter() - debut
        ligne = _totaux[_nom(coro)]
        ligne[0] += duree
        ligne[1] += 1
        ligne[2] = max(ligne[2], duree)


def rapport(limite: int = 8) -> list[tuple[str, float, int, float]]:
    """(écouteur, total s, appels, max s), du plus coûteux au moins coûteux."""
    lignes = [(nom, v[0], int(v[1]), v[2]) for nom, v in _totaux.items()]
    return sorted(lignes, key=lambda l: l[1], reverse=True)[:limite]


async def _boucle_rapport() -> None:
    while True:
        await asyncio.sleep(INTERVALLE_RAPPORT)
        lignes = rapport()
        if not lignes:
            continue
        logger.info(
            "Écouteurs on_message les plus coûteux (10 min) : %s",
            " | ".join(
                f"{nom} {total:.1f}s/{appels} (moy {1000 * total / max(1, appels):.0f}ms, max {1000 * pire:.0f}ms)"
                for nom, total, appels, pire in lignes
            ),
        )
        _totaux.clear()


def installer(bot) -> bool:
    if getattr(discord.Client._run_event, "_sentrix_mesure", False):
        return False
    _run_event_mesure._sentrix_mesure = True
    discord.Client._run_event = _run_event_mesure
    try:
        bot.loop.create_task(_boucle_rapport(), name="sentrix:mesure-ecouteurs")
    except Exception:  # noqa: BLE001 — boucle pas encore prête : la mesure reste active
        asyncio.get_event_loop().create_task(_boucle_rapport())
    logger.info("Mesure des écouteurs on_message active (rapport toutes les %s s).", INTERVALLE_RAPPORT)
    return True


__all__ = ["installer", "rapport"]
