"""V89 — correctif final Logs Setup.

- branche les callbacks sur la CLASSE réellement utilisée par le Setup Components V2 ;
- une sauvegarde de salon de logs réussie ne peut plus devenir une fausse erreur si le
  refresh/audit échoue ensuite.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils import sentrix_panels as panels
from . import runtime_finish_v86 as v86
from . import setup_experience_v74 as v74

logger = logging.getLogger("bot.runtime-finish-v89")

def _iter_components(items):
    for item in items:
        yield item
        children = getattr(item, "children", None)
        if children:
            yield from _iter_components(children)


async def _best_effort_refresh(view, interaction: discord.Interaction) -> bool:
    try:
        await view.refresh(interaction)
        return True
    except Exception:
        logger.exception("Refresh Setup post-sauvegarde impossible guild=%s", view.guild.id)
        return False


def _patch_setup_logs_final() -> None:
    """Patche la classe finale, pas seulement une variable du module V75/V86."""
    cls = v74.SentriXSetupV74
    current = cls._build_page
    if getattr(current, "_sentrix_v89_logs", False):
        return

    async def build_page_v89(self, page: str):
        result = await current(self, page)
        if page != "logs":
            return result

        for item in _iter_components(getattr(self, "children", ())):
            placeholder = str(getattr(item, "placeholder", "") or "")

            if isinstance(item, discord.ui.Select) and placeholder.startswith("1. Choisir la catégorie"):
                category_select = item

                async def choose_category(interaction: discord.Interaction, *, _select=category_select):
                    if not interaction.response.is_done():
                        await interaction.response.defer()
                    if _select.values:
                        self.backend.selected_log = str(_select.values[0])
                    if not await _best_effort_refresh(self, interaction):
                        try:
                            await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success("Catégorie sélectionnée. Utilisez **Actualiser** si le panneau ne s'est pas redessiné.")), ephemere=True)
                        except discord.HTTPException:
                            pass

                category_select.callback = choose_category
                continue

            if isinstance(item, discord.ui.ChannelSelect) and placeholder.startswith("2. Choisir le salon pour"):
                channel_select = item

                async def choose_channel(interaction: discord.Interaction, *, _select=channel_select):
                    log_type = str(getattr(self.backend, "selected_log", None) or "moderation")
                    if not interaction.response.is_done():
                        await interaction.response.defer()

                    chosen = _select.values[0] if _select.values else None
                    channel_id = int(chosen.id) if chosen is not None else None

                    try:
                        await log_service.set_log_channel(
                            self.bot,
                            self.guild.id,
                            log_type,
                            channel_id,
                        )
                        await log_service.set_log_enabled(
                            self.bot,
                            self.guild.id,
                            log_type,
                            channel_id is not None,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Sauvegarde réelle log impossible guild=%s type=%s channel=%s",
                            self.guild.id,
                            log_type,
                            channel_id,
                        )
                        try:
                            await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(f'Erreur de sauvegarde réelle : `{type(exc).__name__}: {str(exc)[:160]}`')), ephemere=True)
                        except discord.HTTPException:
                            pass
                        return

                    # Tout ce qui suit est non critique : la route est DÉJÀ sauvegardée.
                    try:
                        await self.backend.audit(
                            interaction.user.id,
                            f"log:{log_type}",
                            channel_id,
                        )
                    except Exception:
                        logger.debug("Audit choix log V89 ignoré", exc_info=True)

                    refreshed = await _best_effort_refresh(self, interaction)
                    if not refreshed:
                        try:
                            text = (
                                f"Salon enregistré : <#{channel_id}>."
                                if channel_id
                                else "Cette catégorie de logs est maintenant désactivée."
                            )
                            await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success(text)), ephemere=True)
                        except discord.HTTPException:
                            pass

                channel_select.callback = choose_channel
                continue

            if isinstance(item, discord.ui.Button):
                label = str(getattr(item, "label", "") or "")
                if label not in {"Activer cette catégorie", "Désactiver cette catégorie"}:
                    continue
                toggle = item

                async def toggle_category(interaction: discord.Interaction):
                    log_type = str(getattr(self.backend, "selected_log", None) or "moderation")
                    if not interaction.response.is_done():
                        await interaction.response.defer()
                    try:
                        setting = await log_service.get_log_setting(self.bot, self.guild.id, log_type)
                        new_enabled = not bool(setting.get("enabled"))
                        if new_enabled and not setting.get("dedicated_channel_id"):
                            await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.warning("Choisissez d'abord **le salon exact** de cette catégorie avec le deuxième menu.")), ephemere=True)
                            return
                        await log_service.set_log_enabled(
                            self.bot,
                            self.guild.id,
                            log_type,
                            new_enabled,
                        )
                    except Exception as exc:
                        logger.exception("Toggle log V89 impossible guild=%s type=%s", self.guild.id, log_type)
                        try:
                            await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(f'Impossible de modifier cette catégorie : `{type(exc).__name__}: {str(exc)[:150]}`')), ephemere=True)
                        except discord.HTTPException:
                            pass
                        return

                    try:
                        await self.backend.audit(
                            interaction.user.id,
                            f"log:{log_type}",
                            "enabled" if new_enabled else "disabled",
                        )
                    except Exception:
                        logger.warning("Étape non critique ignorée dans toggle_category", exc_info=True)
                    if not await _best_effort_refresh(self, interaction):
                        try:
                            await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success('Catégorie activée.' if new_enabled else 'Catégorie désactivée.')), ephemere=True)
                        except discord.HTTPException:
                            pass

                toggle.callback = toggle_category

        return result

    build_page_v89._sentrix_v89_logs = True
    build_page_v89._sentrix_previous = current
    cls._build_page = build_page_v89
    logger.info("Setup Logs V89 actif : callbacks finaux branchés sur la classe réelle.")


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v89", False):
        return
    v86.install(bot)
    _patch_setup_logs_final()
    bot._sentrix_runtime_finish_v89 = True
    logger.info("Runtime Finish V89 actif : Logs Setup réparés.")


__all__ = ["install"]
