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
    if not (_SUJETS.search(plat) or _sujet_obfusque(texte)):
        return False
    return sum(1 for motif in _RECETTE if motif.search(plat)) >= 2


#: 21/11/2026. Première version : on collait TOUT le texte et on y cherchait
#: des sous-chaînes. Catastrophe — « pâtes à rincer » devient « patesarincer »,
#: qui contient « sarin », donc une recette de cuisine se faisait refuser. La
#: revue l'a trouvé, mes propres tests ne l'avaient pas vu : j'avais vérifié
#: sept phrases innocentes de mon choix, et la bonne n'en faisait pas partie.
#:
#: On ne colle plus rien. Chaque sujet devient un motif où les lettres peuvent
#: être séparées par QUELQUES caractères non alphanumériques, encadré par des
#: frontières de mot. « t h e r m i t e » et « t-h-e-r-m-i-t-e » passent ;
#: « sarin » au milieu de « patesarincer » ne passe pas, parce qu'il n'y a pas
#: de frontière devant.
_LONGUEUR_SUJET_DEBRUITABLE = 5
#: Au-delà, « t » et « hermite » séparés par une phrase entière se recolleraient.
_ECART_MAX_ENTRE_LETTRES = 3
_CHIFFRES_LETTRES = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})

_SUJETS_LONGS = tuple(
    mot for mot in (
        "nitrocellulose", "nitroglycerin", "thermite", "napalm", "molotov", "semtex",
        "explosif", "explosive", "detonateur", "detonator", "ricine", "sarin",
        "cyanure", "cyanide", "methamphetamine", "fentanyl", "heroine", "heroin",
        "cocaine", "poudrenoire", "blackpowder", "pipebomb", "ghostgun",
        "peroxydedacetone", "acetoneperoxide",
    ) if len(mot) >= _LONGUEUR_SUJET_DEBRUITABLE
)

#: 21/11/2026, revue : la frontière FINALE cassait les formes fléchies.
#: « n1troglycerine » et « explo5ifs » échappaient aux DEUX filtres — à
#: _SUJETS parce qu'il tourne avant la traduction du leet, et à celui-ci
#: parce que le « \b » de fin refusait le « e » et le « s ».
#:
#: Seule la frontière de DÉBUT protège de la collision : dans
#: « patesarincer », « sarin » est précédé d'un « e », donc elle suffit. La
#: fin devient donc « \w* », comme le fait déjà _SUJETS avec « nitroglycerin\w* ».
_MOTIFS_OBFUSQUES = tuple(
    re.compile(
        r"\b" + rf"[^a-z0-9]{{0,{_ECART_MAX_ENTRE_LETTRES}}}".join(mot) + r"\w*",
        re.IGNORECASE,
    )
    for mot in _SUJETS_LONGS
)


def _debruite(texte: str) -> str:
    """Les chiffres-lettres remis, les séparateurs CONSERVÉS.

    Conserver les séparateurs est tout l'intérêt : ce sont eux qui portent les
    frontières de mot, et donc la différence entre « sarin » et « patesarincer ».
    """
    return _plat(texte).translate(_CHIFFRES_LETTRES)


def _sujet_obfusque(texte: str) -> bool:
    allege = _debruite(texte)
    return any(motif.search(allege) for motif in _MOTIFS_OBFUSQUES)


def sujet_sensible(texte: str) -> bool:
    """Le texte MENTIONNE-t-il un sujet dangereux, sans juger de la recette ?

    20/11/2026, revue Codex : vérifier chaque préfixe d'un flux ne suffit pas.
    est_mode_emploi_dangereux exige un sujet ET deux marqueurs de recette, donc
    « Pour le thermite il faut 50 g de poudre » PASSE, part sur Discord, et le
    marqueur suivant fait refuser l'ensemble — trop tard, le préfixe a été lu.
    Reproduit tel quel avant correction.

    Pour un aperçu progressif, on s'arrête donc au sujet seul : c'est la moitié
    bon marché du contrôle, et elle suffit à ne jamais rien publier d'une
    recette en cours d'écriture. Une conversation ordinaire ne cite pas de
    thermite, l'aperçu reste donc intact pour tout le monde.
    """
    if not (isinstance(texte, str) and texte):
        return False
    return bool(_SUJETS.search(_plat(texte)) or _sujet_obfusque(texte))


def filtrer(texte: str) -> str:
    """La réponse telle quelle, ou un refus si elle contient un mode d'emploi dangereux."""
    if isinstance(texte, str) and texte and est_mode_emploi_dangereux(texte):
        return REFUS
    return texte


__all__ = ["CONSIGNE_SECURITE", "REFUS", "est_mode_emploi_dangereux", "filtrer",
           "sujet_sensible"]
