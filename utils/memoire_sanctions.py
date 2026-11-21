"""Ce que SentriX a vraiment fait, et pourquoi (17/11/2026).

Test de l'utilisateur : « SentriX, pourquoi tu as banni Natix hier à 14h ? »
Réponse obtenue : « Je n'ai pas accès ici au détail de l'action effectuée hier
à 14 h, donc je ne peux pas confirmer la raison sans l'inventer. »

Refuser d'inventer est le minimum, et SentriX l'a bien fait. Mais l'information
EXISTE : chaque sanction est enregistrée avec son numéro de dossier, son
action, son motif, son modérateur et sa date. L'IA ne la lisait simplement
jamais. Elle disait « je n'ai pas accès » alors que la base, elle, savait.

Deux règles non négociables encadrent cette mémoire.

1. ELLE NE S'OUVRE QU'AUX MODÉRATEURS. Un motif de sanction parle d'un membre
   et de ce qu'on lui reproche : ce n'est pas une information de salon public.
   Un membre ordinaire qui pose la question obtient la réponse d'avant.

2. ELLE N'EST LUE QUE QUAND ON LA DEMANDE. Charger l'historique à chaque
   message gonflerait un prompt déjà à ~2000 tokens, donc la latence, pour une
   information inutile 99 fois sur 100.

Et quand un membre n'a AUCUNE sanction, on le dit aussi : « Natix n'a aucune
sanction enregistrée » est une vraie réponse, bien meilleure qu'un silence.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import NamedTuple

logger = logging.getLogger("bot.memoire-sanctions")

#: Les mots qui désignent une mesure de modération.
_ACTIONS = (
    "ban", "banni", "bannissement", "débanni", "deban", "unban",
    "mute", "muté", "mutée", "timeout", "exclu", "exclusion", "silence",
    "warn", "avertissement", "avertis", "averti",
    "kick", "expuls", "sanction", "sanctionné", "puni", "punition",
)
#: Sans l'un de ceux-là, « ban » est un mot au hasard, pas une question.
_INTERROGATIFS = (
    "pourquoi", "quand", "qui", "combien", "quel", "quelle", "comment",
    "motif", "raison", "historique", "casier", "dossier", "déjà", "est-ce",
)
#: Un nom plus court attrape n'importe quel mot de la phrase.
_LONGUEUR_NOM_MINIMALE = 3
#: Au-delà, on alourdit le prompt sans aider à répondre.
_SANCTIONS_MAX = 8

_MENTION = re.compile(r"<@!?(\d{15,25})>")

_LIBELLES = {
    "ban": "bannissement", "tempban": "bannissement temporaire", "unban": "débannissement",
    "kick": "expulsion", "mute": "mise en sourdine", "unmute": "levée de sourdine",
    "timeout": "exclusion temporaire", "warn": "avertissement", "unwarn": "retrait d'avertissement",
}


#: Les actions se cherchent en DÉBUT de mot : « banni », « bannissement » et
#: « bannir » sont la même idée. Les interrogatifs, eux, se cherchent en mot
#: ENTIER — « quelqu'un » contient « qui », et « j'ai banni quelqu'un » n'est
#: pas une question. Ce piège a été attrapé par le test, pas par moi.
_ACTIONS_RE = re.compile(r"\b(?:" + "|".join(_ACTIONS) + r")\w*", re.IGNORECASE)
_INTERROGATIFS_RE = re.compile(r"\b(?:" + "|".join(_INTERROGATIFS) + r")\b", re.IGNORECASE)


def question_sur_une_sanction(texte: str) -> bool:
    """Vrai seulement si la phrase demande VRAIMENT un historique de modération."""
    phrase = str(texte or "")
    return bool(_ACTIONS_RE.search(phrase) and _INTERROGATIFS_RE.search(phrase))


def _a_les_permissions_discord(membre) -> bool:
    permissions = getattr(membre, "guild_permissions", None)
    if permissions is None:
        return False
    return bool(
        getattr(permissions, "administrator", False)
        or getattr(permissions, "ban_members", False)
        or getattr(permissions, "kick_members", False)
        or getattr(permissions, "moderate_members", False)
        or getattr(permissions, "manage_guild", False)
    )


async def peut_consulter(bot, guild, membre) -> bool:
    """Un motif de sanction n'est pas une information de salon public.

    20/11/2026, revue Codex : beaucoup de serveurs ne donnent AUCUNE permission
    Discord à leur staff et passent par le rôle configuré (`mod_role`).
    +modhistory l'accepte déjà, via access_matrix. Ne regarder que les bits
    natifs refusait donc la mémoire à des modérateurs qui consultent pourtant
    l'historique par commande — deux réponses différentes pour la même
    personne. On interroge la même politique qu'eux.
    """
    if _a_les_permissions_discord(membre):
        return True
    if bot is None or guild is None or membre is None:
        return False
    try:
        from utils import access_matrix

        return await access_matrix.backend_for(bot).has_staff_role(guild.id, membre)
    except Exception:  # noqa: BLE001 — en cas de doute, on ne divulgue rien
        logger.debug("Rôle staff indisponible pour %s", getattr(membre, "id", None),
                     exc_info=True)
        return False


class Cible(NamedTuple):
    """Quelqu'un dont on demande le dossier — membre du serveur ou non."""

    identifiant: int
    nom: str


