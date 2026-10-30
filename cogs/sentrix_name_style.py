"""Style de nom SentriX : dégradé violet et bleu, par serveur.

Les champs Discord display_name_* sont non documentés dans la surface officielle
Modify Current Member. Un refus n'affecte pas la connexion du bot ni les commandes.
Aucune modification du pseudo et aucun token écrit dans les logs.
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands
from discord.http import Route

logger = logging.getLogger("bot.name-style")

# Identité SentriX, cohérente avec les couleurs du profil et de la bannière.
FONT_DEFAULT = 11
EFFECT_GRADIENT = 2
COLORS = (0x7C3AED, 0x2563EB)  # violet -> bleu
REQUEST_DELAY_SECONDS = 1.5


def style_payload() -> dict[str, int | list[int]]:
    return {
        "display_name_font_id": FONT_DEFAULT,
        "display_name_effect_id": EFFECT_GRADIENT,
        "display_name_colors": list(COLORS),
    }


class SentriXNameStyle:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.applied_guilds: set[int] = set()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._unsupported = False

    async def apply(self, guild: discord.Guild) -> None:
        if self._unsupported or guild.id in self.applied_guilds:
            return
        async with self._lock:
            if self._unsupported or guild.id in self.applied_guilds:
                return
            try:
                # Utilise HTTPClient de discord.py pour les limites de débit
                # et l'authentification Bot déjà gérées par la librairie.
                await self.bot.http.request(
                    Route("PATCH", "/guilds/{guild_id}/members/@me", guild_id=guild.id),
                    json=style_payload(),
                )
            except discord.HTTPException as error:
                status = getattr(error, "status", None)
                # Si Discord retire le support des champs, on évite de
                # répéter la même requête sur tous les serveurs.
                if status in {400, 401}:
                    self._unsupported = True
                logger.warning(
                    "Style du nom SentriX refusé pour le serveur %s (HTTP %s).",
                    guild.id, status,
                )
            except Exception:
                logger.exception("Mise en forme du nom SentriX impossible pour %s.", guild.id)
            else:
                self.applied_guilds.add(guild.id)
                logger.info("Style de nom violet/bleu appliqué à SentriX dans %s.", guild.id)

    async def _apply_to_existing(self) -> None:
        for guild in list(self.bot.guilds):
            if self._unsupported:
                break
            await self.apply(guild)
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

    async def on_ready(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._apply_to_existing())

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.apply(guild)


async def setup(bot: commands.Bot) -> None:
    enabled = os.getenv("SENTRIX_NAME_STYLE_AUTO", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not enabled:
        logger.info("Style de nom SentriX désactivé via SENTRIX_NAME_STYLE_AUTO.")
        return
    state = SentriXNameStyle(bot)
    bot.add_listener(state.on_ready, "on_ready")
    bot.add_listener(state.on_guild_join, "on_guild_join")
    bot._sentrix_name_style = state
