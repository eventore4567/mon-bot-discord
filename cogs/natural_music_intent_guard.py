"""Protège le langage naturel SentriX contre les faux positifs et les réponses trop scolaires.

Deux protections vivent ici :
- « fais-moi un résumé sur Pythagore » ne doit jamais devenir +resume musique ;
- les messages Discord très courts comme « cv ? » restent une vraie conversation et ne
  doivent jamais déclencher une définition de l'abréviation ni une liste d'exemples.
"""
from __future__ import annotations

import functools
import logging
import re
import unicodedata

from discord.ext import commands

from utils import ai_service

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

# Le modèle comprend déjà ces expressions, mais un fast-path déterministe évite qu'une
# question de small-talk ultra courte soit parfois traitée comme une demande de définition.
# Cela rend aussi « cv ? » quasi instantané puisqu'aucun appel OpenAI n'est nécessaire.
_CASUAL_REPLIES = {
    "cv": "Oui tranquille, et toi ?",
    "ca va": "Oui tranquille, et toi ?",
    "sava": "Oui tranquille, et toi ?",
    "sa va": "Oui tranquille, et toi ?",
    "tu vas bien": "Oui tranquille, et toi ?",
    "comment ca va": "Ça va bien, et toi ?",
    "ca dit quoi": "Tranquille, et toi ?",
    "bien ou quoi": "Oui tranquille, et toi ?",
    "slt": "Salut !",
    "salut": "Salut !",
    "cc": "Coucou !",
    "coucou": "Coucou !",
    "yo": "Yo !",
    "wsh": "Wsh, ça dit quoi ?",
    "t es la": "Oui, je suis là.",
    "tes la": "Oui, je suis là.",
    "tu fais quoi": "Je suis là, je te réponds. Et toi ?",
}

_CASUAL_PROMPT_MARKER = "[SENTRIX_CASUAL_CHAT_V58]"
_CASUAL_PROMPT = (
    "\n\n[SENTRIX_CASUAL_CHAT_V58]\n"
    "Règles de conversation Discord naturelle :\n"
    "- Un message court comme « cv ? », « ça va ? », « slt », « wsh », « yo », « bien ou quoi » "
    "est une conversation, pas une demande de définition. Réponds directement comme dans un chat.\n"
    "- N'explique JAMAIS spontanément le sens d'un mot, d'une abréviation, d'un argot ou d'une "
    "expression si l'utilisateur ne demande pas explicitement sa signification.\n"
    "- Après une réponse de small-talk, n'ajoute ni définition, ni cours, ni liste d'exemples, "
    "ni formulations que l'utilisateur pourrait envoyer.\n"
    "- Pour les messages de conversation très courts, fais généralement une seule phrase courte.\n"
    "- Si l'utilisateur demande explicitement « ça veut dire quoi ? », « ça signifie quoi ? », "
    "« définis » ou équivalent, alors seulement tu peux expliquer le terme."
)


def _normalize_casual_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.casefold().replace("’", "'")
    normalized = re.sub(r"[^a-z0-9' ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _casual_reply(text: str) -> str | None:
    """Réponse locale uniquement pour les small-talks sans ambiguïté.

    Les demandes de définition (« cv veut dire quoi ? ») ne correspondent volontairement
    à aucune clé exacte et continuent donc vers l'IA normalement.
    """
    return _CASUAL_REPLIES.get(_normalize_casual_text(text))


def _install_casual_chat_guard(ai_module) -> None:
    """Ajoute les règles globales et le fast-path aux routes legacy /sentrix/passives."""
    if _CASUAL_PROMPT_MARKER not in ai_service.SYSTEM_PROMPT:
        ai_service.SYSTEM_PROMPT += _CASUAL_PROMPT

    original_ask_ai = ai_module.Ai.ask_ai
    if getattr(original_ask_ai, "_sentrix_casual_chat_v58", False):
        return

    @functools.wraps(original_ask_ai)
    async def casual_aware_ask_ai(self, prompt, *args, **kwargs):
        if isinstance(prompt, str):
            direct = _casual_reply(prompt)
            if direct is not None:
                logger.debug("Réponse small-talk locale SentriX : %r", prompt[:80])
                return direct
        return await original_ask_ai(self, prompt, *args, **kwargs)

    casual_aware_ask_ai._sentrix_casual_chat_v58 = True
    ai_module.Ai.ask_ai = casual_aware_ask_ai
    logger.info("Conversation naturelle IA V58 active : small-talk court sans définition parasite.")


def install(bot: commands.Bot) -> None:
    """Protège Ai contre les faux positifs musique et les réponses de small-talk scolaires."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import ai

    _install_casual_chat_guard(ai)

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
