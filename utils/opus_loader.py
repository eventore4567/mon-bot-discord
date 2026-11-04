"""Chargement de libopus pour la voix (04/11/2026).

discord.py encode l'audio des pistes en Opus avec libopus. Il tente de la trouver
seul, mais l'image python:3.11-slim ne la contenait plus depuis le passage à un
ffmpeg statique : chaque lecture levait ``discord.opus.OpusNotLoaded`` et le
panneau affichait « Le lecteur a rencontré une erreur ». Ce module la charge
explicitement (Dockerfile : paquet libopus0) et le dit clairement si elle manque.
"""
from __future__ import annotations

import ctypes.util
import logging

import discord

logger = logging.getLogger("bot.opus")

_CANDIDATS = (
    "libopus.so.0",
    "libopus.so",
    "/usr/lib/x86_64-linux-gnu/libopus.so.0",
    "/usr/lib/aarch64-linux-gnu/libopus.so.0",
    "/usr/lib/libopus.so.0",
    "/opt/homebrew/lib/libopus.dylib",
    "/usr/local/lib/libopus.dylib",
)
_signale = False


def assurer_opus() -> bool:
    """Vrai si libopus est chargée (la charge au besoin). Ne lève jamais."""
    global _signale
    try:
        if discord.opus.is_loaded():
            return True
    except Exception:  # noqa: BLE001
        pass
    noms = []
    trouve = ctypes.util.find_library("opus")
    if trouve:
        noms.append(trouve)
    noms.extend(_CANDIDATS)
    for nom in noms:
        try:
            discord.opus.load_opus(nom)
        except Exception:  # noqa: BLE001 — chemin absent ou bibliothèque invalide
            continue
        if discord.opus.is_loaded():
            logger.info("libopus chargée : %s", nom)
            return True
    if not _signale:
        _signale = True
        logger.critical(
            "libopus introuvable : la musique ne peut pas jouer. "
            "Installez le paquet système libopus0 (voir Dockerfile)."
        )
    return False


__all__ = ["assurer_opus"]
