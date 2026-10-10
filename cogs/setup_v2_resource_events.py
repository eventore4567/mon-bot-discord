"""Événements Ressources serveur manquants pour Setup V2."""
from __future__ import annotations

import time

import discord

from utils import embeds, log_service


def _actor(value) -> str:
    return value.mention if value is not None else "Non renseigné par Discord"


def _expiration(invite: discord.Invite) -> str:
    """Une date lisible, jamais « 604800s » pour une invitation de 7 jours."""
    expires = getattr(invite, "expires_at", None)
    if expires is not None:
        return f"<t:{int(expires.timestamp())}:R>"
    seconds = max(0, int(getattr(invite, "max_age", 0) or 0))
    if not seconds:
        return "Jamais"
    for unit, label in ((86400, "jour"), (3600, "heure"), (60, "minute")):
        if seconds >= unit and seconds % unit == 0:
            count = seconds // unit
            return f"Dans {count} {label}{'s' if count > 1 else ''}"
    return f"Dans {seconds} s"


async def _send(
    bot, guild: discord.Guild, title: str, fields, event: str,
    *, invite: discord.Invite | None = None,
) -> None:
    panel = embeds.canonical_log_embed(title, fields=fields)
    actor = getattr(invite, "inviter", None) if invite is not None else None
    code = str(getattr(invite, "code", "") or "").strip() if invite else ""
    await log_service.send_log(
        bot,
        guild,
        "resources",
        panel,
        event_key=log_service.make_event_key(
            guild.id,
            event,
            # Une invite a un code stable. Webhooks : leur événement ne porte
            # pas d'identifiant unique, on conserve le discriminant historique.
            discriminator=code or time.time_ns(),
        ),
        identity_id=getattr(actor, "id", None),
        identity_name=getattr(actor, "display_name", None) or getattr(actor, "name", None),
        identity_icon=(
            str(actor.display_avatar.url) if getattr(actor, "display_avatar", None) else None
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
                ("Créateur", _actor(invite.inviter), False),
                ("Lien", f"https://discord.gg/{invite.code}", False),
                ("Utilisations max", str(invite.max_uses or "Illimité"), False),
                ("Expiration", _expiration(invite), False),
            ],
            "invite_create",
            invite=invite,
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
            invite=invite,
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