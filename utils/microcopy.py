"""Microcopy globale SentriX : plus courte, claire et cohérente.

Ce module ne change jamais la logique métier. Il retouche uniquement des formulations
système connues et les libellés d'interface. Les textes libres (contenu utilisateur,
réponses IA, code, URLs, IDs) restent intacts sauf normalisation légère des espaces.
"""
from __future__ import annotations

import re
from typing import Any


_EXACT = {
    "tu n'as pas les permissions nécessaires pour cette action.": "Permission insuffisante pour cette action.",
    "vous n'avez pas les permissions nécessaires pour cette action.": "Permission insuffisante pour cette action.",
    "tu n'as pas la permission d'utiliser cette commande.": "Permission insuffisante pour cette commande.",
    "vous n'avez pas la permission d'utiliser cette commande.": "Permission insuffisante pour cette commande.",
    "cette commande est réservée aux administrateurs.": "Commande réservée aux administrateurs.",
    "cette action doit être utilisée dans un serveur discord.": "Disponible uniquement sur un serveur.",
    "cette commande doit être utilisée dans un serveur discord.": "Disponible uniquement sur un serveur.",
    "cette commande doit être utilisée dans un serveur.": "Disponible uniquement sur un serveur.",
    "aucune action n'a été exécutée.": "Aucune action exécutée.",
    "cette action a déjà été traitée.": "Action déjà traitée.",
    "la confirmation a expiré. aucune action n'a été exécutée.": "Confirmation expirée. Aucune action exécutée.",
    "vérifie les informations avant de confirmer.": "Vérifiez puis confirmez.",
    "vérifiez les informations avant de confirmer.": "Vérifiez puis confirmez.",
    "réessaie dans quelques instants.": "Réessayez dans un instant.",
    "réessayez dans quelques instants.": "Réessayez dans un instant.",
    "réessaie ta question.": "Réessayez.",
    "réessayez votre question.": "Réessayez.",
    "aucune raison fournie": "Aucun motif",
    "aucun motif fourni": "Aucun motif",
    "aucune bio définie.": "Aucune bio.",
    "action confirmée — exécution": "Action confirmée",
    "confirmation obligatoire": "Confirmation",
    "vérification nécessaire": "À vérifier",
    "action interrompue": "Action impossible",
}

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"mentionn(?:e|ez) le membre concerné\s*\*\*ou répond(?:s|ez) directement à son message\*\*,?"
            r"\s*puis reformul(?:e|ez) (?:ta|votre) demande\.?",
            re.IGNORECASE,
        ),
        "Mentionnez un membre ou répondez à son message.",
    ),
    (
        re.compile(r"je n'ai pas pu (?:préparer|terminer) cette action\.[^\n]*", re.IGNORECASE),
        "Action impossible pour le moment. Réessayez.",
    ),
    (
        re.compile(r"l'action n'a pas pu être terminée\.[^\n]*", re.IGNORECASE),
        "Action impossible pour le moment. Réessayez.",
    ),
    (
        re.compile(r"cette action existe dans sentrix mais n'est pas disponible sur cette instance\.?", re.IGNORECASE),
        "Action indisponible pour le moment.",
    ),
    (
        re.compile(r"seule la personne qui a demandé l'action peut confirmer\.?", re.IGNORECASE),
        "Seul l'auteur de la demande peut confirmer.",
    ),
    (
        re.compile(r"seul l'auteur de la demande peut utiliser ces boutons\.?", re.IGNORECASE),
        "Ces boutons sont réservés à l'auteur de la demande.",
    ),
)

_BUTTONS = {
    "confirmer l'action": "Confirmer",
    "confirmer": "Confirmer",
    "annuler": "Annuler",
    "nouvelle conversation": "Nouveau chat",
    "retour à l'accueil": "Accueil",
    "retour accueil": "Accueil",
    "rafraîchir": "Actualiser",
    "recharger": "Actualiser",
    "enregistrer les modifications": "Enregistrer",
    "sauvegarder les modifications": "Enregistrer",
    "fermer le ticket": "Fermer",
    "supprimer le ticket": "Supprimer",
    "précédent": "Précédent",
    "suivant": "Suivant",
}

_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_TRAILING_SPACE = re.compile(r"[ \t]+(?=\n|$)")


def _polish_plain(segment: str) -> str:
    if not segment:
        return segment

    value = _TRAILING_SPACE.sub("", segment)
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        replacement = _EXACT.get(stripped.casefold())
        if replacement is not None:
            leading = line[: len(line) - len(line.lstrip())]
            lines.append(leading + replacement)
            continue

        polished = line
        for pattern, target in _PATTERNS:
            polished = pattern.sub(target, polished)
        polished = _MULTI_SPACE.sub(" ", polished).rstrip()
        lines.append(polished)
    return "\n".join(lines)


def polish_text(value: Any) -> str:
    """Retouche seulement la microcopy système, sans altérer les blocs de code."""
    text = str(value or "")
    if not text:
        return ""

    # Les blocs ```...``` sont copiés tels quels. Cela évite toute modification de code,
    # JSON, logs techniques ou exemples fournis par un utilisateur.
    parts = re.split(r"(```[\s\S]*?```)", text)
    for index in range(0, len(parts), 2):
        parts[index] = _polish_plain(parts[index])
    return "".join(parts).strip()


def polish_button_label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return text
    return _BUTTONS.get(text.casefold(), text)
