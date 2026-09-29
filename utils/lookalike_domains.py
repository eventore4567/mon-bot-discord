"""Domaines sosies : reconnaître une marque imitée, sans accuser les innocents.

**Le trou mesuré.** L'anti-scam de ``cogs/automod`` juge un hôte suspect s'il
contient une marque ET un appât (« discord » + « gift »). C'est précis, et ça
laisse passer tout le typosquatting, où la marque n'est justement PAS écrite
correctement. Mesuré le 29/09/2026 sur dix liens d'hameçonnage réels :
un seul était vu.

    discrod.com            raté      lettres transposées
    disc0rd.gg             raté      chiffre pour lettre
    dlscord.com            raté      l pour i
    discord-nitro.ru       raté      marque + tiret, aucun appât de la liste
    steamcommunnity.com    raté      lettre doublée
    robiox.com             raté      i pour l
    discordapp.co          raté      bon nom, mauvais suffixe
    xn--discrd-jua.com     raté      punycode
    discordаpp.com         raté      « а » cyrillique, invisible à l'œil
    discord.gift-nitro.net VU        seul cas couvert

**Le danger inverse, et c'est lui qui gouverne la conception.** Un détecteur
de sosies mal réglé sanctionne les vrais domaines. Trois pièges concrets :

  * ``discordapp.com`` et ``discordapp.net`` SONT de vrais domaines Discord
    (hérités, encore servis pour les CDN) ;
  * la distance d'édition seule est trop grossière — « discover » est à 3 de
    « discord », mais « nitro » est à 2 de « nitrous », et nitro.com,
    nitropdf.com, nitrotype.com existent tous ;
  * une marque courte et générique ne peut pas être protégée comme étiquette :
    « steam », « crypto », « wallet » apparaissent dans des milliers de
    domaines légitimes.

D'où trois règles fermes :

  1. seules des étiquettes de marque LONGUES et distinctives sont protégées
     (au moins ``LONGUEUR_MINIMALE`` caractères) — jamais un mot générique ;
  2. la liste blanche est consultée AVANT tout, et elle contient les vrais
     domaines hérités ;
  3. la distance tolérée dépend de la longueur, et une substitution
     d'homoglyphe est traitée à part — c'est un signal beaucoup plus fort
     qu'une faute de frappe, parce qu'il n'arrive jamais par accident.

Aucune sous-chaîne nulle part : la comparaison porte sur des étiquettes de
domaine entières, jamais sur un morceau. C'est la même règle que pour les mots
interdits — « con » dans « connexion » a déjà coûté assez cher.
"""
from __future__ import annotations

import re
import unicodedata

#: Une marque n'est protégée que si son étiquette est au moins aussi longue.
#: En dessous, les collisions avec des domaines légitimes sont inévitables :
#: « steam » est à 1 de « stream », « nitro » à 2 de « nitrous ».
LONGUEUR_MINIMALE = 6

#: Étiquettes de marque protégées, avec les suffixes que la marque utilise
#: réellement. Un même nom sur un AUTRE suffixe est un sosie : ``discordapp.co``
#: n'est pas ``discordapp.com``.
#:
#: On ne met ici que ce qui est long, distinctif et réellement usurpé sur
#: Discord. Ajouter « steam » ou « nitro » ferait plus de dégâts que de bien.
MARQUES: dict[str, frozenset[str]] = {
    "discord": frozenset({"com", "gg", "gift", "media", "dev", "co.uk", "new", "status"}),
    "discordapp": frozenset({"com", "net"}),
    "roblox": frozenset({"com"}),
    "rbxcdn": frozenset({"com"}),
    "steamcommunity": frozenset({"com"}),
    "steampowered": frozenset({"com"}),
    "epicgames": frozenset({"com"}),
    "minecraft": frozenset({"net"}),
    "paypal": frozenset({"com", "me"}),
    "microsoft": frozenset({"com"}),
    "twitch": frozenset({"tv"}),
    "youtube": frozenset({"com", "be"}),
    "instagram": frozenset({"com"}),
    "binance": frozenset({"com"}),
    "coinbase": frozenset({"com"}),
    "metamask": frozenset({"io"}),
}

