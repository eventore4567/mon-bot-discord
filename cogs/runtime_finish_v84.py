"""Finalisation ciblée V84 : tickets et logs Setup.

Cette couche ne remplace aucun moteur métier. Elle sécurise les étapes non critiques qui
s'exécutent après une action réussie.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.runtime-finish-v84")


def _walk_components(items: Iterable[Any]):
    for item in items:
        yield item
        children = getattr(item, "children", None)
        if children:
            yield from _walk_components(children)


async def _persist_log_route(bot: commands.Bot, guild_id: int, log_type: str, channel_id: int) -> None:
    """Passe par le point d'écriture unique : plus de SQL direct, plus de miroir legacy."""
    category, _emoji, _kind = log_service.resolve(log_type)
    await log_service.set_log_config(
        bot, int(guild_id), category, channel_id=int(channel_id), enabled=True
    )


def _install_ticket_log_resilience() -> None:
    from . import tickets as ticket_runtime

    current = ticket_runtime.Tickets.log_action
    if getattr(current, "_sentrix_v84_best_effort", False):
        return

    async def safe_log_action(self, guild, embed, log_channel_id=None):
        try:
            return await current(self, guild, embed, log_channel_id)
        except Exception:
            # Un ticket déjà créé/fermé ne doit jamais devenir une « Action impossible »
            # uniquement parce que son journal est temporairement indisponible.
            logger.exception(
                "Journal ticket indisponible après action réussie (guild=%s, channel=%s)",
                getattr(guild, "id", None),
                log_channel_id,
            )
            return None

    safe_log_action._sentrix_v84_best_effort = True
    safe_log_action._sentrix_previous = current
    ticket_runtime.Tickets.log_action = safe_log_action


def _install_setup_log_channel_resilience() -> None:
    from . import setup_experience_v74 as v74

    cls = v74.SentriXSetupV74
    current = cls._build_page
    if getattr(current, "_sentrix_v84_log_channel_save", False):
        return

    async def build_page_v84(self, page: str):
        result = await current(self, page)
        if page != "logs":
            return result

        selected_type = getattr(self.backend, "selected_log", None)
        if not selected_type:
            return result

        for item in _walk_components(getattr(self, "children", ())):
            if not isinstance(item, discord.ui.ChannelSelect):
                continue
            placeholder = str(getattr(item, "placeholder", "") or "")
            if not placeholder.startswith("2. Choisir le salon pour"):
                continue

            select = item

            async def choose_channel_v84(interaction: discord.Interaction, *, _select=select):
                log_type = getattr(self.backend, "selected_log", None) or selected_type
                if not interaction.response.is_done():
                    await interaction.response.defer()
                channel = _select.values[0] if _select.values else None
                channel_id = int(channel.id) if channel is not None else None

                # La sauvegarde ne dépend pas d'un audit/refresh et ne rejette pas un salon
                # valide à cause d'un cache Discord incomplet. L'état des permissions reste
                # affiché ensuite par validate_channel() sur la page Logs.
                try:
                    if channel_id is None:
                        await log_service.set_log_channel(self.bot, self.guild.id, log_type, None)
                    else:
                        await _persist_log_route(self.bot, self.guild.id, log_type, channel_id)
                except Exception as exc:
                    logger.exception(
                        "Échec réel de sauvegarde salon logs guild=%s type=%s channel=%s",
                        self.guild.id,
                        log_type,
                        channel_id,
                    )
                    detail = str(exc).strip() or type(exc).__name__
                    try:
                        await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(f"Le salon n'a pas pu être enregistré en base. Détail : `{detail[:180]}`")), ephemere=True)
                    except discord.HTTPException:
                        pass
                    return

                try:
                    await self.backend.audit(interaction.user.id, f"log:{log_type}", channel_id)
                except Exception:
                    logger.debug("Audit log channel V84 indisponible", exc_info=True)

                try:
                    await self.refresh(interaction)
                except Exception:
                    # Important : la DB est déjà sauvegardée. On ne ment plus avec
                    # « Salon non enregistré » lorsque seul le rendu du panneau échoue.
                    logger.exception(
                        "Salon log sauvegardé mais refresh Setup impossible guild=%s type=%s",
                        self.guild.id,
                        log_type,
                    )
                    try:
                        if channel is None:
                            text = "Le salon de cette catégorie de logs a bien été désactivé."
                        else:
                            text = f"Salon enregistré : {channel.mention}. Le panneau sera actualisé au prochain rafraîchissement."
                        await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success(text)), ephemere=True)
                    except discord.HTTPException:
                        pass

            select.callback = choose_channel_v84
            break
        return result

    build_page_v84._sentrix_v84_log_channel_save = True
    build_page_v84._sentrix_previous = current
    cls._build_page = build_page_v84


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v84", False):
        return
    _install_ticket_log_resilience()
    _install_setup_log_channel_resilience()
    bot._sentrix_runtime_finish_v84 = True
    logger.info("Runtime Finish V84 actif : tickets et logs Setup.")


__all__ = ["install"]
