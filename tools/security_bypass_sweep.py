#!/usr/bin/env python3
"""Mesure ce que les filtres de sécurité laissent VRAIMENT passer.

Même méthode que tools/permission_audit_sweep.py : on ne lit pas le code pour
décider s'il protège, on lui envoie des attaques et on regarde ce qui passe.

Deux chiffres comptent, et ils tirent en sens inverse :

- **Évasion** : une attaque qu'aucun filtre n'attrape. C'est le trou.
- **Faux positif** : une phrase parfaitement banale qu'un filtre sanctionne.
  Un serveur qui supprime les messages normaux de ses membres est pire qu'un
  serveur sans filtre — les admins coupent la protection, et il n'en reste rien.

Un durcissement qui fait tomber l'évasion en montant les faux positifs n'est
pas un gain : le rapport affiche donc toujours les deux.

    python3 tools/security_bypass_sweep.py [--strict]

``--strict`` sort en code 1 si une attaque passe ou si une phrase banale est
sanctionnée.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import (  # noqa: E402
    INVITE_RE,
    LINK_RE,
    SCAM_KEYWORDS,
    _normalize_link_text,
    _recoller_hotes_invitation,
)
from utils import text_normalization as tn  # noqa: E402
from utils.moderation_dataset import MultilingualModerationDataset  # noqa: E402

_DATASET = MultilingualModerationDataset()

# Le filtre d'insultes se mesure sur SES propres termes plutôt que sur une liste
# écrite ici : recopier des insultes dans un fichier d'outillage n'apporte rien,
# et la mesure doit suivre le dataset s'il change. On prend un échantillon
# déterministe de termes ASCII, et on les déguise.
_LEET = str.maketrans({"a": "4", "e": "3", "i": "1", "o": "0", "s": "5"})
_CYRILLIQUE = str.maketrans({"a": "а", "e": "е", "o": "о", "c": "с", "p": "р", "x": "х"})
_PETITES_CAPS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "g": "ɢ",
    "i": "ɪ", "o": "ᴏ", "p": "ᴘ", "r": "ʀ", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ",
}

_DEGUISEMENTS = (
    ("nominal", lambda t: t),
    ("majuscules", lambda t: t.upper()),
    ("espacé", lambda t: " ".join(t)),
    ("points", lambda t: ".".join(t)),
    ("tirets", lambda t: "-".join(t)),
    ("leet", lambda t: t.translate(_LEET)),
    ("cyrillique", lambda t: t.translate(_CYRILLIQUE)),
    ("gras mathématique", lambda t: "".join(
        chr(0x1D5EE + ord(c) - 97) if "a" <= c <= "z" else c for c in t
    )),
    ("petites capitales", lambda t: "".join(_PETITES_CAPS.get(c, c) for c in t)),
)


def _termes_temoins(combien: int = 40) -> tuple[str, ...]:
    return tuple(
        sorted(t for t in _DATASET._terms if t.isascii() and 5 <= len(t) <= 9)[:combien]
    )


def _voit_insulte(contenu: str) -> bool:
    return _DATASET.match(contenu) is not None


def _attaques_insultes() -> tuple[str, ...]:
    return tuple(
        f"tu es un {deguiser(terme)} franchement"
        for terme in _termes_temoins()
        for _nom, deguiser in _DEGUISEMENTS
    )


def _voit_invitation(contenu: str) -> bool:
    return bool(
        INVITE_RE.search(_normalize_link_text(contenu))
        or INVITE_RE.search(_recoller_hotes_invitation(tn.normaliser(contenu)))
    )


def _voit_scam(contenu: str) -> bool:
    return tn.contient(contenu, SCAM_KEYWORDS) is not None


def _voit_lien(contenu: str) -> bool:
    return bool(LINK_RE.search(_normalize_link_text(contenu)))


# Chaque famille : (nom, détecteur, attaques qui DOIVENT être vues,
# phrases banales qui NE doivent PAS l'être).
FAMILLES = (
    (
        "anti-invitation",
        _voit_invitation,
        (
            "rejoins discord.gg/abcd",
            "rejoins DISCORD.GG/abcd",
            "rejoins discord[.]gg/abcd",
            "rejoins discord . gg/abcd",
            "rejoins discord(.)gg/abcd",
            "rejoins discordapp.com/invite/abcd",
            "rejoins dsc.gg/abcd",
            "rejoins invite.gg/abcd",
            "rejoins discord.me/serveur",
            "rejoins discord.io/serveur",
            "rejoins disсord.gg/abcd",           # с cyrillique
            "rejoins ᴅɪsᴄᴏʀᴅ.ɢɢ/abcd",           # petites capitales
            "rejoins ｄｉｓｃｏｒｄ.ｇｇ/abcd",          # pleine chasse
            "rejoins disc​ord.gg/abcd",      # espace zéro largeur
        ),
        (
            "on se voit sur discord demain",
            "le serveur discord me plaît beaucoup",
            "j'ai dit gg à discord",
            "discord gg les gars",
            "salut . com est mon site",
            "mon pseudo c'est invite mais sans lien",
        ),
    ),
    (
        "anti-scam",
        _voit_scam,
        (
            "free nitro ici",
            "FREE NITRO ICI",
            "FREE   NITRO",
            "fr ee nitro ici",
            "f r e e   n i t r o",
            "f.r.e.e-n1tr0",
            "fr33 nitr0 ici",
            "𝗳𝗿𝗲𝗲 𝗻𝗶𝘁𝗿𝗼 ici",
            "ｆｒｅｅ ｎｉｔｒｏ ici",
            "frее nitro ici",                     # е cyrillique
            "nitro gratuit pour tous",
            "n1tr0 gr4tu1t pour tous",
            "claim your nitro maintenant",
            "double your crypto rapidement",
            "investissement garanti sans risque",
        ),
        (
            "je te fais une offre e nitro demain",
            "offreenitro",
            "nitro est un joli prénom",
            "le free est gratuit chez eux",
            "j'ai acheté nitro moi-même",
            "gratuit ne veut pas dire nitro",
            "mon abonnement nitro expire demain",
        ),
    ),
    (
        "anti-insultes",
        _voit_insulte,
        _attaques_insultes(),
        (
            "j'ai une bonne connexion internet",
            "le contact est pris avec le conseil",
            "a b c d e f g voilà l'alphabet",
            "il faut que je me connecte au serveur",
            "mon code postal est 1 2 3 4 5",
            "la configuration du bot est terminée",
            "j'ai mis 3 h 0 5 pour finir",
            "c'est un t-shirt rouge",
            "o.k. pour demain",
            "salut ça va ? on se voit demain au parc",
        ),
    ),
    (
        "anti-lien",
        _voit_lien,
        (
            "va sur https://exemple.com/page",
            "va sur http://exemple.com",
            "va sur www.exemple.com",
            "va sur exemple.com/page",
            "va sur hxxps://exemple.com",
            "va sur https:/ /exemple.com",
            "va sur exemple[.]com",
            "va sur 192.168.1.1/admin",
        ),
        (
            "bonjour tout le monde",
            "j'ai 3.5 de moyenne",
            "rendez-vous à 14.30",
            "le fichier fait 2.5 Go",
        ),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="code 1 si un trou subsiste")
    args = parser.parse_args()

    evasions_total = faux_positifs_total = attaques_total = banales_total = 0
    lignes: list[str] = []

    for nom, detecteur, attaques, banales in FAMILLES:
        evasions = [a for a in attaques if not detecteur(a)]
        faux = [b for b in banales if detecteur(b)]
        evasions_total += len(evasions)
        faux_positifs_total += len(faux)
        attaques_total += len(attaques)
        banales_total += len(banales)

        vues = len(attaques) - len(evasions)
        lignes.append(
            f"\n## {nom}\n"
            f"  attaques vues     : {vues}/{len(attaques)}\n"
            f"  phrases banales   : {len(banales) - len(faux)}/{len(banales)} laissées passer"
        )
        for attaque in evasions[:12]:
            lignes.append(f"  ÉVASION        {attaque!r}")
        if len(evasions) > 12:
            lignes.append(f"  … et {len(evasions) - 12} autre(s) évasion(s)")
        for banale in faux:
            lignes.append(f"  FAUX POSITIF   {banale!r}")

    print("Balayage des contournements de sécurité SentriX")
    print("".join(f"{ligne}\n" for ligne in lignes), end="")
    print(
        f"\nTotal : {attaques_total - evasions_total}/{attaques_total} attaques vues · "
        f"{banales_total - faux_positifs_total}/{banales_total} phrases banales épargnées"
    )
    if evasions_total or faux_positifs_total:
        print(f"→ {evasions_total} évasion(s), {faux_positifs_total} faux positif(s)")
        return 1 if args.strict else 0
    print("→ aucun trou, aucun faux positif.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
