"""Événements Ressources serveur manquants pour Setup V2."""
from __future__ import annotations

import time

import discord

from utils import embeds, log_service


def _actor(value) -> str:
    return value.mention if value is not None else "Inconnu / Discord"


async def _send(bot, guild: discord.Guild, title: str, fields, event: str) -> None:
    panel = embeds.log_embed(title, fields=fields)
    await log_service.send_log(
        bot,
        guild,
        "resources",
        panel,
        event_key=log_service.make_event_key(
            guild.id,
            event,
            discriminator=time.time_ns(),
        ),
    )


def install(bot) -> None:
    if getattr(bot, "_sentrix_resource_events_v2", False):
        return

    async def on_invite_create(invite: discord.Invite):
        guild = invite.guild
        if not isinstance(guild, discord.Guild):
            return
        await _send(
            bot,
            guild,
            "Invitation créée",
            [
                ("Code", f"`{invite.code}`", True),
                ("Salon", getattr(invite.channel, "mention", "Inconnu"), True),
                ("Créée par", _actor(invite.inviter), True),
                ("Utilisations max", str(invite.max_uses or "Illimité"), True),
                ("Expiration", f"{invite.max_age}s" if invite.max_age else "Jamais", True),
            ],
            "invite_create",
        )

    async def on_invite_delete(invite: discord.Invite):
        guild = invite.guild
        if not isinstance(guild, discord.Guild):
            return
        await _send(
            bot,
            guild,
            "Invitation supprimée",
            [
                ("Code", f"`{invite.code}`", True),
                ("Salon", getattr(invite.channel, "mention", "Inconnu"), True),
            ],
            "invite_delete",
        )

    async def on_webhooks_update(channel: discord.abc.GuildChannel):
        guild = getattr(channel, "guild", None)
        if not isinstance(guild, discord.Guild):
            return
        await _send(
            bot,
            guild,
            "Webhooks modifiés",
            [
                ("Salon", getattr(channel, "mention", str(channel)), True),
                ("ID salon", f"`{channel.id}`", True),
            ],
            "webhooks_update",
        )

    bot.add_listener(on_invite_create, "on_invite_create")
    bot.add_listener(on_invite_delete, "on_invite_delete")
    bot.add_listener(on_webhooks_update, "on_webhooks_update")
    bot._sentrix_resource_events_v2 = True


__all__ = ["install"]