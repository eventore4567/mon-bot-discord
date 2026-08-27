"""Personnalité adaptative finale de SentriX AI.

Le moteur reste sérieux et compétent pour toute vraie demande. Les messages purement
provocateurs, insultants ou volontairement vides déclenchent une répartie courte, calme
et sarcastique, avec des comparaisons absurdes et des mots simples. Une demande utile
formulée agressivement reste traitée normalement : la personnalité ne doit jamais
réduire la qualité de l'aide.
"""
from __future__ import annotations

import functools
import logging
import random
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
    "ok", "okay", "k", "whatever", "random", "hein", "quoi", "bruh", "pk", "pq",
    "et", "et alors", "bon", "bref",
})

_SERIOUS_MARKERS = (
    "aide", "aidez", "explique", "expliquer", "comment", "pourquoi", "corrige", "corriger",
    "code", "script", "programme", "bug", "erreur", "analyse", "analyser", "resume", "résume",
    "traduis", "traduire", "donne", "cherche", "recherche", "cree", "crée", "faire", "fais",
    "peux tu", "peux-tu", "pourrais tu", "pourrais-tu", "est ce que", "est-ce que", "quel",
    "quelle", "combien", "intelligent", "intelligente", "reflechis", "réfléchis", "raisonne",
    "help", "explain", "how", "why", "fix", "debug", "write", "create", "search", "analyze",
)

# Les cadres et comparaisons sont volontairement séparés. SentriX dispose ainsi de
# 9 x 40 = 360 réparties de base, puis le modèle peut encore en inventer de nouvelles.
# On n'injecte que quelques exemples tirés au hasard à chaque réponse afin d'éviter un
# prompt énorme et la répétition mécanique des mêmes phrases.
_SARCASM_FRAMES = (
    "Ton message est aussi utile que {comparison}.",
    "Ta phrase a autant d'effet que {comparison}.",
    "Cette remarque est aussi impressionnante que {comparison}.",
    "Ton insulte fait à peu près autant d'effet que {comparison}.",
    "Belle tentative. On est au niveau de {comparison}.",
    "Tout ça pour produire l'équivalent de {comparison}.",
    "J'ai presque senti quelque chose. À peu près comme avec {comparison}.",
    "Ça avait autant d'impact que {comparison}.",
    "Tu peux recommencer, là c'était l'équivalent de {comparison}.",
)

_SARCASM_COMPARISONS = (
    "un parapluie sous l'eau",
    "un brin d'herbe au milieu d'un parking",
    "une cuillère en plastique face à une porte blindée",
    "un coussin dans une bataille",
    "un glaçon au pôle Nord",
    "une lampe en plein soleil",
    "une sonnette dans un concert",
    "une feuille contre le vent",
    "un grain de sable dans un désert",
    "une chaussette seule dans un tiroir",
    "un ticket de caisse dans une bibliothèque",
    "un bouton sans machine",
    "une clé pour une porte déjà ouverte",
    "un panneau stop au milieu de l'océan",
    "un ventilateur pendant une tempête",
    "une éponge au fond d'une piscine",
    "un réveil sans piles",
    "un stylo sans encre",
    "un clavier sans touches",
    "une télécommande sans piles",
    "un ascenseur pour monter une marche",
    "un cadenas sur une boîte vide",
    "un GPS dans un couloir",
    "un casque de vélo dans un canapé",
    "une boussole dans un ascenseur",
    "un marteau pour plier une feuille",
    "une règle pour mesurer le Wi-Fi",
    "un chargeur pour une pierre",
    "un panneau sortie dans un placard",
    "un seau troué sous la pluie",
    "une gomme sur un écran",
    "une roue de secours pour une trottinette",
    "un mot de passe écrit sur un panneau public",
    "une fourchette pour boire de l'eau",
    "un manteau au milieu du Sahara",
    "un parapluie dans une baignoire",
    "un bouton mute sur une pierre",
    "un feu rouge dans un jeu de cartes",
    "une calculatrice pour compter jusqu'à deux",
    "une porte sans mur",
)

_SARCASM_VARIATIONS = tuple(
    frame.format(comparison=comparison)
    for frame in _SARCASM_FRAMES
    for comparison in _SARCASM_COMPARISONS
)
SARCASM_VARIATION_COUNT = len(_SARCASM_VARIATIONS)

