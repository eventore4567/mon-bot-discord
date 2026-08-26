"""UI guards shared by SentriX.

Only +ping is migrated here for the visual test requested by the owner. The command
still exists in cogs.utility, but when its legacy embed reaches Context.send we replace
it with a compact Discord Components V2 LayoutView.
"""

import re

import discord
from discord.ext import commands


PING_ACCENT = 0x5865F2


def _is_sentrix_ping_panel(embed: discord.Embed | None) -> bool:
    if embed is None or str(embed.title or "").strip().casefold() != "ping":
        return False

    field_names = {str(field.name or "").strip().casefold() for field in embed.fields}
    return {"passerelle discord", "connexion", "état"}.issubset(field_names)


def _latency_from_embed(embed: discord.Embed, fallback: int) -> int:
    for field in embed.fields:
        if str(field.name or "").strip().casefold() != "passerelle discord":
            continue
        match = re.search(r"(\d+)", str(field.value or ""))
        if match:
            return max(0, int(match.group(1)))
    return max(0, fallback)


def _latency_quality(latency_ms: int) -> tuple[str, str]:
    if latency_ms <= 80:
        return "Excellente", "▰▰▰▰▰▰▰▰▰▰"
    if latency_ms <= 140:
        return "Très bonne", "▰▰▰▰▰▰▰▰▰▱"
    if latency_ms <= 220:
        return "Correcte", "▰▰▰▰▰▰▰▱▱▱"
    return "Dégradée", "▰▰▰▰▱▱▱▱▱▱"


class _SentriXPingLayout(discord.ui.LayoutView):
    def __init__(self, ctx: commands.Context, latency_ms: int):
        super().__init__(timeout=120)

        bot = ctx.bot
        server_count = len(bot.guilds)
        member_count = sum((guild.member_count or 0) for guild in bot.guilds)
        shard_count = int(getattr(bot, "shard_count", None) or 1)
        connection = "Active" if not bot.is_closed() else "Hors ligne"
        state = "Opérationnel" if not bot.is_closed() else "Indisponible"
        quality, quality_bar = _latency_quality(latency_ms)
        measured_at = int(discord.utils.utcnow().timestamp())

        # Five deliberately short buttons keep the card wide on desktop without
        # adding vertical height. There is intentionally no MediaGallery here:
        # Discord rendered a failed media placeholder that made +ping enormous.
        status_row = discord.ui.ActionRow(
            discord.ui.Button(
                label=f"Ping {latency_ms} ms",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=connection,
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"{server_count} srv",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"{member_count:,} membres",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"{shard_count} shard{'s' if shard_count != 1 else ''}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
        )

        container = discord.ui.Container(
            discord.ui.TextDisplay(
                "-# SENTRIX • ÉTAT DES SERVICES\n"
                f"## Latence  ·  {latency_ms} ms  ·  {quality}\n"
                f"`{quality_bar}`"
            ),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(
                f"**Connexion** {connection}   •   **État** {state}   •   "
                f"**Serveurs** {server_count:,}   •   **Membres** {member_count:,}   •   "
                f"**Shards** {shard_count}"
            ),
            status_row,
            discord.ui.TextDisplay(
                f"-# Mesuré <t:{measured_at}:R> • SentriX"
            ),
            accent_colour=PING_ACCENT,
        )
        self.add_item(container)


_ORIGINAL_CONTEXT_SEND = getattr(
    commands.Context.send,
    "_sentrix_original_context_send",
    commands.Context.send,
)


if not getattr(commands.Context.send, "_sentrix_ping_components_v2", False):
    async def _sentrix_context_send(self, *args, **kwargs):
        embed = kwargs.get("embed")

        if _is_sentrix_ping_panel(embed) and kwargs.get("view") is None:
            latency_ms = _latency_from_embed(
                embed,
                round(self.bot.latency * 1000),
            )

            kwargs.pop("embed", None)
            kwargs.pop("embeds", None)
            kwargs.pop("file", None)
            kwargs.pop("files", None)
            kwargs["view"] = _SentriXPingLayout(self, latency_ms)

        return await _ORIGINAL_CONTEXT_SEND(self, *args, **kwargs)

    _sentrix_context_send._sentrix_ping_components_v2 = True
    _sentrix_context_send._sentrix_original_context_send = _ORIGINAL_CONTEXT_SEND
    commands.Context.send = _sentrix_context_send
