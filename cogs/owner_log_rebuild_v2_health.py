"""Critère strict d'idempotence pour +reset-logs-all V2.

Une simple validation de permissions ne suffit pas : les deux serveurs qui ont rollback
peuvent encore avoir d'anciens salons techniquement accessibles. On ne les considère donc
comme déjà réparés que si les 8 routes pointent vers l'architecture créée par le rebuild
(topic officiel SentriX sur chaque salon).
"""
from __future__ import annotations

import discord

from utils import log_service
from . import owner_log_rebuild as v1
from . import owner_log_rebuild_v2 as v2


async def strict_is_healthy(bot, guild: discord.Guild) -> bool:
    route_ids: set[int] = set()
    for log_type, _column, _name, _topic in v1.LOG_ROUTES:
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
        except Exception:
            return False
        channel_id = int(setting.get("channel_id") or 0)
        if not setting.get("enabled") or not channel_id:
            return False
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return False
        valid, _reason = log_service.validate_channel(guild, channel_id)
        if not valid:
            return False
        if not str(channel.topic or "").startswith("SentriX logs •"):
            return False
        route_ids.add(channel_id)

    # Huit types doivent réellement avoir huit salons distincts.
    return len(route_ids) == len(v1.LOG_ROUTES)


def install() -> None:
    v2._is_healthy = strict_is_healthy
