"""Compatibilité des sauvegardes automatiques Security V2 avec +server-restore.

Le moteur de restauration historique attend exactement les mêmes clés que +server-backup,
notamment les permission overwrites des catégories et salons. Cette couche garde ce contrat
pour que les sauvegardes automatiques soient directement restaurables.
"""
from __future__ import annotations

import discord

from .security_v2_runtime import SecurityV2Runtime

_INSTALLED = False


def _snapshot_overwrites(channel) -> list[dict]:
    result: list[dict] = []
    try:
        items = channel.overwrites.items()
    except Exception:
        return result
    for target, overwrite in items:
        try:
            allow, deny = overwrite.pair()
            result.append({
                "type": "role" if isinstance(target, discord.Role) else "member",
                "name": target.name if isinstance(target, discord.Role) else str(target.id),
                "allow": int(allow.value),
                "deny": int(deny.value),
            })
        except Exception:
            continue
    return result


def _compatible_snapshot(guild: discord.Guild) -> dict:
    data = {
        "roles": [
            {
                "name": role.name,
                "color": int(role.color.value),
                "hoist": bool(role.hoist),
                "mentionable": bool(role.mentionable),
                "permissions": int(role.permissions.value),
                "position": int(role.position),
            }
            for role in guild.roles
            if role != guild.default_role and not role.managed
        ],
        "categories": [],
    }

    for category in guild.categories:
        cat_data = {
            "name": category.name,
            "position": int(category.position),
            "overwrites": _snapshot_overwrites(category),
            "channels": [],
        }
        for channel in category.channels:
            ch_data = {
                "name": channel.name,
                "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
                "position": int(channel.position),
                "overwrites": _snapshot_overwrites(channel),
            }
            if isinstance(channel, discord.TextChannel):
                ch_data.update({
                    "topic": channel.topic,
                    "nsfw": bool(channel.nsfw),
                    "slowmode_delay": int(channel.slowmode_delay),
                })
            cat_data["channels"].append(ch_data)
        data["categories"].append(cat_data)

    data["uncategorized"] = [
        {
            "name": channel.name,
            "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
            "position": int(channel.position),
        }
        for channel in guild.channels
        if channel.category is None
        and isinstance(channel, (discord.TextChannel, discord.VoiceChannel))
    ]
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    SecurityV2Runtime._snapshot_server = staticmethod(_compatible_snapshot)
