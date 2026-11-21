"""Ce que SentriX sait de son serveur, et qui a le droit de le lui demander.

21/11/2026. La mémoire des sanctions a montré la voie : l'information EXISTE
en base, l'IA ne la lisait simplement pas. Le même constat vaut pour les
tickets, les invitations, les niveaux et l'économie.

Plutôt que de recoudre chaque module dans le pipeline IA — ce qui a produit
les 31 modules qui se remplacent les uns les autres et tous les bugs de cette
semaine — chaque domaine DÉCLARE ici ce qu'il sait. L'IA interroge le
registre ; elle n'a pas à connaître les modules, et un module n'a rien à
remplacer.

LA RÈGLE D'ACCÈS, et elle n'a pas d'exception : une source est lisible par
l'IA exactement comme sa commande équivalente. Même donnée, même permission.
On interroge donc access_matrix, l'autorité qui décide déjà pour les
commandes, au lieu d'inventer une seconde politique qui finirait par diverger
— c'est précisément l'erreur qu'on a corrigée sur peut_consulter le 20/11.

Conséquence concrète : « combien de tickets ouverts ? » ne répond qu'au staff,
« qui a le plus d'invitations ? » répond à tout le monde, parce que
`+invites` répond déjà à tout le monde.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, NamedTuple

logger = logging.getLogger("bot.connaissance")

#: Au-delà, on gonfle un prompt déjà à ~2000 tokens pour un gain nul.
LONGUEUR_MAX = 2500
#: Une source lente ne doit jamais retarder la réponse.
DELAI_MAX_S = 2.5


class Source(NamedTuple):
    """Un domaine qui sait répondre à certaines questions sur le serveur."""

    nom: str
    #: La question parle-t-elle de ce domaine ? Appelé à chaque message : rapide.
    concerne: Callable[[str], bool]
    #: async (bot, guild, auteur, texte) -> bloc de texte, ou "" s'il n'y a rien.
    lire: Callable[..., Awaitable[str]]
    #: La commande dont cette source partage les données. None = tout le monde.
    commande_equivalente: str | None = None


_SOURCES: list[Source] = []


def enregistrer(source: Source) -> None:
    """Un module déclare ce qu'il sait. Idempotent : un rechargement ne duplique pas."""
    global _SOURCES
    _SOURCES = [s for s in _SOURCES if s.nom != source.nom] + [source]


def sources() -> tuple[Source, ...]:
    return tuple(_SOURCES)


async def _autorise(bot, guild, auteur, source: Source) -> bool:
    """La même décision que pour la commande équivalente, jamais une autre."""
    if source.commande_equivalente is None:
        return True
    try:
        from utils import access_matrix

        decision = await access_matrix.evaluate(
            bot, command_name=source.commande_equivalente, author=auteur, guild=guild,
        )
        return bool(decision.allowed)
    except Exception:  # noqa: BLE001 — dans le doute on ne divulgue rien
        logger.debug("Politique d'accès illisible pour %s", source.nom, exc_info=True)
        return False


async def bloc(bot, guild, auteur, texte: str) -> str:
    """Ce que l'IA a le droit de savoir pour CETTE question, ou une chaîne vide."""
    if guild is None or auteur is None or not str(texte or "").strip():
        return ""

    concernees = [s for s in _SOURCES if _concerne_sans_echec(s, texte)]
    if not concernees:
        return ""

    morceaux: list[str] = []
    for source in concernees:
        if not await _autorise(bot, guild, auteur, source):
            logger.debug("Source %s refusée à %s", source.nom, getattr(auteur, "id", None))
            continue
        try:
            morceau = await asyncio.wait_for(
                source.lire(bot, guild, auteur, texte), timeout=DELAI_MAX_S,
            )
        except asyncio.TimeoutError:
            logger.info("Source %s trop lente : ignorée.", source.nom)
            continue
        except Exception:  # noqa: BLE001 — jamais au prix de la réponse
            logger.debug("Source %s illisible.", source.nom, exc_info=True)
            continue
        if morceau and morceau.strip():
            morceaux.append(morceau.strip())

    if not morceaux:
        return ""

    # 21/11/2026, revue Codex : trancher à LONGUEUR_MAX coupait un bloc en plein
    # milieu tout en gardant son en-tête « Toutes les sanctions » et sa consigne
    # « dis qu'elle n'est pas enregistrée ». Un dossier supprimé par la
    # troncature recevait donc un démenti FAUX — exactement le défaut corrigé la
    # veille sur la limite de huit dossiers, réintroduit un étage plus haut.
    #
    # On ne coupe plus à l'intérieur d'un bloc : un bloc entre entier ou pas du
    # tout, et s'il en manque un, on le DIT au lieu de laisser croire à une
    # liste complète.
    gardes, longueur, tronque = [], 0, False
    for morceau in morceaux:
        if longueur + len(morceau) + 2 > LONGUEUR_MAX and gardes:
            tronque = True
            continue
        gardes.append(morceau)
        longueur += len(morceau) + 2
    if not gardes:  # un seul bloc, plus long que la limite à lui seul
        gardes, tronque = [morceaux[0][:LONGUEUR_MAX]], True

    avertissement = (
        " ATTENTION : une partie des données n'a pas pu être incluse ici. Ne dis "
        "donc JAMAIS qu'une information n'existe pas — dis que tu ne la vois pas "
        "et renvoie vers la commande du module concerné."
        if tronque else
        " Ce qui n'y est pas, dis que tu ne l'as pas sous les yeux."
    )
    return (
        "[Données réelles du serveur, lues dans la base SentriX. C'est la SOURCE DE "
        "VÉRITÉ : réponds à partir de ces lignes et n'invente jamais un chiffre, une "
        f"date ou un nom qui n'y figure pas.{avertissement}]\n" + "\n\n".join(gardes)
    )


def _concerne_sans_echec(source: Source, texte: str) -> bool:
    try:
        return bool(source.concerne(texte))
    except Exception:  # noqa: BLE001
        logger.debug("Détecteur de %s en erreur.", source.nom, exc_info=True)
        return False


__all__ = ["LONGUEUR_MAX", "Source", "bloc", "enregistrer", "sources"]
