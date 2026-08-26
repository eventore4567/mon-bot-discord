"""Notification privée au créateur quand SentriX n'est plus présent sur un serveur."""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from .owner_log_rebuild import _send_creator_dm
from utils import embeds

logger = logging.getLogger("bot.guild-departure-notify")


def _departure_embed(guild: discord.Guild) -> discord.Embed:
    owner_text = str(guild.owner) if guild.owner else "Non présent dans le cache"
    timestamp = int(time.time())

    embed = embeds.warning(
        "SentriX n'est plus présent sur ce serveur.",
        title="SentriX retiré d’un serveur",
    )
    embed.add_field(name="Serveur", value=f"{guild.name}\n`{guild.id}`", inline=False)
    embed.add_field(
        name="Propriétaire",
        value=f"{owner_text}\n`{guild.owner_id}`",
        inline=True,
    )
    embed.add_field(name="Membres", value=str(guild.member_count or 0), inline=True)
    embed.add_field(
        name="Retrait détecté",
        value=f"<t:{timestamp}:F>\n<t:{timestamp}:R>",
        inline=False,
    )
    embed.add_field(
        name="Raison",
        value=(
            "Discord ne transmet pas toujours la raison exacte à l’événement de retrait "
            "(bot expulsé, serveur supprimé, etc.)."
        ),
        inline=False,
    )
    embed.set_footer(text="SentriX • Suivi des serveurs")
    return embed


class GuildDepartureNotify(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent: dict[int, float] = {}

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        now = time.monotonic()
        last = self._recent.get(guild.id, 0.0)
        if now - last < 30.0:
            return
        self._recent[guild.id] = now

        try:
            delivered = await _send_creator_dm(self.bot, embed=_departure_embed(guild))
            if delivered:
                logger.info(
                    "Notification retrait envoyée au créateur guild=%s name=%s",
                    guild.id,
                    guild.name,
                )
            else:
                logger.warning(
                    "Notification retrait non délivrée guild=%s : aucun créateur joignable",
                    guild.id,
                )
        except Exception:
            logger.exception("Notification retrait impossible guild=%s", guild.id)


async def install(bot: commands.Bot) -> None:
    existing = bot.get_cog("GuildDepartureNotify")
    if existing is not None:
        await bot.remove_cog("GuildDepartureNotify")
    await bot.add_cog(GuildDepartureNotify(bot))

    # Le diagnostic live a prouvé que l'ancienne chaîne send_log plante en TypeError
    # malgré des routes valides. V5.2 devient l'unique transport final avant le probe.
    from . import log_transport_v52
    log_transport_v52.install(bot)

    from . import log_runtime_diagnostic
    await log_runtime_diagnostic.install(bot)


async def setup(bot: commands.Bot) -> None:
    await install(bot)
