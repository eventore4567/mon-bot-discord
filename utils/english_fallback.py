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


async def _traduire_ligne(ligne: str) -> str:
    global _coupe_jusqua
    if ligne in _cache:
        _cache.move_to_end(ligne)
        return _cache[ligne]
    if time.monotonic() < _coupe_jusqua:
        return ligne
    from services import translation as tr

    masque, gardes = _masquer(ligne)
    try:
        resultat = await tr.translate(masque, "en", source="fr")
    except tr.TranslationError as exc:
        if exc.code == "unavailable":
            _coupe_jusqua = time.monotonic() + COUPURE_SECONDES
            logger.warning("Traduction anglaise indisponible : passe coupée %ss.", int(COUPURE_SECONDES))
        return ligne
    except Exception:  # noqa: BLE001
        logger.debug("Ligne non traduite.", exc_info=True)
        return ligne
    traduit = _restaurer(unicodedata.normalize("NFC", resultat.text), gardes)
    if not traduit:
        return ligne
    _cache[ligne] = traduit
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return traduit


async def traduire_texte(texte: str) -> str:
    """Traduit les lignes françaises d'un texte, laisse les autres intactes."""
    if not texte or not est_francais(texte):
        return texte
    lignes = str(texte).split("\n")
    a_traduire = sorted({l for l in lignes if l.strip() and est_francais(l)})
    if not a_traduire:
        return texte
    traductions = dict(zip(a_traduire, await asyncio.gather(*(_traduire_ligne(l) for l in a_traduire))))
    return "\n".join(traductions.get(l, l) for l in lignes)


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
    """Traduit sur place embeds et vue, renvoie le contenu traduit. Budget borné."""
    # Coupé dans le simulateur et les tests (résultats déterministes, pas de réseau).
    if os.environ.get("SENTRIX_TRADUCTION_AUTO", "1") == "0":
        return content
    cibles: list[tuple[Any, str]] = []
    for embed in embeds or ():
        cibles.extend(_textes_embed(embed))
    if vue is not None:
        cibles.extend(_textes_vue(vue))
    textes = [str(getattr(objet, attr) or "") for objet, attr in cibles]
    if not any(est_francais(t) for t in [content or "", *textes]):
        return content

    async def tout():
        nouveau = await traduire_texte(content) if content else content
        resultats = await asyncio.gather(*(traduire_texte(t) for t in textes))
        return nouveau, resultats

    try:
        nouveau, resultats = await asyncio.wait_for(tout(), BUDGET_SECONDES)
    except asyncio.TimeoutError:
        logger.info("Traduction anglaise trop lente : message envoyé tel quel.")
        return content
    for (objet, attr), avant, apres in zip(cibles, textes, resultats):
        if apres != avant:
            try:
                setattr(objet, attr, apres)
            except Exception:  # noqa: BLE001 — attribut en lecture seule
                pass
    for embed in embeds or ():
        for index, field in enumerate(list(getattr(embed, "fields", ()) or ())):
            nom, valeur = field.name, field.value
            if est_francais(nom) or est_francais(valeur):
                try:
                    nom2 = await asyncio.wait_for(traduire_texte(nom), BUDGET_SECONDES)
                    valeur2 = await asyncio.wait_for(traduire_texte(valeur), BUDGET_SECONDES)
                    embed.set_field_at(index, name=nom2, value=valeur2, inline=field.inline)
                except Exception:  # noqa: BLE001
                    pass
    return nouveau


__all__ = ["est_francais", "traduire_charge", "traduire_texte"]
