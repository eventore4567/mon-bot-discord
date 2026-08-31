"""Render ``+me`` as one compact Components V2 panel.

``+me`` reuses the classic /stats embed + StatsView. The generic top-banner compatibility
layer therefore had to send two embeds: an image-only banner embed followed by the stats
embed. This module intercepts only the final ``+me`` send and turns that payload into one
Components V2 ``Container`` containing the banner, profile content and navigation buttons.

/stats and every other command keep their existing rendering path.
"""
from __future__ import annotations

import time
from typing import Any

import discord
from discord.ext import commands

from . import command_visuals as visuals

_INSTALLED = False
_PREVIOUS_CONTEXT_SEND = None


def _root_command_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _clean(value: object, *, limit: int = 1000) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


def _field_blocks(embed: discord.Embed) -> list[str]:
    """Keep inline stats compact instead of flattening every field vertically."""
    blocks: list[str] = []
    inline_row: list[str] = []

    def flush_inline() -> None:
        nonlocal inline_row
        if inline_row:
            blocks.append("  •  ".join(inline_row))
            inline_row = []

    for field in embed.fields:
        name = _clean(field.name, limit=80)
        value = _clean(field.value, limit=800)
        if not name or not value:
            continue

        compact = bool(field.inline) and "\n" not in value and len(name) <= 28 and len(value) <= 80
        if compact:
            inline_row.append(f"**{name}** {value}")
            if len(inline_row) >= 3:
                flush_inline()
        else:
            flush_inline()
            blocks.append(f"**{name}**\n{value}")

    flush_inline()
    return blocks


def _small_separator() -> discord.ui.Separator:
    spacing_enum = getattr(discord, "SeparatorSpacing", None)
    small = getattr(spacing_enum, "small", None) if spacing_enum is not None else None
    if small is not None:
        try:
            return discord.ui.Separator(spacing=small)
        except (TypeError, ValueError):
            pass
    return discord.ui.Separator()


