"""Évite que le routeur naturel SentriX confonde du français courant avec la musique.

Exemple corrigé : « fais-moi un résumé sur Pythagore » ne doit jamais devenir +resume.
Les commandes musique restent accessibles quand elles sont demandées directement ou quand
la phrase contient un contexte audio/musical clair.
"""
from __future__ import annotations

import logging
import re

from discord.ext import commands

logger = logging.getLogger("bot.ai.natural-music-guard")
_INSTALLED = False

MUSIC_COMMANDS = {
    "join",
    "leave",
    "play",
    "pause",
    "resume",
    "skip",
    "stop",
    "queue",
    "nowplaying",
    "volume",
    "loop",
    "shuffle",
    "remove-from-queue",
    "clear-queue",
    "playlist-save",
    "playlist-load",
}

SUMMARY_PATTERN = re.compile(
    r"\b(resume|resumes|resumer|resumee|resumee?s|synthese|synthetise|synthetiser)\b"
)
MUSIC_CONTEXT_PATTERN = re.compile(
    r"\b(musique|musiques|chanson|chansons|audio|son|sons|lecture|playlist|playlist[s]?|"
    r"vocal|voice|track|titre|file d['’ ]?attente|volume)\b"
)
PLAYBACK_RESUME_PATTERN = re.compile(
    r"\b(reprend|reprends|reprendre|continue|continuer|relance|relancer)\b"
)


def install(bot: commands.Bot) -> None:
    """Protège Ai._natural_command_line contre les faux positifs de commandes musique."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import ai

    original = ai.Ai._natural_command_line
    if getattr(original, "_sentrix_music_intent_guard", False):
        _INSTALLED = True
        return

    def guarded_natural_command_line(
        self,
        question: str,
        prefix: str,
        *,
        has_attachment: bool,
    ) -> str | None:
        normalized = self._normalize_request(question)

        # L'accent est volontairement retiré par _normalize_request : « résumé » devient
        # donc « resume ». On donne la priorité au sens scolaire/IA avant toute recherche
        # de commande. Une vraie reprise audio formulée avec « reprends/relance » reste libre.
        if SUMMARY_PATTERN.search(normalized):
            explicit_playback_resume = bool(
                PLAYBACK_RESUME_PATTERN.search(normalized)
                and MUSIC_CONTEXT_PATTERN.search(normalized)
            )
            if not explicit_playback_resume:
                return None

        command_line = original(
            self,
            question,
            prefix,
            has_attachment=has_attachment,
        )
        if not command_line:
            return None

        raw = command_line[len(prefix):] if command_line.startswith(prefix) else command_line
        command_name = raw.split(maxsplit=1)[0].casefold()
        if command_name not in MUSIC_COMMANDS:
            return command_line

        # Une commande musique trouvée au milieu d'une phrase n'est exécutée que si la
        # phrase parle réellement d'audio. « SentriX pause » / « SentriX play X » restent
        # valides parce que le nom de commande est alors le début explicite de la demande.
        direct_music_command = bool(
            re.match(rf"^\s*{re.escape(command_name)}(?:\s|$)", normalized)
        )
        has_music_context = bool(MUSIC_CONTEXT_PATTERN.search(normalized))
        if not direct_music_command and not has_music_context:
            logger.info(
                "Commande musique naturelle ignorée (faux positif probable) : %s <- %r",
                command_name,
                question[:160],
            )
            return None

        return command_line

    guarded_natural_command_line._sentrix_music_intent_guard = True
    ai.Ai._natural_command_line = guarded_natural_command_line
    _INSTALLED = True
    logger.info("Protection des intentions musique du langage naturel activée.")