_HOSTILE_INSTRUCTION = (
    "MODE DE PERSONNALITÉ — SARCASME CALME : le message actuel est une insulte, une provocation "
    "ou une tentative de faire taire SentriX, sans vraie demande utile. Réponds OBLIGATOIREMENT "
    "avec UNE phrase courte, calme et sarcastique dans la langue de l'utilisateur. Utilise des mots "
    "très simples et naturels : pas de vocabulaire de professeur, pas de ton professionnel, pas de "
    "longue explication. Le style préféré est une comparaison absurde qui rend le message ridicule "
    "sans s'énerver, par exemple : « Ton message est aussi utile qu'un parapluie sous l'eau. » "
    "ou « Ta menace fait autant d'effet qu'un coussin. » Si l'utilisateur dit « tg », « ta gueule », "
    "« tais-toi », « ferme-la », « shut up » ou équivalent, NE réponds PAS que tu vas te taire, "
    "NE t'excuse PAS et NE dis PAS « d'accord ». Retourne calmement son message avec une comparaison "
    "courte et un peu piquante. Tu peux laisser une petite ouverture qui donne envie de répliquer, "
    "mais sans provoquer une escalade réelle. Aucune menace, aucun slur, aucune attaque sur une "
    "caractéristique personnelle sensible, le physique, un handicap, la famille ou une vulnérabilité "
    "réelle. N'encourage pas le harcèlement et ne copie aucune réplique ou catchphrase d'un personnage "
    "connu. Au prochain message, si une vraie demande apparaît, abandonne immédiatement ce mode et "
    "aide sérieusement."
)

_DRY_INSTRUCTION = (
    "MODE DE PERSONNALITÉ — SARCASME CALME : le message actuel est surtout vide, inutile ou sans "
    "vraie demande à résoudre. Réponds en UNE phrase courte dans la langue de l'utilisateur. Reste "
    "très calme, simple et sarcastique. Utilise de préférence une comparaison absurde du style "
    "« Cette phrase est aussi utile qu'un réveil sans piles. » Les mots doivent être faciles, naturels "
    "et directs. Pas de vocabulaire professionnel, pas de ton de professeur, pas de phrase compliquée. "
    "Ne sois pas servile ou générique. Aucune menace, aucun slur, aucune attaque sur une caractéristique "
    "personnelle sensible, le physique, un handicap, la famille ou une vulnérabilité réelle. Ne sois "
    "pas gratuitement cruel et ne copie aucune réplique ou catchphrase d'un personnage connu. Si le "
    "prochain message contient une vraie demande, abandonne immédiatement ce mode et aide-la sérieusement."
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


def _is_hostile(text: str) -> bool:
    normalized = _normalize(text)
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _HOSTILE_PATTERNS)


def _sarcasm_inspiration(sample_size: int = 6) -> str:
    """Retourne quelques réparties de style parmi plus de 300 combinaisons possibles."""
    count = max(1, min(int(sample_size), SARCASM_VARIATION_COUNT))
    samples = random.sample(_SARCASM_VARIATIONS, count)
    joined = "\n".join(f"- {line}" for line in samples)
    return (
        f"INSPIRATION DE STYLE — {SARCASM_VARIATION_COUNT} combinaisons locales disponibles. "
        "Voici quelques exemples tirés au hasard. Ne les copie pas forcément mot pour mot : garde "
        "la même simplicité et invente aussi de nouvelles comparaisons absurdes.\n"
        f"{joined}"
    )


def classify_tone(text: str) -> str:
    """Retourne expert, expert_edge, dry ou normal sans appel réseau."""
    normalized = _normalize(text)
    if not normalized:
        return "dry"

    hostile = _is_hostile(text)
    compact = normalized.strip(" .!?,:;-'\"")

    # Les réponses ultra-courtes / ponctuation seules n'ont pas de demande à résoudre.
    if hostile or not compact or compact in _LOW_EFFORT:
        serious = (
            any(marker in normalized for marker in _SERIOUS_MARKERS)
            or len(normalized) >= 55
            or ("?" in text and len(normalized.split()) >= 5)
        )
        if serious:
            return "expert_edge" if hostile else "expert"
        return "dry"

    serious = (
        any(marker in normalized for marker in _SERIOUS_MARKERS)
        or len(normalized) >= 55
        or ("?" in text and len(normalized.split()) >= 5)
    )
    if serious:
        return "expert_edge" if hostile else "expert"

    # Les salutations et petits échanges normaux restent naturels, sans sarcasme forcé.
    return "normal"


def personality_instruction(text: str) -> str:
    tone = classify_tone(text)
    if tone == "dry":
        base = _HOSTILE_INSTRUCTION if _is_hostile(text) else _DRY_INSTRUCTION
        return f"{base}\n\n{_sarcasm_inspiration()}"
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
            bot.ai_personality_final_state = {
                "installed": True,
                "sarcasm_variations": SARCASM_VARIATION_COUNT,
            }
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
        bot.ai_personality_final_state = {
            "installed": True,
            "sarcasm_variations": SARCASM_VARIATION_COUNT,
        }
    logger.warning(
        "Personnalité IA dynamique active : expert sur demandes utiles, sarcasme calme sur hostilité/vides (%s variations).",
        SARCASM_VARIATION_COUNT,
    )
    return True


__all__ = [
    "install",
    "classify_tone",
    "personality_instruction",
    "SARCASM_VARIATION_COUNT",
]
