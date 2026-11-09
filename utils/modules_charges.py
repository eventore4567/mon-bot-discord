"""Quels fichiers du bot ne sont JAMAIS chargés en production (10/11/2026).

« Rends les fichiers plus simples. » Avant de supprimer des fichiers, il faut savoir
avec certitude lesquels ne servent à rien : l'analyse hors ligne n'est pas fiable (le
démarrage de test diffère de la production). Le bot fait donc lui-même le constat, une
fois, quelques minutes après le démarrage : il compare les fichiers ``cogs``, ``utils``,
``web`` et ``database`` présents sur le disque à ceux réellement importés, et journalise
la liste des fichiers jamais chargés. Lecture seule : rien n'est modifié.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger("bot.modules-charges")

RACINE = Path(__file__).resolve().parents[1]
PAQUETS = ("cogs", "utils", "web", "database")
DELAI = 180
TAILLE_LIGNE = 1500


def modules_sur_disque(racine: Path = RACINE) -> set[str]:
    noms: set[str] = set()
    for paquet in PAQUETS:
        dossier = racine / paquet
        if not dossier.is_dir():
            continue
        for fichier in dossier.rglob("*.py"):
            if "__pycache__" in fichier.parts:
                continue
            relatif = fichier.relative_to(racine).with_suffix("")
            parties = list(relatif.parts)
            if parties[-1] == "__init__":
                parties.pop()
            noms.add(".".join(parties))
    return noms


def jamais_charges(racine: Path = RACINE, charges=None) -> list[str]:
    charges = set(sys.modules if charges is None else charges)
    return sorted(nom for nom in modules_sur_disque(racine) if nom not in charges and nom not in PAQUETS)


def _lignes(noms: list[str], taille: int = TAILLE_LIGNE) -> list[str]:
    lignes, courante = [], ""
    for nom in noms:
        ajout = nom if not courante else f", {nom}"
        if courante and len(courante) + len(ajout) > taille:
            lignes.append(courante)
            courante = nom
        else:
            courante += ajout
    if courante:
        lignes.append(courante)
    return lignes


async def _constat(delai: float) -> None:
    await asyncio.sleep(delai)
    noms = jamais_charges()
    total = len(modules_sur_disque())
    logger.info("FICHIERS JAMAIS CHARGÉS : %s sur %s (%s s après le démarrage).", len(noms), total, int(delai))
    for index, ligne in enumerate(_lignes(noms), start=1):
        logger.info("FICHIERS JAMAIS CHARGÉS (%s) : %s", index, ligne)


def installer(bot, delai: float = DELAI) -> None:
    if getattr(bot, "_sentrix_constat_modules", False):
        return
    bot._sentrix_constat_modules = True
    asyncio.get_running_loop().create_task(_constat(delai), name="sentrix:modules-jamais-charges")


__all__ = ["installer", "jamais_charges", "modules_sur_disque"]
