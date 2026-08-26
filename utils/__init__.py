"""UI guards shared by SentriX.

Only +ping is migrated here for the visual test requested by the owner. The command
still exists in cogs.utility, but when its legacy embed reaches Context.send we replace
it with a Discord Components V2 LayoutView.
"""

import re

import discord
from discord.ext import commands


# Use a normal public PNG URL for MediaGallery. Attachment references inside
# Components V2 were rendered as "Image introuvable" by the Discord client.
PING_BANNER_URL = (
    "https://raw.githubusercontent.com/eventore4567/mon-bot-discord/"
    "c9a3fc10cad21bff31944c2831d125b55905be18/assets/sentrix-log-header.png"
)
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
        connection = "Active" if bot.is_ready() else "Connexion..."
        state = "Opérationnel" if bot.is_ready() else "Initialisation"
        quality, quality_bar = _latency_quality(latency_ms)
        measured_at = int(discord.utils.utcnow().timestamp())

        gallery = discord.ui.MediaGallery()
        gallery.add_item(
            media=PING_BANNER_URL,
            description="SentriX — Informations générales",
        )

        # Five compact components occupy the complete row and keep the information
        # horizontal instead of letting the text collapse into a vertical block.
        status_row = discord.ui.ActionRow(
            discord.ui.Button(
                label=f"Discord • {latency_ms} ms",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Connexion • {connection}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Serveurs • {server_count}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Membres • {member_count:,}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Shards • {shard_count}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
        )

        container = discord.ui.Container(
            gallery,
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(
                "## Latence\n"
                "-# État en temps réel de la connexion et des services SentriX."
            ),
            discord.ui.TextDisplay(
                f"### Passerelle Discord    **{latency_ms} ms**  •  **{quality}**\n"
                f"`{quality_bar}`"
            ),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(
                "### Informations\n"
                f"**{connection}** connexion   •   **{state}** état   •   "
                f"**{server_count:,}** serveurs   •   **{member_count:,}** membres   •   "
                f"**{shard_count}** shard{'s' if shard_count != 1 else ''}"
            ),
            status_row,
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(
                f"-# SentriX • Mesuré <t:{measured_at}:R>"
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
