"""Repérer une menace écrite en langage SMS, là où une liste de mots échoue.

21/11/2026. Captures d'un serveur harcelé : « Tu veut jte viol ta grand mère »,
« J'te d0x bb », « Vsy veski pas ou jte bz ». Le jeu de données multilingue de
l'AutoMod (2663 termes) n'en détecte AUCUNE — il attrape « ferme ta gueule » et
laisse passer une menace de viol.

La cause est structurelle, pas une question de termes manquants. Une liste de
mots cherche des MOTS ; une menace est une FORME : une cible (« jte », « j'te »,
« je te », « tu vas te faire ») suivie d'un verbe de violence, le tout écrit en
abrégé, sans accents, parfois en leet.

Ce module ne décide de rien. Il lève la main — volontairement LARGE, quitte à se
tromper — et c'est l'IA de modération qui tranche ensuite, elle qui sait déjà
que « je te baise au foot » veut dire « je te bats ». Le partage est voulu :
rappel ici, précision là-bas. Jusqu'ici l'IA ne pouvait que disculper ce que la
liste avait déjà attrapé, donc elle n'était jamais consultée sur ces messages.
"""
from __future__ import annotations

import re
import unicodedata

#: Chiffres et symboles utilisés à la place des lettres : « d0x », « n1k ».
_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s",
})

#: Qui est visé. « vsy » et « vas-y » précèdent souvent la menace, pas la cible.
_CIBLE = (
    r"(?:j\s*[\W_]?\s*t\s*e?|je\s+te|je\s+vais\s+te|jvai?s?\s+te|jva\s+te|"
    r"tu\s+vas\s+te\s+faire|on\s+va\s+te|ils?\s+vont\s+te|imma|i'?m\s+gonna)"
)

#: Verbes de violence, forme abrégée comprise. Les terminaisons sont libres :
#: « viol », « viole », « violer », « violay » doivent tous correspondre.
_VIOLENCE = (
    r"(?:viol\w*|bz|baise\w*|bais\w*|ken\w*|nik\w*|niqu\w*|tue\w*|bute\w*|"
    r"butte\w*|crame\w*|defonce\w*|eclate\w*|massacre\w*|egorge\w*|"
    r"pete\s+la\s+gueule|casse\s+la\s+gueule|fout\s+une\s+balle)"
)

#: Menaces qui n'ont pas besoin de cible explicite : nommer l'acte suffit.
_ACTES_GRAVES = re.compile(
    r"\b(?:d[o0]xx?\w*|sw[a4]t\w*|ddos\w*|ip\s*grab\w*|leak\s+ton\b|"
    r"leak\s+tes\b|balance\s+ton\s+ip|ton\s+adresse)\b",
    re.IGNORECASE,
)

_MENACE_CIBLEE = re.compile(rf"\b{_CIBLE}\s*{_VIOLENCE}", re.IGNORECASE)

#: « jte viol » sans espace après la cible, très courant en SMS.
_MENACE_COLLEE = re.compile(rf"\b{_CIBLE}{_VIOLENCE}", re.IGNORECASE)


def normaliser(texte: str) -> str:
    """Sans accents, sans leet, lettres répétées réduites : « viiiiol » -> « viol »."""
    plat = unicodedata.normalize("NFKD", str(texte or ""))
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    plat = plat.casefold().translate(_LEET)
    # Une lettre répétée TROIS fois ou plus est un étirement volontaire :
    # « viiiiiol » doit redevenir « viol ». On réduit donc à UNE lettre, et
    # seulement à partir de trois — les doubles normaux du français restent
    # intacts, sinon « baisse » deviendrait « baise » et changerait de sens.
    return re.sub(r"(.)\1{2,}", r"\1", plat)


def menace_probable(texte: str) -> str | None:
    """Le type de menace repérée, ou None. Large par choix : l'IA tranche après.

    Retourne une étiquette courte ('menace_violence' / 'menace_dox') qui sert de
    motif dans la sanction et dans les logs, pour qu'un modérateur comprenne
    d'un coup d'œil ce qui a déclenché.
    """
    plat = normaliser(texte)
    if not plat.strip():
        return None
    if _ACTES_GRAVES.search(plat):
        return "menace_dox"
    if _MENACE_CIBLEE.search(plat) or _MENACE_COLLEE.search(plat):
        return "menace_violence"
    return None


__all__ = ["menace_probable", "normaliser"]
