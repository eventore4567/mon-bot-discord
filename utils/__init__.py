"""Petits garde-fous UI partagés par SentriX.

Le wrapper ci-dessous ne modifie que le panneau de la commande +ping. Discord place
forcément ``Embed.set_image`` après le contenu d'un embed classique ; pour obtenir le
header demandé au-dessus du panneau, +ping est rendu avec deux embeds dans le même
message : un embed image seul, puis l'embed d'informations.
"""

from pathlib import Path

import discord
from discord.ext import commands


_PING_BANNER_NAME = "sentrix-ping-header-v2.webp"
_PING_BANNER_PATH = Path(__file__).resolve().parents[1] / "assets" / _PING_BANNER_NAME


def _is_sentrix_ping_panel(embed: discord.Embed | None) -> bool:
    if embed is None or str(embed.title or "").strip().casefold() != "ping":
        return False

    field_names = {str(field.name or "").strip().casefold() for field in embed.fields}
    required = {"passerelle discord", "connexion", "état"}
    if not required.issubset(field_names):
        return False

    image_url = str(getattr(embed.image, "url", "") or "")
    return "sentrix-ping-header" in image_url


_ORIGINAL_CONTEXT_SEND = getattr(
    commands.Context.send,
    "_sentrix_original_context_send",
    commands.Context.send,
)


if not getattr(commands.Context.send, "_sentrix_ping_banner_guard", False):
    async def _sentrix_context_send(self, *args, **kwargs):
        embed = kwargs.get("embed")

        if (
            _is_sentrix_ping_panel(embed)
            and kwargs.get("embeds") is None
            and kwargs.get("file") is None
            and kwargs.get("files") is None
            and _PING_BANNER_PATH.is_file()
        ):
            # Ne touche pas à l'objet original : il peut encore être utilisé par le
            # gestionnaire hybrid/slash de discord.py après l'appel.
            content_embed = discord.Embed.from_dict(embed.to_dict())
            content_embed.set_image(url=None)

            # L'image est volontairement dans le PREMIER embed. Discord respecte
            # l'ordre de la liste d'embeds, donc le header apparaît réellement en haut.
            banner_embed = discord.Embed(colour=content_embed.colour)
            banner_embed.set_image(url=f"attachment://{_PING_BANNER_NAME}")

            kwargs.pop("embed", None)
            kwargs["embeds"] = [banner_embed, content_embed]
            kwargs["file"] = discord.File(
                _PING_BANNER_PATH,
                filename=_PING_BANNER_NAME,
            )

        return await _ORIGINAL_CONTEXT_SEND(self, *args, **kwargs)

    _sentrix_context_send._sentrix_ping_banner_guard = True
    _sentrix_context_send._sentrix_original_context_send = _ORIGINAL_CONTEXT_SEND
    commands.Context.send = _sentrix_context_send
