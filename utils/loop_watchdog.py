"""Détecteur de blocage de la boucle asyncio : dit QUEL code gèle le bot.

27/10/2026 : en production, des requêtes triviales (« SELECT 1 » à 327 ms) étaient
lentes PAR PAQUETS, à la même seconde, sans lien entre elles — la signature d'une
boucle bloquée par du calcul synchrone, pas d'une base lente (mesuré : voir la
mémoire « la lenteur ne vient pas de la base »). Tant qu'on ne voit pas la pile du
code bloquant, on corrige au hasard.

Principe : une tâche asyncio avance un horodatage toutes les 0,25 s ; un fil
séparé vérifie qu'il avance. Si la boucle reste figée plus de SEUIL_S, le fil lit
la pile du fil principal (sys._current_frames) et journalise les cadres du code
SentriX — une seule fois par blocage. Coût : un horodatage et une comparaison.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback

logger = logging.getLogger("bot.loop-watchdog")

SEUIL_S = 1.0
INTERVALLE_S = 0.25
_CE_FICHIER = os.path.abspath(__file__)
_RACINE = os.path.dirname(os.path.dirname(_CE_FICHIER))

_etat = {"dernier": time.monotonic(), "actif": False, "generation": 0}


def cadres_sentrix(frame, limite: int = 6) -> list[str]:
    """Les cadres du code du dépôt, du plus profond au plus haut."""
    lignes = []
    for f in reversed(traceback.extract_stack(frame)):
        if f.filename.startswith(_RACINE) and os.path.abspath(f.filename) != _CE_FICHIER:
            lignes.append(f"{os.path.relpath(f.filename, _RACINE)}:{f.lineno} {f.name}")
            if len(lignes) >= limite:
                break
    return lignes


async def _battre(generation: int) -> None:
    # Une tâche liée à un ancien cycle ne modifie jamais le battement du nouveau.
    while _etat["actif"] and _etat["generation"] == generation:
        _etat["dernier"] = time.monotonic()
        await asyncio.sleep(INTERVALLE_S)


def _surveiller(fil_principal: int, generation: int) -> None:
    signale = False
    while _etat["actif"] and _etat["generation"] == generation:
        time.sleep(INTERVALLE_S)
        # arreter() peut être appelé pendant le sommeil. Ne pas publier un
        # avertissement périmé dans une session suivante du watchdog.
        if not _etat["actif"] or _etat["generation"] != generation:
            return
        retard = time.monotonic() - _etat["dernier"]
        if retard < SEUIL_S:
            signale = False
            continue
        if signale:
            continue
        signale = True
        frame = sys._current_frames().get(fil_principal)
        pile = cadres_sentrix(frame) if frame is not None else []
        logger.warning(
            "Boucle bloquée depuis %.1f s — %s",
            retard, " ← ".join(pile) if pile else "hors du code SentriX (bibliothèque ou E/S synchrone)",
        )


def demarrer(loop: asyncio.AbstractEventLoop | None = None) -> bool:
    """Idempotent. Renvoie True si le détecteur vient d'être lancé."""
    if _etat["actif"]:
        return False
    loop = loop or asyncio.get_event_loop()
    _etat["generation"] += 1
    generation = _etat["generation"]
    _etat["actif"] = True
    _etat["dernier"] = time.monotonic()
    loop.create_task(_battre(generation), name="sentrix:loop-watchdog")
    threading.Thread(target=_surveiller, args=(threading.get_ident(), generation), name="sentrix-loop-watchdog",
                     daemon=True).start()
    return True


def arreter() -> None:
    _etat["actif"] = False
    _etat["generation"] += 1


__all__ = ["demarrer", "arreter", "cadres_sentrix", "SEUIL_S"]
