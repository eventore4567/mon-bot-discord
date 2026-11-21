"""Copie préventive du serveur (« empreinte ») pour l'anti-nuke.

21/11/2026. L'anti-nuke V55 (cogs/antinuke_emergency_v55.py) sait déjà tout
remettre en place après une destruction… **à condition d'avoir vu passer les
événements**. Il mémorise chaque salon et chaque rôle au moment où Discord
annonce sa suppression, puis rejoue ces dégâts à l'envers.

Ce modèle laisse un trou qu'on ne peut pas boucher en améliorant la réaction :

* si le bot redémarre pendant le nuke, les dégâts enregistrés avant le
  redémarrage sont purgés au bout de ``PURGE_AFTER_SECONDS`` et ceux d'après
  ne décrivent plus que la fin du carnage ;
* si le bot est hors ligne au moment du nuke, il n'a rien vu du tout ;
* si une passerelle Discord perd un événement (ça arrive), le salon
  correspondant n'existe dans aucune mémoire.

Dans ces trois cas, l'anti-nuke bannit bien l'auteur mais n'a plus rien à
restaurer. D'où cette empreinte : une copie entière de la structure du serveur
(rôles, salons, catégories, permissions) prise **avant** tout incident et
rafraîchie en tâche de fond. Elle sert de filet quand la mémoire des
événements est vide ou incomplète.

Ce qu'elle ne couvre pas, volontairement : les messages, les membres, les
émojis et les autocollants. On restaure la structure du serveur, pas son
historique — recréer des messages n'est de toute façon pas possible.

Le module ne connaît ni ``discord`` ni l'anti-nuke : les fonctions qui
photographient un rôle ou un salon lui sont passées en paramètre
(``instantane_role`` / ``instantane_salon``), ce qui le rend testable sans
Discord et évite un import circulaire avec le cog.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

TABLE = "serveur_empreinte"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    guild_id INTEGER PRIMARY KEY,
    pris_le INTEGER NOT NULL,
    contenu_json TEXT NOT NULL
)
"""

#: Deux captures du même serveur ne peuvent pas se suivre plus vite que ça.
#: Sans ce frein, un simple ménage de salons déclencherait une capture par
#: salon touché : des centaines d'écritures pour un contenu quasi identique.
DELAI_ENTRE_CAPTURES_S = 600

#: Au-delà de cet âge, l'empreinte ne sert plus à recréer quoi que ce soit :
#: un serveur peut avoir changé du tout au tout en une semaine, et recréer
#: cinquante salons supprimés exprès le mois dernier ferait plus de mal que
#: le nuke qu'on voulait réparer.
AGE_MAX_S = 7 * 24 * 3600

#: Ordre de restauration. Les rôles d'abord, parce que les permissions de
#: salon les citent ; les catégories ensuite, parce que les salons s'y
#: rangent ; le reste en dernier.
ORDRE = ("roles", "categories", "salons")


