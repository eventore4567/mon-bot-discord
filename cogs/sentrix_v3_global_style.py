"""SentriX V3.2 — finition visuelle globale non destructive.

Cette couche se branche sur la fabrique premium existante au lieu de réécrire chaque
commande. Elle conserve la logique métier, les couleurs de catégories et les embeds
spécialisés, puis harmonise l'en-tête et le pied de page avec l'identité SentriX.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.sentrix-v3-global-style")
_INSTALLED = False


def _asset_url(bot_user: Any) -> str | None:
    avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)
    return str(avatar) if avatar else None


def _category_label(category: str) -> str:
    return str(premium_style.CATEGORY_NAMES.get(category, "SentriX"))


def _refine_embed(
    embed: discord.Embed,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
    category: str | None = None,
    kind: str | None = None,
    log_type: str | None = None,
) -> discord.Embed:
    del requester
    resolved_category = premium_style.infer_category(command=command, embed=embed, hint=category)
    resolved_kind = kind or premium_style.infer_kind(embed)

    # Les logs possèdent déjà leur propre identité Secure Audit : on ne touche pas à leur header.
    is_log = bool(log_type) or resolved_category == "logs"
    if not is_log:
        author_name = getattr(getattr(embed, "author", None), "name", None)
        if not author_name:
            label = _category_label(resolved_category)
            icon = _asset_url(bot_user)
            if icon:
                embed.set_author(name=f"SentriX • {label}", icon_url=icon)
            else:
                embed.set_author(name=f"SentriX • {label}")

    # Les états courts ont une couleur immédiatement identifiable ; les panneaux métier
    # conservent la couleur de leur catégorie.
    state_colours = {
        "success": premium_style.COLORS["success"],
        "warning": premium_style.COLORS["warning"],
        "danger": premium_style.COLORS["danger"],
    }
    if resolved_kind in state_colours:
        embed.colour = discord.Colour(state_colours[resolved_kind])
    elif resolved_category in premium_style.COLORS:
        embed.colour = discord.Colour(premium_style.COLORS[resolved_category])

    footer_text = getattr(getattr(embed, "footer", None), "text", None)
    generic_footer = not footer_text or str(footer_text).strip().casefold() in {
        "sentrix",
        "sentrix • rapide, propre, sécurisé",
        "sentrix • rapide, propre, securise",
    }
    if generic_footer:
        parts = ["SentriX"]
        if resolved_category not in {"brand", "utility"}:
            parts.append(_category_label(resolved_category))
        if guild is not None:
            parts.append(premium_style.clip(getattr(guild, "name", "Serveur"), 45))
        embed.set_footer(text=" • ".join(parts))

    return embed


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    original = premium_style.style_embed

    def styled_v32(embed: discord.Embed, *args, **kwargs):
        result = original(embed, *args, **kwargs)
        if not isinstance(result, discord.Embed):
            return result
        return _refine_embed(
            result,
            command=kwargs.get("command"),
            guild=kwargs.get("guild"),
            requester=kwargs.get("requester"),
            bot_user=kwargs.get("bot_user"),
            category=kwargs.get("category"),
            kind=kwargs.get("kind"),
            log_type=kwargs.get("log_type"),
        )

    premium_style.style_embed = styled_v32
    _INSTALLED = True
    logger.info("SentriX V3.2 : finition visuelle globale premium active.")


__all__ = ["install"]