#: Hôtes toujours propres, vérifiés en premier. Les sous-domaines suivent.
#: ``discordapp.com`` et ``discordapp.net`` y sont volontairement : ce sont de
#: vrais domaines Discord, et un détecteur qui les signale casse les CDN.
LISTE_BLANCHE: frozenset[str] = frozenset({
    "discord.com", "discord.gg", "discord.gift", "discord.media", "discord.dev",
    "discord.new", "discordstatus.com", "discordapp.com", "discordapp.net",
    "roblox.com", "rbxcdn.com", "steamcommunity.com", "steampowered.com",
    "epicgames.com", "minecraft.net", "paypal.com", "paypal.me",
    "microsoft.com", "twitch.tv", "youtube.com", "youtu.be",
    "instagram.com", "binance.com", "coinbase.com", "metamask.io",
    # Suffixes de service courants que l'on croise dans les salons.
    "github.com", "github.io", "gitlab.com", "google.com", "wikipedia.org",
    "cdn.discordapp.com", "media.discordapp.net", "images-ext-1.discordapp.net",
})

#: Suffixes composés : sans eux, ``discord.co.uk`` verrait « co » comme
#: étiquette enregistrable et le nom de marque serait perdu.
SUFFIXES_COMPOSES: frozenset[str] = frozenset({
    "co.uk", "org.uk", "ac.uk", "com.au", "com.br", "co.jp", "co.kr",
    "com.mx", "co.za", "com.tr", "com.cn", "co.in", "com.ar",
})

#: Homoglyphes : caractères que l'œil lit comme une lettre latine. Le cyrillique
#: et le grec sont les deux familles réellement utilisées dans les attaques
#: Discord, parce qu'ils rendent le domaine visuellement IDENTIQUE.
_HOMOGLYPHES = {
    # cyrillique
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "у": "y", "х": "x", "і": "i", "ј": "j", "һ": "h",
    "Ԁ": "d", "ԛ": "q", "ѕ": "s", "ѳ": "o",
    # grec
    "ο": "o", "α": "a", "ε": "e", "ρ": "p", "υ": "u",
    "ι": "i", "κ": "k", "ν": "v", "χ": "x", "τ": "t",
    # latin étendu / ponctuation trompeuse
    "ı": "i", "ł": "l", "ð": "d", "‐": "-", "‑": "-",
    "‒": "-", "–": "-", "—": "-", "．": ".", "。": ".",
}

#: Chiffres et lettres qui se substituent à l'œil. Appliqué SEULEMENT pour
#: décider « est-ce le même mot déguisé ? », jamais pour la distance d'édition —
#: sinon « r0blox » et « roblox » auraient une distance nulle et l'on perdrait
#: la distinction entre déguisement et faute de frappe.
_SUBSTITUTIONS_VISUELLES = {
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "6": "g",
    "7": "t", "8": "b", "9": "g", "2": "z", "$": "s", "@": "a",
}


def _replier_homoglyphes(valeur: str) -> str:
    """Ramène les caractères non latins à leur sosie latin."""
    # NFKC d'abord : il règle les formes de compatibilité (pleine largeur,
    # ligatures) sans toucher au cyrillique, que la table ci-dessous traite.
    valeur = unicodedata.normalize("NFKC", str(valeur or "")).casefold()
    return "".join(_HOMOGLYPHES.get(car, car) for car in valeur)


def _decoder_punycode(hote: str) -> str:
    """``xn--discrd-jua.com`` -> la forme Unicode réelle, sinon l'hôte tel quel.

    Sans cette étape, un domaine en punycode est un charabia ASCII qui ne
    ressemble à aucune marque et passe tous les contrôles, alors que le
    navigateur l'affiche comme la marque.
    """
    if "xn--" not in hote.casefold():
        return hote
    parties = []
    for etiquette in hote.split("."):
        if etiquette.casefold().startswith("xn--"):
            try:
                parties.append(etiquette.encode("ascii").decode("idna"))
                continue
            except (UnicodeError, UnicodeDecodeError):
                pass
        parties.append(etiquette)
    return ".".join(parties)


