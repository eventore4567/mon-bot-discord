"""Serveur réglé en anglais : traduire ce qui reste en français (03/11/2026).

cogs/language_runtime traduit par dictionnaire (phrases connues). Tout texte que
le dictionnaire ne connaît pas partait en français. Cette seconde passe repère les
textes de SentriX encore en français et les traduit (services/translation : Google,
puis OpenAI en secours), en protégeant mentions, salons, horodatages, emojis, code
et liens. Chaque phrase n'est traduite qu'une fois (cache) ; si le service est lent
ou en panne, le message part tel quel et la passe se coupe quelques minutes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("bot.english-fallback")

#: Temps total accordé à la traduction d'un message (Discord attend la réponse).
BUDGET_SECONDES = 2.5
#: Après une panne du service : plus d'essai pendant ce délai.
COUPURE_SECONDES = 300.0
_CACHE_MAX = 5000

_cache: "OrderedDict[str, str]" = OrderedDict()
_coupe_jusqua = 0.0

_PROTEGE = re.compile(
    r"(<a?:\w+:\d+>|<[@#][!&]?\d+>|<t:\d+(?::[a-zA-Z])?>|</[\w -]+:\d+>|`[^`]*`|https?://\S+|\{[a-z_]+\})"
)
_MOTS = re.compile(r"[^\W\d_]+", re.UNICODE)
_ACCENTS = set("éèêëàâùûüçôîïœ")
_FR = frozenset("""
le la les des du de un une est sont vous votre vos pour avec aucun aucune dans sur pas
ce cette ces été être au aux et ou qui que ne plus déjà ici puis encore jamais
membre membres salon salons serveur commande commandes rôle rôles activé désactivé
choisissez configurez utilisez impossible introuvable cliquez envoyez retour fermer
""".split())
_EN = frozenset("the and you your is are to of for with this that not no in on it be".split())


def est_francais(texte: str) -> bool:
    """Heuristique prudente : plusieurs marqueurs français et plus que d'anglais."""
    propre = _PROTEGE.sub(" ", str(texte or ""))
    mots = [m.casefold() for m in _MOTS.findall(propre)]
    if not mots:
        return False
    fr = sum(1 for m in mots if m in _FR)
    en = sum(1 for m in mots if m in _EN)
    accents = sum(1 for m in mots if _ACCENTS & set(m))
    if en > fr + accents:
        return False
    return fr + accents >= 2 or (accents >= 1 and len(mots) <= 3)


def _masquer(texte: str) -> tuple[str, list[str]]:
    gardes: list[str] = []

    def remplacer(match: re.Match[str]) -> str:
        gardes.append(match.group(0))
        return f"⟦{len(gardes) - 1}⟧"

    return _PROTEGE.sub(remplacer, texte), gardes


def _restaurer(texte: str, gardes: list[str]) -> str | None:
    for index, valeur in enumerate(gardes):
        repere = f"⟦{index}⟧"
        if repere not in texte:
            return None  # le traducteur a abîmé un repère : on garde l'original
        texte = texte.replace(repere, valeur)
    return texte


def _memoriser(ligne: str, traduit: str) -> None:
    _cache[ligne] = traduit
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


async def _appel(texte: str) -> str | None:
    """Un appel au service ; None si refusé (et coupure après une vraie panne)."""
    global _coupe_jusqua
    from services import translation as tr

    async with _verrou():
        try:
            resultat = await tr.translate(texte, "en", source="fr")
        except tr.TranslationError as exc:
            if exc.code == "unavailable":
                _coupe_jusqua = time.monotonic() + COUPURE_SECONDES
                logger.warning("Traduction anglaise indisponible : passe coupée %ss.", int(COUPURE_SECONDES))
            return None
        except Exception:  # noqa: BLE001
            logger.debug("Texte non traduit.", exc_info=True)
            return None
    return unicodedata.normalize("NFC", resultat.text)


_semaphore: asyncio.Semaphore | None = None


def _verrou() -> asyncio.Semaphore:
    # Google refuse au-delà de 5 requêtes/s (TooManyRequests vu en production le
    # 03/11/2026) : deux appels à la fois au plus, tous messages confondus.
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(2)
    return _semaphore


async def _traduire_lot(lignes: list[str]) -> None:
    """Traduit des lignes en UN appel par paquet (au lieu d'un appel par ligne).

    Les lignes sont jointes par des retours à la ligne ; si le service rend un
    autre nombre de lignes, chaque ligne du paquet est retraduite seule.
    """
    a_faire = [l for l in dict.fromkeys(lignes) if l not in _cache]
    if not a_faire or time.monotonic() < _coupe_jusqua:
        return
    from services import translation as tr

    paquets: list[list[str]] = [[]]
    taille = 0
    for ligne in a_faire:
        if paquets[-1] and taille + len(ligne) + 1 > tr.MAX_LENGTH - 200:
            paquets.append([])
            taille = 0
        paquets[-1].append(ligne)
        taille += len(ligne) + 1
    for paquet in paquets:
        masques = [_masquer(l) for l in paquet]
        sortie = await _appel("\n".join(m for m, _ in masques))
        if sortie is None:
            return
        morceaux = sortie.split("\n")
        if len(morceaux) != len(paquet):
            morceaux = []
            for masque, _ in masques:
                seul = await _appel(masque)
                if seul is None:
                    return
                morceaux.append(seul)
        for ligne, (_, gardes), traduit in zip(paquet, masques, morceaux):
            restaure = _restaurer(traduit.strip() if ligne == ligne.strip() else traduit, gardes)
            if restaure:
                _memoriser(ligne, restaure)