class MeSinglePanel(discord.ui.LayoutView):
    """One visual block for +me, including the four navigation buttons."""

    def __init__(self, source_view: discord.ui.View, embed: discord.Embed, page: str = "stats") -> None:
        super().__init__(timeout=getattr(source_view, "timeout", 120) or 120)
        self.source_view = source_view
        self.cog = getattr(source_view, "cog", None)
        self.guild = getattr(source_view, "guild", None)
        self.member = getattr(source_view, "member", None)
        self.author_id = int(getattr(source_view, "author_id", 0) or 0)
        self.page = page
        self.message: discord.Message | None = None
        self._rebuild(embed)

    def _button(self, label: str, page: str) -> discord.ui.Button:
        button = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=f"sx:me:{page}",
            disabled=self.page == page,
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self._switch_page(interaction, page)

        button.callback = callback
        return button

    def _rebuild(self, embed: discord.Embed) -> None:
        self.clear_items()

        colour_value = int(getattr(getattr(embed, "colour", None), "value", 0) or 0x3B82F6)
        container = discord.ui.Container(accent_colour=discord.Colour(colour_value))

        # The banner is part of the SAME container, so +me is no longer two embeds.
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=visuals.banner_url("info"))
        container.add_item(gallery)

        title = _clean(embed.title or "Profil", limit=180)
        description = _clean(embed.description, limit=1000)
        header_text = f"## {title}"
        if description:
            header_text += f"\n{description}"

        thumbnail = str(getattr(getattr(embed, "thumbnail", None), "url", None) or "")
        if thumbnail:
            try:
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(header_text),
                        accessory=discord.ui.Thumbnail(thumbnail),
                    )
                )
            except Exception:
                container.add_item(discord.ui.TextDisplay(header_text))
        else:
            container.add_item(discord.ui.TextDisplay(header_text))

        blocks = _field_blocks(embed)
        if blocks:
            container.add_item(_small_separator())
            container.add_item(discord.ui.TextDisplay("\n\n".join(blocks)[:3900]))

        footer = _clean(getattr(getattr(embed, "footer", None), "text", None), limit=220) or "SentriX"
        timestamp = getattr(embed, "timestamp", None)
        if timestamp is not None:
            try:
                unix = int(timestamp.timestamp())
                footer = f"{footer} • <t:{unix}:t>"
            except Exception:
                pass
        container.add_item(_small_separator())
        container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

        row = discord.ui.ActionRow()
        row.add_item(self._button("Statistiques", "stats"))
        row.add_item(self._button("Niveau", "level"))
        row.add_item(self._button("Économie", "eco"))
        row.add_item(self._button("Classement", "rank"))
        container.add_item(row)

        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True

        is_staff = False
        if isinstance(interaction.user, discord.Member):
            is_staff = interaction.user.guild_permissions.administrator
            if not is_staff and getattr(interaction.client, "db", None) is not None and self.guild is not None:
                try:
                    is_staff = await interaction.client.db.is_bot_manager(self.guild.id, interaction.user.id)
                except Exception:
                    is_staff = False

        try:
            from config import OWNER_IDS
            if interaction.user.id in OWNER_IDS:
                is_staff = True
        except Exception:
            pass

        if is_staff:
            return True
        await interaction.response.send_message(
            "○ Ce menu n'est pas pour vous — utilisez `+me` de votre côté.",
            ephemeral=True,
        )
        return False

    async def _switch_page(self, interaction: discord.Interaction, page: str) -> None:
        if self.cog is None or self.guild is None or self.member is None:
            return await interaction.response.send_message("Impossible d'actualiser ce panneau.", ephemeral=True)

        try:
            if page == "level":
                embed = await self.cog.build_level_embed(self.guild, self.member)
            elif page == "eco":
                embed = await self.cog.build_economy_embed(self.guild, self.member)
            elif page == "rank":
                embed = await self.cog.build_ranks_embed(self.guild, self.member)
            else:
                page = "stats"
                embed = await self.cog.build_stats_embed(self.guild, self.member)
        except Exception:
            return await interaction.response.send_message("Une erreur est survenue pendant l'actualisation.", ephemeral=True)

        self.page = page
        self._rebuild(embed)
        await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        # Rebuild the visible page with disabled controls is unnecessary: simply disable
        # every button already present in the ActionRow and edit the same single panel.
        for item in self.walk_children():
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def _single_panel_me_send(self: commands.Context, *args: Any, **kwargs: Any):
    assert _PREVIOUS_CONTEXT_SEND is not None

    if _root_command_name(self) != "me":
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    content = args[0] if args else kwargs.get("content")
    embed = kwargs.get("embed")
    source_view = kwargs.get("view")

    # Only transform the normal +me stats payload. Errors, plain text and unrelated
    # payloads keep the existing renderer.
    if content is not None or not isinstance(embed, discord.Embed) or source_view is None:
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)
    if isinstance(source_view, discord.ui.LayoutView):
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)
    if not all(hasattr(source_view, attr) for attr in ("cog", "guild", "member", "author_id")):
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    raw_send = getattr(visuals, "_ORIGINAL_CONTEXT_SEND", None)
    if raw_send is None:
        return await _PREVIOUS_CONTEXT_SEND(self, *args, **kwargs)

    layout = MeSinglePanel(source_view, embed, page="stats")
    output = dict(kwargs)
    output.pop("embed", None)
    output.pop("embeds", None)
    output.pop("content", None)
    output["view"] = layout

    message = await raw_send(self, None, **output)
    layout.message = message
    try:
        source_view.message = message
    except Exception:
        pass
    return message


def install_me_single_panel() -> None:
    global _INSTALLED
    global _PREVIOUS_CONTEXT_SEND

    if _INSTALLED:
        return
    _INSTALLED = True

    current_send = commands.Context.send
    if getattr(current_send, "_sentrix_me_single_panel", False):
        _PREVIOUS_CONTEXT_SEND = getattr(current_send, "_sentrix_previous_context_send", current_send)
        return

    _PREVIOUS_CONTEXT_SEND = current_send
    _single_panel_me_send._sentrix_me_single_panel = True
    _single_panel_me_send._sentrix_previous_context_send = current_send
    commands.Context.send = _single_panel_me_send


__all__ = ["install_me_single_panel"]
