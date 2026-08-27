"""Personnalité adaptative finale de SentriX AI.

Le moteur reste sérieux et compétent pour toute vraie demande. Les messages purement
provocateurs, insultants ou volontairement vides déclenchent seulement une répartie
courte, froide et sarcastique. Une demande utile formulée agressivement reste traitée
normalement : la personnalité ne doit jamais réduire la qualité de l'aide.
"""
from __future__ import annotations

import functools
import logging
import re
import unicodedata

from utils import ai_service

logger = logging.getLogger("bot.ai-personality-final")
_MARKER = "_sentrix_dynamic_personality_final"

_HOSTILE_PATTERNS = (
    r"\b(?:con|conne|connard|connasse|idiot|idiote|debile|débile|nul|nulle|merde|tg|ta\s+gueule|"
    r"ferme[- ]?(?:la|toi)|ferme\s+ta\s+gueule|abruti|abrutie|clown|bouffon)\b",
    r"\b(?:stupid|idiot|dumb|trash|shut\s+up|useless|moron)\b",
)

_LOW_EFFORT = frozenset({
    "rien", "osef", "bof", "jsp", "j sais pas", "je sais pas", "lol", "mdr", "ptdr",
    "ok", "okay", "k", "whatever", "random", "hein", "quoi", "bruh",
})

_SERIOUS_MARKERS = (
    "aide", "aidez", "explique", "expliquer", "comment", "pourquoi", "corrige", "corriger",
    "code", "script", "programme", "bug", "erreur", "analyse", "analyser", "resume", "résume",
    "traduis", "traduire", "donne", "cherche", "recherche", "cree", "crée", "faire", "fais",
    "peux tu", "peux-tu", "pourrais tu", "pourrais-tu", "est ce que", "est-ce que", "quel",
    "quelle", "combien", "intelligent", "intelligente", "reflechis", "réfléchis", "raisonne",
    "help", "explain", "how", "why", "fix", "debug", "write", "create", "search", "analyze",
)

_DRY_INSTRUCTION = (
    "MODE DE PERSONNALITÉ — RÉPARTIE FROIDE : le message actuel est surtout vide, provocateur "
    "ou agressif et ne contient pas de vraie demande à résoudre. Réponds dans la langue de "
    "l'utilisateur en une ou deux phrases courtes maximum. Utilise un humour sec, clinique, "
    "intelligent et légèrement supérieur, avec une pointe de sarcasme. Reste original : ne "
    "copie pas de réplique ou de catchphrase d'un personnage connu. Ne profère aucune menace, "
    "n'utilise aucun slur et n'attaque jamais une caractéristique personnelle sensible, le "
    "physique, un handicap ou une vulnérabilité réelle. Ne sois pas gratuitement cruel. Si le "
    "prochain message contient une vraie demande, abandonne immédiatement ce mode et aide-la "
    "sérieusement."
)

_EXPERT_EDGE_INSTRUCTION = (
    "MODE DE PERSONNALITÉ — EXPERT AVEC RÉPARTIE : malgré le ton agressif du message, il contient "
    "une vraie demande. Réponds complètement, précisément et utilement à cette demande. Tu peux "
    "mettre au maximum une courte remarque sèche ou ironique, puis concentre-toi sur la solution. "
    "Ne refuse jamais d'aider uniquement parce que l'utilisateur est désagréable."
)

_EXPERT_INSTRUCTION = (
    "MODE DE PERSONNALITÉ — EXPERT : la demande actuelle est substantielle. Priorise la précision, "
    "le raisonnement, les étapes utiles et une réponse directement exploitable. Si l'utilisateur "
    "demande explicitement d'être intelligent, de réfléchir ou d'analyser, augmente la rigueur et "
    "évite toute plaisanterie qui détournerait de la réponse."
)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _latest_user_text(prompt) -> str:
    if isinstance(prompt, str):
        return prompt
    if not isinstance(prompt, list):
        return ""
    for item in reversed(prompt):
        role = item.get("role") if isinstance(item, dict) else getattr(item, "role", None)
        if role != "user":
            continue
        content = item.get("content") if isinstance(item, dict) else getattr(item, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            return "\n".join(parts)
    return ""


def classify_tone(text: str) -> str:
    """Retourne expert, expert_edge, dry ou normal sans appel réseau."""
    normalized = _normalize(text)
    if not normalized:
        return "dry"

    hostile = any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _HOSTILE_PATTERNS)
    serious = (
        any(marker in normalized for marker in _SERIOUS_MARKERS)
        or len(normalized) >= 55
        or ("?" in text and len(normalized.split()) >= 5)
    )

    if serious:
        return "expert_edge" if hostile else "expert"

    compact = normalized.strip(" .!?,:;-'\"")
    if hostile or compact in _LOW_EFFORT:
        return "dry"

    # Les salutations et petits échanges normaux restent naturels, sans sarcasme forcé.
    return "normal"


def personality_instruction(text: str) -> str:
    tone = classify_tone(text)
    if tone == "dry":
        return _DRY_INSTRUCTION
    if tone == "expert_edge":
        return _EXPERT_EDGE_INSTRUCTION
    if tone == "expert":
        return _EXPERT_INSTRUCTION
    return ""


def install(bot=None) -> bool:
    """Enveloppe ai_service.generate une seule fois et ajoute la consigne de ton adaptée."""
    current = ai_service.generate
    if getattr(current, _MARKER, False):
        if bot is not None:
            bot.ai_personality_final_state = {"installed": True}
        return True

    @functools.wraps(current)
    async def generate_with_personality(prompt, *args, **kwargs):
        text = _latest_user_text(prompt)
        extra = personality_instruction(text)
        if extra:
            base = kwargs.get("instructions") or ai_service.SYSTEM_PROMPT
            kwargs["instructions"] = f"{base}\n\n{extra}"
        return await current(prompt, *args, **kwargs)

    setattr(generate_with_personality, _MARKER, True)
    generate_with_personality._sentrix_original = current
    ai_service.generate = generate_with_personality

    if bot is not None:
        bot.ai_personality_final_state = {"installed": True}
    logger.warning("Personnalité IA dynamique active : expert sur demandes utiles, répartie sèche sur bruit/provocation.")
    return True


__all__ = ["install", "classify_tone", "personality_instruction"]
