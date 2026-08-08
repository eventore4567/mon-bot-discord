"""Empêche les cartes Components V2 des logs SentriX de notifier les mentions.

Les mentions restent visibles dans les journaux, mais @membre, @rôle, @everyone et @here
ne déclenchent aucune notification. Le patch est volontairement limité aux vues
PremiumLogLayout afin de conserver les vrais pings du reste du bot (tickets, notifications,
giveaways, etc.).
"""
from __future__ import annotations

import discord

_INSTALLED = False
_ORIGINAL_TEXT_CHANNEL_SEND = discord.TextChannel.send


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_send = discord.TextChannel.send
    if getattr(original_send, "_sentrix_logs_no_ping", False):
        _INSTALLED = True
        return

    async def send_without_log_mentions(self, *args, **kwargs):
        view = kwargs.get("view")
        if (
            view is not None
            and view.__class__.__name__ == "PremiumLogLayout"
            and view.__class__.__module__.endswith("premium_logs_v2")
        ):
            # La mention reste rendue visuellement par Discord, sans générer de ping.
            kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        return await original_send(self, *args, **kwargs)

    send_without_log_mentions._sentrix_logs_no_ping = True
    discord.TextChannel.send = send_without_log_mentions
    _INSTALLED = True