def _lignes_francaises(textes) -> list[str]:
    lignes: list[str] = []
    for texte in textes:
        if texte and est_francais(texte):
            lignes.extend(l for l in str(texte).split("\n") if l.strip() and est_francais(l))
    return lignes


def _depuis_cache(texte: str) -> str:
    if not texte:
        return texte
    lignes = str(texte).split("\n")
    for ligne in lignes:
        if ligne in _cache:
            _cache.move_to_end(ligne)
    return "\n".join(_cache.get(l, l) for l in lignes)


async def traduire_texte(texte: str) -> str:
    """Traduit les lignes françaises d'un texte, laisse les autres intactes."""
    if not texte or not est_francais(texte):
        return texte
    await _traduire_lot(_lignes_francaises([texte]))
    return _depuis_cache(texte)


# --------------------------------------------------------------------------- charge utile
def _textes_vue(vue: Any) -> list[tuple[Any, str]]:
    """(objet, attribut) des textes d'une vue : TextDisplay, boutons, menus."""
    import discord

    cibles: list[tuple[Any, str]] = []
    pile = list(getattr(vue, "children", ()) or ())
    while pile:
        item = pile.pop()
        pile.extend(getattr(item, "children", ()) or ())
        accessoire = getattr(item, "accessory", None)
        if accessoire is not None:
            pile.append(accessoire)
        if isinstance(item, discord.ui.TextDisplay):
            cibles.append((item, "content"))
        elif isinstance(item, discord.ui.Button) and item.label:
            cibles.append((item, "label"))
        elif isinstance(item, discord.ui.Select):
            if item.placeholder:
                cibles.append((item, "placeholder"))
            for option in getattr(item, "options", ()) or ():
                cibles.append((option, "label"))
                if option.description:
                    cibles.append((option, "description"))
    return cibles


def _textes_embed(embed: Any) -> list[tuple[Any, str]]:
    cibles: list[tuple[Any, str]] = []
    for attr in ("title", "description"):
        if getattr(embed, attr, None):
            cibles.append((embed, attr))
    return cibles


async def traduire_charge(content: str | None, embeds: list, vue: Any) -> str | None:
    """Traduit sur place embeds et vue, renvoie le contenu traduit. Budget borné.

    Tout le message part en un seul appel. Si le budget est dépassé, le message
    part tel quel MAIS la traduction continue en fond et remplit le cache : le
    même texte sortira en anglais dès la fois suivante.
    """
    # Coupé dans le simulateur et les tests (résultats déterministes, pas de réseau).
    if os.environ.get("SENTRIX_TRADUCTION_AUTO", "1") == "0":
        return content
    cibles: list[tuple[Any, str]] = []
    for embed in embeds or ():
        cibles.extend(_textes_embed(embed))
    if vue is not None:
        cibles.extend(_textes_vue(vue))
    textes = [str(getattr(objet, attr) or "") for objet, attr in cibles]
    champs = [
        (embed, index, field)
        for embed in embeds or ()
        for index, field in enumerate(list(getattr(embed, "fields", ()) or ()))
    ]
    tous = [content or "", *textes, *(f.name for _, _, f in champs), *(f.value for _, _, f in champs)]
    lignes = _lignes_francaises(tous)
    if not lignes:
        return content
    if any(l not in _cache for l in lignes):
        tache = asyncio.ensure_future(_traduire_lot(lignes))
        _en_fond.add(tache)
        tache.add_done_callback(_en_fond.discard)
        try:
            await asyncio.wait_for(asyncio.shield(tache), BUDGET_SECONDES)
        except asyncio.TimeoutError:
            logger.info("Traduction anglaise trop lente : message envoyé tel quel, traduction gardée pour la suite.")
            return content
    for (objet, attr), avant in zip(cibles, textes):
        apres = _depuis_cache(avant)
        if apres != avant:
            try:
                setattr(objet, attr, apres)
            except Exception:  # noqa: BLE001 — attribut en lecture seule
                pass
    for embed, index, field in champs:
        nom, valeur = _depuis_cache(field.name), _depuis_cache(field.value)
        if (nom, valeur) != (field.name, field.value):
            try:
                embed.set_field_at(index, name=nom, value=valeur, inline=field.inline)
            except Exception:  # noqa: BLE001
                pass
    return _depuis_cache(content) if content else content


#: Traductions poursuivies après l'envoi (référence gardée : sinon le GC les coupe).
_en_fond: set = set()


__all__ = ["est_francais", "traduire_charge", "traduire_texte"]