def cibles_citees(texte: str, guild, bot=None) -> list[Cible]:
    """Les personnes désignées dans la question, par mention ou par nom.

    Revue Codex du 17/11/2026 : la première version ne retenait que les
    membres présents, via guild.get_member puis un balayage de guild.members.
    Or un membre BANNI n'est plus dans le serveur, et un membre expulsé non
    plus. La fonction échouait donc exactement sur « pourquoi tu as banni X »,
    le cas qui a motivé toute la fonctionnalité. Un identifiant mentionné
    explicitement est désormais conservé même sans appartenance : la base, elle,
    garde le dossier. Un nom seul reste limité aux membres présents — on n'a
    rien d'autre pour le résoudre.
    """
    phrase = str(texte or "")
    trouves: list[Cible] = []
    vus: set[int] = set()

    def _ajouter(identifiant: int, nom: str) -> None:
        if identifiant not in vus:
            vus.add(identifiant)
            trouves.append(Cible(identifiant, nom))

    for brut in _MENTION.findall(phrase):
        identifiant = int(brut)
        membre = guild.get_member(identifiant) if guild else None
        if membre is None and bot is not None:
            membre = bot.get_user(identifiant)
        nom = getattr(membre, "display_name", None) or getattr(membre, "name", None)
        _ajouter(identifiant, nom or f"l'utilisateur {identifiant}")

    # 20/11/2026, revue Codex : le balayage prenait les membres dans l'ordre du
    # serveur. Avec « Jean », « Paul », « Dupont » et « Jean-Paul Dupont »,
    # demander le dossier de Jean-Paul Dupont ramenait les trois premiers et
    # jamais le bon — la limite de trois cibles écartait la personne visée.
    # On classe donc par nom le PLUS LONG d'abord (le plus spécifique), et on
    # écarte ensuite un nom déjà contenu dans une correspondance retenue.
    minuscule = phrase.casefold()
    correspondances = []
    for membre in (getattr(guild, "members", None) or []):
        if membre.id in vus or getattr(membre, "bot", False):
            continue
        # 21/11/2026 : ce `for` s'arrêtait au PREMIER nom correspondant. Deux
        # membres peuvent partager un pseudo affiché — c'est courant sur
        # Discord, un pseudo n'est pas unique. Avec « Alex » (alice) et
        # « Alex » (bob), « Pourquoi Alex (bob) a été banni ? » retenait le
        # premier Alex et n'examinait JAMAIS « bob », donc la mémoire lisait
        # le dossier de la mauvaise personne. On retient donc TOUTES les
        # correspondances ; _ajouter dédoublonne déjà par identifiant.
        for nom in filter(None, (getattr(membre, "display_name", ""), getattr(membre, "name", ""))):
            if len(nom) >= _LONGUEUR_NOM_MINIMALE and nom.casefold() in minuscule:
                correspondances.append((nom.casefold(), membre, nom))

    # 21/11/2026 : écarter le nom court GLOBALEMENT était trop brutal — c'était
    # ma propre correction de la veille, et la revue l'a reprise à juste titre.
    # « Pourquoi Jean ET Jean-Paul Dupont ont été bannis ? » ne retenait plus
    # que Jean-Paul Dupont : Jean est pourtant cité séparément, à un autre
    # endroit de la phrase. On raisonne donc sur les POSITIONS et non sur les
    # noms : un nom n'est écarté que si toutes ses occurrences tombent à
    # l'intérieur d'un nom plus long déjà retenu.
    correspondances.sort(key=lambda item: len(item[0]), reverse=True)
    occupes: list[tuple[int, int]] = []

    def _occurrence_libre(plat: str) -> tuple[int, int] | None:
        depart = 0
        while True:
            debut = minuscule.find(plat, depart)
            if debut < 0:
                return None
            fin = debut + len(plat)
            if not any(d <= debut and fin <= f for d, f in occupes):
                return debut, fin
            depart = debut + 1

    for plat, membre, nom in correspondances:
        place = _occurrence_libre(plat)
        if place is None:
            continue  # ce nom n'apparaît que dans un nom plus long déjà retenu
        occupes.append(place)
        _ajouter(membre.id, getattr(membre, "display_name", None) or nom)
    return trouves[:3]


