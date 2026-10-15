"""Plusieurs processus SentriX actifs en même temps : qui s'occupe de quel serveur.

Discord répartit les serveurs en « shards » : shard = (id du serveur >> 22) % nombre
de shards. Avec plusieurs processus (clusters), chacun ouvre une partie des shards
et ne voit QUE les serveurs de ses shards. Configuration :

    SHARD_COUNT              nombre total de shards (obligatoire au-delà d'un cluster)
    SENTRIX_CLUSTER_COUNT    nombre de processus actifs (défaut 1 : comportement actuel)
    SENTRIX_CLUSTER_ID       0 … COUNT-1 : la part de CE processus

Le shard n est ouvert par le cluster n % COUNT.

Ce module répond aux deux questions que le reste du code se posait mal :

* « Ce serveur est-il le mien ? » — un serveur absent du cache n'est pas forcément
  quitté : il peut appartenir à un autre processus, ou être momentanément
  indisponible (panne Discord : ``get_guild`` le rend alors sans aucun salon).
  Plusieurs tâches de fond prenaient ces cas pour un départ et marquaient des
  tickets « supprimés » ou oubliaient des quarantaines. ``etat_serveur`` ne
  répond « parti » que si c'est sûr.
* « Cette tâche globale doit-elle tourner ici ? » — synchronisation des
  commandes « / », statistiques des annuaires… une seule fois, sur le cluster 0.
"""
from __future__ import annotations

import os
from typing import Any

PRESENT = "present"        # dans ce processus, disponible
AILLEURS = "ailleurs"      # géré par un autre cluster
INDISPONIBLE = "indisponible"  # panne Discord ou démarrage en cours : ne rien conclure
PARTI = "parti"            # le bot n'est plus sur ce serveur (certain)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def cluster_count() -> int:
    return max(1, _int_env("SENTRIX_CLUSTER_COUNT", 1))


def cluster_id() -> int:
    return max(0, min(cluster_count() - 1, _int_env("SENTRIX_CLUSTER_ID", 0)))


def is_primary_cluster() -> bool:
    """Le cluster qui exécute les tâches globales (une seule fois pour tout le bot)."""
    return cluster_id() == 0


def shard_ids_for_cluster(shard_count: int, cluster: int | None = None, count: int | None = None) -> list[int]:
    count = cluster_count() if count is None else count
    cluster = cluster_id() if cluster is None else cluster
    return [shard for shard in range(max(1, shard_count)) if shard % count == cluster]


def shard_of(guild_id: int, shard_count: int) -> int:
    return (int(guild_id) >> 22) % max(1, int(shard_count))


def owns_guild(bot: Any, guild_id: int) -> bool:
    """Vrai si ce processus a la charge de ce serveur (toujours vrai avec un seul cluster)."""
    shard_ids = getattr(bot, "shard_ids", None)
    shard_count = getattr(bot, "shard_count", None)
    if not shard_ids or not shard_count:
        return True
    return shard_of(guild_id, shard_count) in set(shard_ids)


def etat_serveur(bot: Any, guild_id: int):
    """(serveur ou None, état). Seul l'état PARTI autorise un nettoyage de données."""
    if not owns_guild(bot, guild_id):
        return None, AILLEURS
    guild = bot.get_guild(int(guild_id))
    if guild is not None:
        if getattr(guild, "unavailable", False):
            return None, INDISPONIBLE
        return guild, PRESENT
    is_ready = getattr(bot, "is_ready", None)
    if callable(is_ready) and not is_ready():
        return None, INDISPONIBLE
    return None, PARTI


# --------------------------------------------------------------- état partagé

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sentrix_cluster_state ("
    "cluster_id INTEGER PRIMARY KEY, shard_ids TEXT, guilds INTEGER NOT NULL, "
    "members INTEGER NOT NULL, updated_at INTEGER NOT NULL)"
)


def _local(bot: Any) -> tuple[int, int]:
    guilds = list(getattr(bot, "guilds", []) or [])
    return len(guilds), sum(int(getattr(g, "member_count", 0) or 0) for g in guilds)


async def publier(bot: Any) -> None:
    """Ce cluster écrit ses chiffres dans la base partagée."""
    import time

    guilds, members = _local(bot)
    await bot.db.execute(_SCHEMA)
    await bot.db.execute(
        "INSERT INTO sentrix_cluster_state (cluster_id, shard_ids, guilds, members, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(cluster_id) DO UPDATE SET shard_ids = excluded.shard_ids, "
        "guilds = excluded.guilds, members = excluded.members, updated_at = excluded.updated_at",
        (cluster_id(), ",".join(str(s) for s in (getattr(bot, "shard_ids", None) or [])),
         guilds, members, int(time.time())),
    )


async def totaux(bot: Any, max_age: int = 300) -> dict[str, int]:
    """Serveurs et membres de TOUS les clusters (ce cluster en direct, les autres via la base)."""
    import time

    guilds, members = _local(bot)
    if cluster_count() <= 1:
        return {"guilds": guilds, "members": members, "clusters": 1}
    await bot.db.execute(_SCHEMA)
    rows = await bot.db.fetchall(
        "SELECT cluster_id, guilds, members FROM sentrix_cluster_state WHERE cluster_id <> ? AND updated_at >= ?",
        (cluster_id(), int(time.time()) - max_age),
    )
    return {
        "guilds": guilds + sum(int(r["guilds"]) for r in rows),
        "members": members + sum(int(r["members"]) for r in rows),
        "clusters": 1 + len(rows),
    }


async def battement(bot: Any, interval: float = 60.0) -> None:
    """Publie les chiffres de ce cluster toutes les ``interval`` secondes."""
    import asyncio
    import logging

    log = logging.getLogger("bot.cluster")
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await publier(bot)
        except Exception:
            log.warning("État du cluster %s non publié.", cluster_id(), exc_info=True)
        await asyncio.sleep(interval)


__all__ = [
    "PRESENT", "AILLEURS", "INDISPONIBLE", "PARTI",
    "cluster_count", "cluster_id", "is_primary_cluster", "shard_ids_for_cluster",
    "shard_of", "owns_guild", "etat_serveur", "publier", "totaux", "battement",
]
