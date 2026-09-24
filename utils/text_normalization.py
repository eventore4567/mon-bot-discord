"""Normalisation des textes avant TOUT contrôle de sécurité.

Pourquoi ce module existe — mesuré, pas supposé. Avant lui, sur huit variantes
d'une même arnaque, sept passaient au travers de l'anti-scam : il suffisait de
majuscules et d'un espace en trop (« FREE   NITRO »), d'un chiffre à la place
d'une lettre (« fr33 nitr0 »), de gras mathématique (« 𝗳𝗿𝗲𝗲 𝗻𝗶𝘁𝗿𝗼 ») ou d'un
« е » cyrillique invisible à l'œil nu. Côté invitations, six variantes sur huit
passaient.

Deux outils, et une règle de prudence qui compte autant que la détection :

- ``normaliser(texte)`` ramène un texte à une forme canonique ASCII minuscule :
  décomposition NFKD (gras mathématique, pleine chasse, lettres cerclées),
  retrait des diacritiques, table de confusables cyrilliques/grecs, petites
  capitales, puis espaces normalisés.

- ``motif_tolerant(expression)`` compile une expression en regex qui tolère
  l'insertion de séparateurs ENTRE les lettres (« f-r-e-e n i t r o ») et les
  substitutions leet courantes, sans jamais accepter une correspondance au
  milieu d'un autre mot.

C'est ce dernier point qui évite le piège de la solution naïve : supprimer tous
les espaces puis chercher « freenitro » ferait correspondre « offre e nitro »,
et un filtre qui sanctionne une phrase française banale est pire que pas de
filtre du tout. Les frontières de mot sont donc conservées des deux côtés.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Confusables réellement vus dans les arnaques Discord : une lettre latine
# remplacée par son sosie cyrillique ou grec. Invisible à la lecture, fatal
# pour une comparaison de chaînes.
_CONFUSABLES = {
    # Cyrillique
    "а": "a", "в": "b", "с": "c", "ԁ": "d", "е": "e", "ѕ": "s", "һ": "h",
    "і": "i", "ј": "j", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "т": "t", "у": "y", "х": "x", "г": "r", "ц": "u", "ғ": "f", "ԛ": "q",
    "ѡ": "w", "ѵ": "v", "ղ": "n", "ӏ": "l",
    # Grec
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "γ": "y", "ϲ": "c", "ѕ": "s",
    # Divers
    "ʟ": "l", "ı": "i", "ȷ": "j", "ɡ": "g", "ɢ": "g", "ɑ": "a", "ɔ": "o",
}


def _table_petites_capitales() -> dict[str, str]:
    """Les petites capitales (ᴅɪsᴄᴏʀᴅ) ne sont pas décomposées par NFKD.

    Construite depuis les noms Unicode plutôt que recopiée à la main : la table
    reste juste si Unicode en ajoute, et personne n'a à vérifier 26 codes.
    """
    table: dict[str, str] = {}
    # Les 45 petites capitales latines d'Unicode sont réparties sur SIX blocs,
    # pas deux : ne balayer que 0x0250 et 0x1D00 laissait dehors la petite
    # capitale Q (U+A7AF) et quelques autres, donc « ᴀʀɴᴀQᴜᴇ » passait.
    for debut, fin in (
        (0x0200, 0x0300),
        (0x1D00, 0x1D80),
        (0x2C00, 0x2C80),
        (0xA700, 0xA7D0),
        (0xAB00, 0xAB80),
    ):
        for point in range(debut, fin):
            caractere = chr(point)
            try:
                nom = unicodedata.name(caractere)
            except ValueError:
                continue
            if not nom.startswith("LATIN LETTER SMALL CAPITAL "):
                continue
            lettre = nom.rsplit(" ", 1)[-1]
            # « SMALL CAPITAL AE », « SMALL CAPITAL L WITH STROKE »… : seules les
            # lettres simples se ramènent à une lettre ASCII sans inventer.
            if len(lettre) == 1 and lettre.isalpha() and lettre.isascii():
                table[caractere] = lettre.lower()
    return table


_PETITES_CAPITALES = _table_petites_capitales()
_REMPLACEMENTS = {**_CONFUSABLES, **_PETITES_CAPITALES}
_INVISIBLES = re.compile(r"[­​-‏⁠⁦-⁩﻿]")

# Substitutions leet : une classe de caractères par lettre. Volontairement
# restreinte aux substitutions vraiment utilisées — « 5 » pour « s » oui,
# « 6 » pour « g » non, parce que chaque ajout élargit aussi les faux positifs.
_LEET = {
    "a": "a4@", "b": "b8", "e": "e3", "g": "g9", "i": "i1!|", "l": "l1|",
    "o": "o0", "s": "s5$", "t": "t7", "z": "z2", "c": "c(",
}


def normaliser(texte: str) -> str:
    """Forme canonique ASCII minuscule d'un texte, pour la comparaison."""
    valeur = str(texte or "")
    valeur = _INVISIBLES.sub("", valeur)
    valeur = "".join(_REMPLACEMENTS.get(c, c) for c in valeur.casefold())
    valeur = unicodedata.normalize("NFKD", valeur)
    valeur = "".join(c for c in valeur if not unicodedata.combining(c))
    # Une deuxième passe : NFKD peut révéler un confusable jusque-là composé.
    valeur = "".join(_REMPLACEMENTS.get(c, c) for c in valeur)
    # Et un second casefold : NFKD décompose « 𝗙 » (gras mathématique capitale)
    # en « F » majuscule, que le premier casefold n'avait pas pu voir. Sans cette
    # ligne, mettre son insulte en gras suffisait à passer.
    return re.sub(r"\s+", " ", valeur.casefold()).strip()


