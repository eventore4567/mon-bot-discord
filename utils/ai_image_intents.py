"""Route explicite des créations d'images, indépendante des actions Discord.

Une description de capture peut contenir « salon », « rendre visible », « fermer »
ou « permissions ». Ces mots sont le CONTENU du visuel, pas des consignes de
modification du serveur. Ne jamais envoyer ce prompt au routeur d'actions.
"""
from __future__ import annotations

import re
import unicodedata


_CREATE = re.compile(
    r"\b(?:cre(?:e|er|ez|eons|ation)|recre(?:e|er|ez)|"
    r"gener(?:e|er|ez)|dessin(?:e|er|ez)|fabriqu(?:e|er|ez)|"
    r"produi(?:s|t|re|sez)|illustr(?:e|er|ez)|"
    r"fais|fait|faire|cree|recree|genere|render|generate|create|draw|make)\b"
)
_VISUAL = re.compile(
    r"\b(?:image|images|capture|captures|screenshot|screenshots|"
    r"visuel|visuels|photo|photos|photographie|illustration|"
    r"logo|logos|banniere|bannieres|affiche|affiches|avatar|"
    r"icone|icones|portrait|portraits|artwork|rendering|graphic|picture)\b"
)
_QUESTION_ONLY = re.compile(
    r"^\s*(?:pourquoi|comment|est.ce (?:que|qu)|why|how)\b"
)
_SIZE = re.compile(r"(?<!\d)(\d{3,4})\s*[x×]\s*(\d{3,4})(?!\d)")


def _normal(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def is_image_creation_request(text: str) -> bool:
    """Seulement un ordre de CRÉER un visuel, jamais « analyse cette image ».

    L'absence de verbes d'édition de serveur ici est voulue. La description
    peut les mentionner sans jamais autoriser des changements de permissions.
    """
    value = _normal(text)
    if not value or _QUESTION_ONLY.match(value):
        return False
    return bool(_CREATE.search(value) and _VISUAL.search(value))


def requested_image_size(text: str) -> tuple[int, int] | None:
    """Dimensions finales facultatives ; recadrage local, sans API non supportée."""
    match = _SIZE.search(str(text or ""))
    if not match:
        return None
    width, height = map(int, match.groups())
    if 256 <= width <= 3840 and 256 <= height <= 2160 and width * height <= 8_294_400:
        return width, height
    return None
