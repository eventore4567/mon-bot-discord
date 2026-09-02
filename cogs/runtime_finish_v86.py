"""V86 — branchement final de V84/V85 avant l'installation du Setup V75."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from . import runtime_finish_v84 as v84
from . import runtime_finish_v85 as v85
from . import setup_security_choice_v75 as v75

logger = logging.getLogger("bot.runtime-finish-v86")


def _patch_v75_builder() -> None:
    current = v75._build_page_v75
    if getattr(current, "_sentrix_v86_log_save", False):
        return

    async def build_page_v86(self, page: str):
        if page != "logs":
            previous = getattr(build_page_v86, "_sentrix_previous")
            return await previous(self, page)

        result = await v75._build_logs_v75(self)
        selected_type = getattr(self.backend, "selected_log", None)
        if not selected_type:
            return result

        for item in v84._walk_components(getattr(self, "children", ())):
            if not isinstance(item, discord.ui.ChannelSelect):
                continue
            placeholder = str(getattr(item, "placeholder", "") or "")
            if not placeholder.startswith("2. Choisir le salon pour"):
                continue

            select = item

            async def choose_channel_v86(interaction: discord.Interaction, *, _select=select):
                log_type = getattr(self.backend, "selected_log", None) or selected_type
                if not interaction.response.is_done():
                    await interaction.response.defer()

                channel = _select.values[0] if _select.values else None
                channel_id = int(channel.id) if channel is not None else None

                # L'enregistrement est la seule étape critique. Audit et rendu ne peuvent
                # plus transformer une sauvegarde réussie en « Salon non enregistré ».
                try:
                    if channel_id is None:
                        from utils import log_service
                        await log_service.set_log_channel(self.bot, self.guild.id, log_type, None)
                    else:
                        await v84._persist_log_route(self.bot, self.guild.id, log_type, channel_id)
                except Exception as exc:
                    logger.exception(
                        "Échec réel sauvegarde log V86 guild=%s type=%s channel=%s",
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
                    logger.debug("Audit log V86 indisponible", exc_info=True)

                try:
                    await self.refresh(interaction)
                except Exception:
                    logger.exception(
                        "Log sauvegardé mais refresh Setup V86 impossible guild=%s type=%s",
                        self.guild.id,
                        log_type,
                    )
                    try:
                        if channel is None:
                            text = "Cette catégorie de logs a bien été désactivée."
                        else:
                            text = f"Salon enregistré : {channel.mention}."
                        await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success(text)), ephemere=True)
                    except discord.HTTPException:
                        pass

            select.callback = choose_channel_v86
            break
        return result

    build_page_v86._sentrix_v86_log_save = True
    v75._build_page_v75 = build_page_v86


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v86", False):
        return
    _patch_v75_builder()
    v85.install(bot)
    bot._sentrix_runtime_finish_v86 = True
    logger.info("Runtime Finish V86 préparé : ticket, logs Setup et +create manox.")


__all__ = ["install"]
