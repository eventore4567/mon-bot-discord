"""UI guards shared by SentriX.

Only +ping is migrated here for the visual test requested by the owner. The command
still exists in cogs.utility, but when its legacy embed reaches Context.send we replace
it with a compact Discord Components V2 LayoutView.
"""

import base64
import io
import re

import discord
from discord.ext import commands


PING_ACCENT = 0x5865F2
PING_BANNER_PATH = "assets/sentrix-ping-information.jpg"
PING_BANNER_FILENAME = "sentrix-ping-information.jpg"


def _is_sentrix_ping_panel(embed: discord.Embed | None) -> bool:
    if embed is None:
        return False

    title = str(embed.title or "").strip().casefold()
    if title in {"pong", "pong !"}:
        return bool(re.search(r"latence\s*:\s*\*\*?\d+\s*ms", str(embed.description or ""), re.IGNORECASE))

    if title != "ping":
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

    match = re.search(r"(\d+)\s*ms", str(embed.description or ""), re.IGNORECASE)
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


def _load_ping_banner_file() -> discord.File:
    """Decode the Base64 asset stored in GitHub into a real JPEG for Discord."""
    with open(PING_BANNER_PATH, "r", encoding="ascii") as asset:
        encoded = "".join(asset.read().split())

    data = base64.b64decode(encoded, validate=True)
    if not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("SentriX ping banner is not a valid JPEG after Base64 decoding")

    return discord.File(io.BytesIO(data), filename=PING_BANNER_FILENAME)


class _SentriXPingLayout(discord.ui.LayoutView):
    def __init__(self, ctx: commands.Context, latency_ms: int, *, with_banner: bool = True):
        super().__init__(timeout=120)

        bot = ctx.bot
        server_count = len(bot.guilds)
        member_count = sum((guild.member_count or 0) for guild in bot.guilds)
        shard_count = int(getattr(bot, "shard_count", None) or 1)
        connection = "Active" if not bot.is_closed() else "Hors ligne"
        state = "Opérationnel" if not bot.is_closed() else "Indisponible"
        quality, quality_bar = _latency_quality(latency_ms)
        measured_at = int(discord.utils.utcnow().timestamp())

        status_row = discord.ui.ActionRow(
            discord.ui.Button(
                label=f"Discord · {latency_ms} ms",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Connexion · {connection}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Serveurs · {server_count}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Membres · {member_count:,}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
            discord.ui.Button(
                label=f"Shards · {shard_count}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            ),
        )

        children: list[discord.ui.Item] = []
        if with_banner:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(
                media=f"attachment://{PING_BANNER_FILENAME}",
                description="SentriX — Information",
            )
            children.append(gallery)

        children.extend(
            [
                discord.ui.TextDisplay(
                    f"## Latence  ·  {latency_ms} ms  ·  {quality}    `{quality_bar}`\n"
                    f"**Connexion** {connection}   •   **État** {state}   •   "
                    f"**Serveurs** {server_count:,}   •   **Membres** {member_count:,}   •   "
                    f"**Shards** {shard_count}"
                ),
                status_row,
                discord.ui.TextDisplay(
                    f"-# SentriX • Mesuré <t:{measured_at}:R>"
                ),
            ]
        )

        self.add_item(discord.ui.Container(*children, accent_colour=PING_ACCENT))


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

            try:
                banner_file = _load_ping_banner_file()
            except (OSError, ValueError):
                kwargs["view"] = _SentriXPingLayout(self, latency_ms, with_banner=False)
                return await _ORIGINAL_CONTEXT_SEND(self, *args, **kwargs)

            kwargs["files"] = [banner_file]
            kwargs["view"] = _SentriXPingLayout(self, latency_ms, with_banner=True)

            try:
                return await _ORIGINAL_CONTEXT_SEND(self, *args, **kwargs)
            except discord.HTTPException:
                try:
                    banner_file.close()
                except Exception:
                    pass
                kwargs.pop("files", None)
                kwargs["view"] = _SentriXPingLayout(self, latency_ms, with_banner=False)
                return await _ORIGINAL_CONTEXT_SEND(self, *args, **kwargs)

        return await _ORIGINAL_CONTEXT_SEND(self, *args, **kwargs)

    _sentrix_context_send._sentrix_ping_components_v2 = True
    _sentrix_context_send._sentrix_original_context_send = _ORIGINAL_CONTEXT_SEND
    commands.Context.send = _sentrix_context_send
