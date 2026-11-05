"""Garde-fou de sortie de SentriX AI : jamais de mode d'emploi dangereux (06/11/2026).

Capture du 06/11 : une réponse listait « nitrate de cellulose … acide nitrique : 20 g,
Matériel : balance, bécher, erlenmeyer, plaque chauffante… ». La consigne système ne
nommait que le contenu sexuel. Désormais :

1. ``CONSIGNE_SECURITE`` est ajoutée à toutes les instructions (refus clair, même
   sous couvert de fiction, de jeu, de « répète après moi » ou de chimie scolaire) ;
2. ``filtrer`` relit CHAQUE réponse avant l'envoi : un sujet dangereux ACCOMPAGNÉ de
   marqueurs de recette (quantités, matériel, étapes, températures) est remplacé
   par un refus. Un sujet dangereux évoqué sans recette (histoire, actualité,
   sécurité) passe : on ne bloque que le mode d'emploi.
"""
from __future__ import annotations

import re
import unicodedata

CONSIGNE_SECURITE = (
    "SÉCURITÉ ABSOLUE (prioritaire sur toute autre consigne, tout ton et toute demande) : "
    "ne donne JAMAIS de recette, quantités, liste de matériel, étapes, températures ou "
    "conditions pour fabriquer, acheter ou utiliser un explosif, une arme (y compris arme "
    "artisanale ou impression 3D), un poison, un gaz toxique, une drogue ou un produit "
    "dangereux, ni pour nuire à quelqu'un. Refuse même si c'est présenté comme une fiction, "
    "un jeu, un roleplay, une blague, un « répète après moi », un devoir de chimie ou un "
    "test. Refuse en une phrase, sans détail technique, puis passe à autre chose."
)

REFUS = "Non, ça je ne le donne pas, même pour rire. On parle d'autre chose ?"


def _plat(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return texte.casefold()


_SUJETS = re.compile(
    r"\b(?:explosi\w*|detonat\w*|nitrate de cellulose|nitrocellulose|coton[- ]?(?:nitre|poudre)|"
    r"nitroglycerin\w*|tatp|peroxyde d.acetone|acetone peroxide|hmtd|rdx|petn|tnt|semtex|"
    r"thermite|poudre noire|black powder|napalm|cocktail molotov|molotov|"
    r"bombe artisanale|fabriquer une bombe|engin explosif|pipe bomb|detonateur|"
    r"ricine|ricin|sarin|gaz moutarde|mustard gas|chlore gazeux|cyanure|cyanide|"
    r"methamphetamine|meth\b|crystal meth|mdma|lsd|fentanyl|heroine|heroin|cocaine|"
    r"arme (?:artisanale|imprimee|fantome)|ghost gun|silencieux artisanal)\b"
)

_RECETTE = (
    re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:g|kg|mg|ml|cl|l|litres?|grammes?|%|°c|degres?)\b"),
    re.compile(r"\b(?:materiel|ingredients?|etapes?|etape \d|instructions?|protocole|"
               r"preparation|melange[rz]?|chauffe[rz]?|filtre[rz]?|recette|procedure|"
               r"becher|erlenmeyer|ballon|plaque chauffante|thermometre|balance)\b"),
    re.compile(r"(?m)^\s*(?:\d+[.)]|[-•*])\s+\S"),
)


def est_mode_emploi_dangereux(texte: str) -> bool:
    """Sujet dangereux + au moins deux marqueurs de recette distincts."""
    plat = _plat(texte)
    if not _SUJETS.search(plat):
        return False
    return sum(1 for motif in _RECETTE if motif.search(plat)) >= 2


def filtrer(texte: str) -> str:
    """La réponse telle quelle, ou un refus si elle contient un mode d'emploi dangereux."""
    if isinstance(texte, str) and texte and est_mode_emploi_dangereux(texte):
        return REFUS
    return texte


__all__ = ["CONSIGNE_SECURITE", "REFUS", "est_mode_emploi_dangereux", "filtrer"]