def _date_lisible(horodatage) -> str:
    try:
        return datetime.fromtimestamp(int(horodatage), tz=timezone.utc).strftime("%d/%m/%Y à %Hh%M")
    except (TypeError, ValueError, OSError):
        return "date inconnue"


def _ligne(sanction, guild) -> str:
    action = str(sanction["action"] or "sanction").casefold()
    libelle = _LIBELLES.get(action, action)
    modateur = guild.get_member(int(sanction["moderator_id"] or 0)) if guild else None
    par = getattr(modateur, "display_name", None) or f"modérateur {sanction['moderator_id']}"
    morceaux = [
        f"dossier #{sanction['case_number']}",
        libelle,
        _date_lisible(sanction["created_at"]),
        f"par {par}",
    ]
    duree = int(sanction["duration_seconds"] or 0)
    if duree:
        morceaux.append(f"durée {duree // 60} min" if duree < 3600 else f"durée {duree // 3600} h")
    motif = str(sanction["reason"] or "").strip()
    morceaux.append(f"motif : {motif}" if motif else "aucun motif enregistré")
    return "- " + " · ".join(morceaux)


async def memoire(bot, guild, auteur, texte: str) -> str:
    """Le bloc à donner à l'IA, ou une chaîne vide s'il n'y a rien à dire."""
    if guild is None or not question_sur_une_sanction(texte):
        return ""
    if not await peut_consulter(bot, guild, auteur):
        logger.debug("Historique refusé : %s n'est pas modérateur.", getattr(auteur, "id", None))
        return ""
    cibles = cibles_citees(texte, guild, bot)
    if not cibles:
        return ""

    blocs, tronque = [], False
    for cible in cibles:
        try:
            # Un dossier de plus que la limite : c'est ce qui permet de SAVOIR
            # qu'il en reste, au lieu de le deviner.
            lignes = await bot.db.get_sanction_history(
                guild.id, cible.identifiant, _SANCTIONS_MAX + 1,
            )
        except Exception:  # noqa: BLE001 — jamais bloquant pour la réponse
            logger.debug("Historique illisible pour %s", cible.identifiant, exc_info=True)
            continue
        lignes = list(lignes or ())
        if not lignes:
            blocs.append(
                f"{cible.nom} (id {cible.identifiant}) : aucune sanction enregistrée sur ce serveur."
            )
            continue
        if len(lignes) > _SANCTIONS_MAX:
            tronque = True
            lignes = lignes[:_SANCTIONS_MAX]
            entete = (
                f"Les {_SANCTIONS_MAX} sanctions LES PLUS RÉCENTES de {cible.nom} "
                f"(id {cible.identifiant}) — il en existe de plus anciennes, non listées ici"
            )
        else:
            entete = (
                f"Toutes les sanctions de {cible.nom} (id {cible.identifiant}), "
                "de la plus récente à la plus ancienne"
            )
        detail = "\n".join(_ligne(sanction, guild) for sanction in lignes)
        blocs.append(f"{entete} :\n{detail}")

    if not blocs:
        return ""
    # Revue Codex du 17/11/2026 : avec plus de huit dossiers, la consigne
    # « dis qu'elle n'est pas enregistrée » transformait une liste tronquée en
    # démenti faux. On ne nie une sanction que sur une liste complète.
    consigne_absence = (
        "Une partie de l'historique est tronquée : ne dis JAMAIS qu'une sanction "
        "n'existe pas et ne donne aucun total — dis que tu ne vois que les plus "
        "récentes et propose `+modhistory` pour le dossier complet."
        if tronque else
        "Si la question porte sur une action absente d'une liste annoncée comme "
        "complète, dis qu'elle n'est pas enregistrée."
    )
    return (
        "[Historique de modération lu dans la base SentriX. C'est la SOURCE DE VÉRITÉ : "
        "réponds à partir de ces lignes, cite le numéro de dossier, et n'invente jamais "
        f"une sanction, une date ou un motif qui n'y figure pas. {consigne_absence}]\n"
        + "\n\n".join(blocs)
    )


__all__ = ["Cible", "cibles_citees", "memoire", "peut_consulter", "question_sur_une_sanction"]