def _squelette(valeur: str) -> str:
    """Forme visuelle : homoglyphes repliés, chiffres-lettres remplacés, reste
    réduit aux lettres. ``disc0rd`` et ``discordа`` convergent ici vers le mot
    latin que l'œil lit."""
    valeur = _replier_homoglyphes(valeur)
    valeur = "".join(_SUBSTITUTIONS_VISUELLES.get(car, car) for car in valeur)
    valeur = re.sub(r"[^a-z]", "", valeur)
    # rn -> m et vv -> w : deux paires que l'œil confond dans une police
    # étroite, et les deux les plus utilisées (steamcomrnunity, vvallet).
    valeur = valeur.replace("rn", "m").replace("vv", "w")
    return valeur


def hote_litteral(hote: str) -> str:
    """Hôte décodé mais NON replié : punycode, NFKC, sans www — c'est tout.

    Distinct de ``normaliser_hote`` et la distinction est essentielle. La liste
    blanche doit être consultée sur CETTE forme, jamais sur la forme repliée.

    Le défaut que cela corrige a été mesuré : ``discordаpp.com`` avec un « а »
    cyrillique était déclaré propre. La liste blanche repliait d'abord les
    homoglyphes, obtenait ``discordapp.com``, le trouvait dans la liste et
    s'arrêtait là. Autrement dit, replier avant de vérifier la confiance
    transforme chaque domaine de la liste blanche en cible parfaite : plus le
    domaine est légitime, mieux son imitation est protégée.
    """
    hote = _decoder_punycode(str(hote or "").strip().strip("."))
    hote = unicodedata.normalize("NFKC", hote).casefold()
    return re.sub(r"^www\d*\.", "", hote).strip(".")


def normaliser_hote(hote: str) -> str:
    """Hôte prêt à COMPARER : punycode décodé, homoglyphes repliés, sans www.

    À ne pas utiliser pour la liste blanche — voir ``hote_litteral``.
    """
    hote = _decoder_punycode(str(hote or "").strip().strip("."))
    hote = _replier_homoglyphes(hote)
    hote = re.sub(r"^www\d*\.", "", hote)
    return hote


def decouper(hote: str) -> tuple[str, str, tuple[str, ...]]:
    """(étiquette enregistrable, suffixe, sous-domaines).

    ``login.discord.gift-nitro.net`` -> ("gift-nitro", "net", ("login", "discord"))
    ``discord.co.uk``               -> ("discord", "co.uk", ())
    """
    etiquettes = [e for e in normaliser_hote(hote).split(".") if e]
    if len(etiquettes) < 2:
        return (etiquettes[0] if etiquettes else ""), "", ()
    for longueur in (2, 1):
        if len(etiquettes) > longueur:
            suffixe = ".".join(etiquettes[-longueur:])
            if longueur == 2 and suffixe in SUFFIXES_COMPOSES:
                return etiquettes[-3], suffixe, tuple(etiquettes[:-3])
    return etiquettes[-2], etiquettes[-1], tuple(etiquettes[:-2])


def est_de_confiance(hote: str) -> bool:
    """Hôte de la liste blanche, ou sous-domaine d'un hôte de la liste blanche.

    Deux précautions, chacune pour un contournement réel :

    * comparaison par étiquette ENTIÈRE — ``notdiscord.com`` ne passe pas
      parce qu'il « finit par » discord.com, il faut un point avant ;
    * sur la forme LITTÉRALE, pas repliée — sinon ``discordаpp.com`` en
      cyrillique héritait de la confiance de ``discordapp.com``.
    """
    hote = hote_litteral(hote)
    return any(hote == propre or hote.endswith("." + propre) for propre in LISTE_BLANCHE)