def composer(
    guild: Any,
    *,
    instantane_role: Callable[[Any], dict[str, Any]],
    instantane_salon: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    """Photographie la structure complète d'un serveur.

    Le rôle ``@everyone`` est exclu : il ne peut pas être supprimé, donc jamais
    restauré, et ses permissions sont déjà gardées par la garde des permissions.
    """
    roles: list[dict[str, Any]] = []
    for role in list(getattr(guild, "roles", []) or []):
        if int(getattr(role, "id", 0)) == int(getattr(guild, "id", 0)):
            continue  # @everyone porte l'ID du serveur
        if bool(getattr(role, "managed", False)):
            continue  # rôle d'intégration : Discord refuse de le recréer
        try:
            roles.append(instantane_role(role))
        except Exception:  # noqa: BLE001 — un rôle illisible ne doit pas vider l'empreinte
            logger.warning("Empreinte : rôle ignoré sur %s", getattr(guild, "id", "?"), exc_info=True)

    salons: list[dict[str, Any]] = []
    for salon in list(getattr(guild, "channels", []) or []):
        try:
            salons.append(instantane_salon(salon))
        except Exception:  # noqa: BLE001
            logger.warning("Empreinte : salon ignoré sur %s", getattr(guild, "id", "?"), exc_info=True)

    return {"roles": roles, "salons": salons}


async def installer(db) -> None:
    await db.execute(SCHEMA)


async def lire(db, guild_id: int) -> dict[str, Any] | None:
    """Dernière empreinte connue, ou ``None`` s'il n'y en a aucune d'exploitable."""
    try:
        ligne = await db.fetchone(
            f"SELECT pris_le, contenu_json FROM {TABLE} WHERE guild_id = ?", (int(guild_id),)
        )
    except Exception:  # noqa: BLE001 — table absente sur une vieille base
        logger.warning("Empreinte : lecture impossible pour %s", guild_id, exc_info=True)
        return None
    if not ligne:
        return None
    try:
        contenu = json.loads(ligne["contenu_json"])
    except (TypeError, ValueError, KeyError):
        return None
    if not isinstance(contenu, dict):
        return None
    contenu["pris_le"] = int(ligne["pris_le"])
    return contenu


async def age(db, guild_id: int, *, maintenant: float | None = None) -> float | None:
    """Âge en secondes de l'empreinte, ``None`` s'il n'y en a pas."""
    empreinte = await lire(db, guild_id)
    if empreinte is None:
        return None
    return max(0.0, (maintenant if maintenant is not None else time.time()) - empreinte["pris_le"])


def trop_vieille(empreinte: dict[str, Any], *, maintenant: float | None = None) -> bool:
    pris_le = int(empreinte.get("pris_le") or 0)
    if not pris_le:
        return True
    ecoule = (maintenant if maintenant is not None else time.time()) - pris_le
    return ecoule > AGE_MAX_S


async def capturer(
    db,
    guild: Any,
    *,
    instantane_role: Callable[[Any], dict[str, Any]],
    instantane_salon: Callable[[Any], dict[str, Any]],
    forcer: bool = False,
    maintenant: float | None = None,
) -> dict[str, Any] | None:
    """Écrit une nouvelle empreinte. Renvoie ``None`` si c'est trop tôt.

    ``forcer`` ignore le frein de ``DELAI_ENTRE_CAPTURES_S`` : utilisé quand le
    propriétaire demande explicitement une copie, jamais en tâche de fond.
    """
    instant = maintenant if maintenant is not None else time.time()
    if not forcer:
        precedent = await age(db, getattr(guild, "id", 0), maintenant=instant)
        if precedent is not None and precedent < DELAI_ENTRE_CAPTURES_S:
            return None
    contenu = composer(
        guild, instantane_role=instantane_role, instantane_salon=instantane_salon
    )
    if not contenu["roles"] and not contenu["salons"]:
        # Serveur vu vide : presque toujours un cache pas encore rempli au
        # démarrage. Écraser une bonne empreinte par du vide serait pire que
        # de ne rien faire.
        return None
    await db.execute(
        f"INSERT INTO {TABLE}(guild_id, pris_le, contenu_json) VALUES(?, ?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET pris_le = excluded.pris_le, "
        "contenu_json = excluded.contenu_json",
        (int(getattr(guild, "id", 0)), int(instant), json.dumps(contenu, ensure_ascii=False)),
    )
    contenu["pris_le"] = int(instant)
    return contenu


def _est_categorie(instantane: dict[str, Any]) -> bool:
    return str(instantane.get("kind") or "") == "category"


def disparus(
    empreinte: dict[str, Any],
    guild: Any,
    *,
    maintenant: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Ce que l'empreinte contient et que le serveur n'a plus.

    Renvoie trois listes, dans l'ordre où il faut les recréer
    (``ORDRE``). Une empreinte trop vieille renvoie trois listes vides :
    mieux vaut ne rien restaurer que recréer un serveur d'il y a un mois.
    """
    vide: dict[str, list[dict[str, Any]]] = {cle: [] for cle in ORDRE}
    if not empreinte or trop_vieille(empreinte, maintenant=maintenant):
        return vide

    get_role = getattr(guild, "get_role", None)
    get_channel = getattr(guild, "get_channel", None)

    for instantane in empreinte.get("roles") or []:
        identifiant = int(instantane.get("id") or 0)
        if not identifiant or bool(instantane.get("managed")):
            continue
        if get_role is not None and get_role(identifiant) is not None:
            continue
        vide["roles"].append(instantane)

    for instantane in empreinte.get("salons") or []:
        identifiant = int(instantane.get("id") or 0)
        if not identifiant:
            continue
        if get_channel is not None and get_channel(identifiant) is not None:
            continue
        cle = "categories" if _est_categorie(instantane) else "salons"
        vide[cle].append(instantane)

    vide["roles"].sort(key=lambda item: int(item.get("position") or 0))
    for cle in ("categories", "salons"):
        vide[cle].sort(key=lambda item: int(item.get("position") or 0))
    return vide


def total(absents: dict[str, Iterable[dict[str, Any]]]) -> int:
    return sum(len(list(absents.get(cle) or [])) for cle in ORDRE)


__all__ = [
    "AGE_MAX_S",
    "DELAI_ENTRE_CAPTURES_S",
    "ORDRE",
    "SCHEMA",
    "TABLE",
    "age",
    "capturer",
    "composer",
    "disparus",
    "installer",
    "lire",
    "total",
    "trop_vieille",
]
