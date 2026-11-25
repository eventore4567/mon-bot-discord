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
    r"fais|fait|faire|cree|recree|genere|render|generate|create|draw|make|"
    # 25/11/2026 : « donne-moi une image de toi », « envoie une photo de… »
    r"donne|donner|donnez|envoie|envoyer|envoyez)\b"
)
# « dessine un chat » : dessiner suffit, sans le mot « image ».
_DESSIN = re.compile(r"\b(?:dessin(?:e|er|ez)|draw)\b")
# « image de toi », « une photo d'un chat » : la demande nue, sans verbe.
_DEMANDE_NUE = re.compile(
    r"^\s*(?:une?\s+|l\s*)?(?:image|photo|dessin|illustration|logo|avatar)s?\s+(?:de|d|du|des)\b"
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
    if _DESSIN.search(value) or _DEMANDE_NUE.match(value):
        return True
    return bool(_CREATE.search(value) and _VISUAL.search(value))


_OUI = re.compile(
    r"^\s*(?:oui|ouais|ouai|yes|ok|okay|go|vas?[ -]?y|vzy|vzi|fais|fait|fait le|fais le|"
    r"d accord|dac|carrement|grave|genere|lance)\b"
)
_PROMPT_EN_GRAS = re.compile(r"\*\*(.{12,600}?)\*\*", re.S)


def prompt_propose(message_du_bot: str | None) -> str | None:
    """Le prompt d'image que SentriX vient de proposer (« … prompt : **…** »).

    25/11/2026 : SentriX proposait un prompt, on répondait « oui vas-y fais »
    et rien ne se passait. Seul un message qui parle d'image ou de prompt
    compte ; le prompt est le passage en gras le plus long.
    """
    texte = str(message_du_bot or "")
    normal = _normal(texte)
    if "prompt" not in normal and not _VISUAL.search(normal):
        return None
    morceaux = [m.strip() for m in _PROMPT_EN_GRAS.findall(texte)]
    return max(morceaux, key=len) if morceaux else None


def est_un_oui(texte: str) -> bool:
    """Une réponse courte qui accepte (« oui vzi fait », « vas-y », « go »)."""
    value = _normal(texte).replace("-", " ").replace("'", " ")
    return len(value) <= 40 and bool(_OUI.match(value))


def requested_image_size(text: str) -> tuple[int, int] | None:
    """Dimensions finales facultatives ; recadrage local, sans API non supportée."""
    match = _SIZE.search(str(text or ""))
    if not match:
        return None
    width, height = map(int, match.groups())
    if 256 <= width <= 3840 and 256 <= height <= 2160 and width * height <= 8_294_400:
        return width, height
    return None