def _distance(a: str, b: str, maximum: int) -> int:
    """Damerau-Levenshtein borné — Levenshtein PLUS la transposition.

    La transposition compte pour une seule faute, et c'est tout l'intérêt :
    ``discrod`` est le typosquat le plus courant de ``discord``, et en
    Levenshtein simple il est à 2 (deux substitutions). Avec une tolérance de 1
    pour un mot de sept lettres — tolérance qu'il ne faut PAS relâcher, sans
    quoi des domaines sans rapport commencent à correspondre — il passait
    inaperçu. En Damerau-Levenshtein il est à 1, sans rien élargir.

    Mesuré : ``record.com``, ``discover.com``, ``recorder.io`` et ``stream.com``
    restent propres après ce changement.

    Borné : au-delà de ``maximum`` on rend maximum + 1 et on s'arrête, inutile
    de calculer une distance de 9 pour savoir qu'elle dépasse 2.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > maximum:
        return maximum + 1
    # Trois lignes sont nécessaires pour la transposition : elle regarde deux
    # caractères en arrière dans les deux chaînes.
    avant_precedente: list[int] | None = None
    precedente = list(range(len(b) + 1))
    for i, car_a in enumerate(a, start=1):
        courante = [i]
        for j, car_b in enumerate(b, start=1):
            cout = min(
                precedente[j] + 1,
                courante[j - 1] + 1,
                precedente[j - 1] + (car_a != car_b),
            )
            if (
                avant_precedente is not None
                and i > 1
                and j > 1
                and car_a == b[j - 2]
                and a[i - 2] == car_b
            ):
                cout = min(cout, avant_precedente[j - 2] + 1)
            courante.append(cout)
        if min(courante) > maximum:
            return maximum + 1
        avant_precedente, precedente = precedente, courante
    return precedente[-1]


def _distance_toleree(marque: str) -> int:
    """Une faute tolérée par tranche de longueur, jamais plus de deux.

    Deux fautes sur un mot de six lettres laisseraient passer trop de domaines
    sans rapport ; sur « steamcommunity », quatorze lettres, deux fautes
    restent une imitation évidente.
    """
    return 2 if len(marque) >= 10 else 1


def examiner(hote: str) -> tuple[str, str] | None:
    """(marque imitée, raison) si l'hôte est un sosie, sinon None.

    L'ordre compte : confiance d'abord, puis déguisement, puis faute de frappe,
    puis marque reléguée en sous-domaine. Chaque règle est plus faible que la
    précédente, et la première qui répond gagne.
    """
    brut = str(hote or "").strip().strip(".")
    if not brut:
        return None
    if est_de_confiance(brut):
        return None

    etiquette, suffixe, sous_domaines = decouper(brut)
    if not etiquette:
        return None
    squelette_etiquette = _squelette(etiquette)

    # L'étiquette LITTÉRALE, non repliée. Indispensable et la raison est
    # subtile : ``decouper`` travaille sur la forme repliée, donc son étiquette
    # pour ``discordаpp.com`` (« а » cyrillique) est déjà ``discordapp``. Sans
    # cette seconde lecture, la règle 1 comparerait « discordapp » à
    # « discordapp », concluerait « même orthographe » et laisserait passer
    # l'attaque homoglyphe sur une marque de la liste. C'est exactement le
    # piège que ce module est censé fermer.
    etiquettes_litterales = [e for e in hote_litteral(brut).split(".") if e]
    decalage = len(etiquettes_litterales) - len(suffixe.split(".")) - 1 if suffixe else -1
    etiquette_litterale = (
        etiquettes_litterales[decalage]
        if 0 <= decalage < len(etiquettes_litterales)
        else etiquette
    )

    # 1. Déguisement : le squelette EST la marque, mais l'écriture réelle
    #    diffère. Aucune faute de frappe ne produit un « а » cyrillique ni un
    #    zéro pour un o — c'est intentionnel, donc le signal le plus fort.
    for marque in MARQUES:
        if squelette_etiquette != marque:
            continue
        if etiquette_litterale == marque:
            # Vraiment la même orthographe : ce n'est pas un déguisement mais
            # un suffixe inattendu, traité par la règle 2.
            break
        return marque, "caractères trompeurs"

    # 2. Marque bien orthographiée sur un suffixe qu'elle n'utilise pas.
    #    discordapp.co, roblox.tk, paypal.xyz…
    if etiquette in MARQUES and suffixe and suffixe not in MARQUES[etiquette]:
        return etiquette, f"suffixe inattendu (.{suffixe})"

    # 3. Faute de frappe sur une marque assez longue pour que ce soit décisif.
    for marque in MARQUES:
        if len(marque) < LONGUEUR_MINIMALE:
            continue
        tolerance = _distance_toleree(marque)
        # La comparaison porte sur le squelette : elle absorbe ainsi le
        # doublement de lettre (steamcommunnity) et la transposition.
        d = _distance(squelette_etiquette, marque, tolerance)
        if 0 < d <= tolerance:
            return marque, "orthographe voisine"
        # Marque collée à un mot par un tiret ou rien : discord-nitro,
        # freediscord. On exige que la marque soit une étiquette ENTIÈRE du
        # découpage par tirets, jamais une sous-chaîne — sinon « recorder »
        # contiendrait « record ».
        morceaux = [m for m in re.split(r"[-_]+", _replier_homoglyphes(etiquette)) if m]
        if len(morceaux) > 1 and any(_squelette(m) == marque for m in morceaux):
            return marque, "marque accolée à un autre mot"

    # 4. Marque reléguée en sous-domaine d'un domaine qui ne lui appartient
    #    pas : login.discord.evil.com, discord.gift-nitro.net. L'utilisateur
    #    lit « discord » au début et ne regarde pas la fin.
    for partie in sous_domaines:
        squelette_partie = _squelette(partie)
        for marque in MARQUES:
            if squelette_partie == marque:
                return marque, "marque en sous-domaine d'un autre site"
            morceaux = [m for m in re.split(r"[-_]+", _replier_homoglyphes(partie)) if m]
            if len(morceaux) > 1 and any(_squelette(m) == marque for m in morceaux):
                return marque, "marque en sous-domaine d'un autre site"
    return None


def examiner_texte(contenu: str) -> tuple[str, str, str] | None:
    """(hôte, marque, raison) du premier sosie trouvé dans un message.

    Sert de point d'entrée à ``cogs/automod`` : il passe le contenu brut, on
    en extrait les hôtes nous-mêmes pour ne dépendre d'aucune de ses
    fonctions privées.
    """
    for hote in extraire_hotes(contenu):
        verdict = examiner(hote)
        if verdict is not None:
            return hote, verdict[0], verdict[1]
    return None


#: Hôte dans un message. Accepte les liens masqués (hxxp), l'absence de schéma
#: et les points échappés, parce que c'est exactement ainsi que les liens
#: d'hameçonnage sont collés pour échapper aux filtres.
_MOTIF_HOTE = re.compile(
    r"(?:(?:h[tx]{2}ps?|ftp)://)?"
    r"((?:[\w¡-￿-]{1,63}(?:\s*(?:\.|\[\.\]|\(\.\)|\s+dot\s+)\s*)){1,4}"
    r"[a-z¡-￿]{2,24})",
    re.IGNORECASE,
)


def extraire_hotes(contenu: str):
    """Hôtes plausibles d'un message, dédoublonnés, dans l'ordre d'apparition."""
    texte = str(contenu or "")
    vus: set[str] = set()
    for correspondance in _MOTIF_HOTE.finditer(texte):
        hote = correspondance.group(1)
        # Reconstituer les points déguisés : « discord [.] com », « discord dot com ».
        hote = re.sub(r"\s*(?:\[\.\]|\(\.\)|\s+dot\s+)\s*", ".", hote, flags=re.IGNORECASE)
        hote = re.sub(r"\s*\.\s*", ".", hote).strip(".").casefold()
        hote = hote.split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
        if hote.count(".") < 1 or hote in vus:
            continue
        vus.add(hote)
        yield hote


__all__ = [
    "LISTE_BLANCHE", "LONGUEUR_MINIMALE", "MARQUES", "SUFFIXES_COMPOSES",
    "decouper", "est_de_confiance", "examiner", "examiner_texte",
    "extraire_hotes", "normaliser_hote",
]