def _corps_tolerant(expression: str) -> str:
    """Le cœur du motif : lettres, leet, séparateurs tolérés entre elles."""
    morceaux: list[str] = []
    for caractere in normaliser(expression):
        if caractere == " ":
            # Un espace de l'expression tolère n'importe quel séparateur, ou rien.
            morceaux.append(r"[\W_]*")
            continue
        if caractere.isalnum():
            classe = _LEET.get(caractere)
            morceaux.append(f"[{re.escape(classe)}]" if classe else re.escape(caractere))
            # Entre deux lettres, on tolère des séparateurs insérés.
            morceaux.append(r"[\W_]*")
        else:
            morceaux.append(re.escape(caractere))
    corps = "".join(morceaux).rstrip()
    if corps.endswith(r"[\W_]*"):
        corps = corps[: -len(r"[\W_]*")]
    return corps


@lru_cache(maxsize=2048)
def motif_tolerant(expression: str) -> re.Pattern[str]:
    """Compile une expression en motif tolérant aux séparateurs et au leet.

    « free nitro » attrape « f.r.e.e n1tr0 » et « F R E E   N I T R O », mais
    PAS « offre e nitro » : les deux extrémités restent des frontières de mot.
    """
    return re.compile(rf"(?<![a-z0-9]){_corps_tolerant(expression)}(?![a-z0-9])", re.IGNORECASE)


@lru_cache(maxsize=2048)
def motif_prefixe(expression: str) -> re.Pattern[str]:
    """Même tolérance, mais la fin du mot est libre : « merd* » → « merdier ».

    Construit directement, et non en retouchant la chaîne de motif_tolerant :
    remplacer un morceau de regex par recherche de texte casserait en silence
    le jour où l'ancre change — un filtre qui n'attrape plus rien, sans erreur.
    """
    return re.compile(rf"(?<![a-z0-9]){_corps_tolerant(expression)}[a-z0-9]*", re.IGNORECASE)


def contient(texte: str, expressions) -> str | None:
    """La première expression trouvée dans le texte, ou None.

    Retourne l'expression et non un booléen : un journal de modération qui dit
    « message supprimé » sans dire lequel des filtres a réagi est inexploitable.
    """
    normalise = normaliser(texte)
    if not normalise:
        return None
    for expression in expressions:
        if motif_tolerant(expression).search(normalise):
            return expression
    return None


__all__ = ["normaliser", "motif_tolerant", "motif_prefixe", "contient"]
