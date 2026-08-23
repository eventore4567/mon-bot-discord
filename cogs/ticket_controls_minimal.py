"""Contrôles de ticket minimaux : seulement « Prendre en charge » et « Fermer ».

Cette couche est volontairement petite et non destructive :
- les handlers historiques restent dans cogs.tickets pour compatibilité/transcripts ;
- les nouvelles vues n'affichent que claim + close, même si une ancienne configuration
  enregistrée active encore add/remove/rename/note/etc. ;
- les anciens boutons retirés sont bloqués côté serveur s'ils existent encore sur un
  message Discord historique ;
- les tickets ouverts sont migrés en arrière-plan après le démarrage pour retirer
  visuellement les anciens composants sans bloquer le boot.
"""
from __future__ import annotations

import asyncio
import logging

import discord

logger = logging.getLogger("bot.ticket-controls-minimal")

_ALLOWED_KEYS = ("claim", "close")
_INSTALLED = False
_MIGRATION_STARTED = False


def _is_ticket_control_message(message: discord.Message) -> bool:
    """Détecte une ancienne/nouvelle vue TicketControlView dans un message du bot."""
    for row in getattr(message, "components", ()) or ():
        for child in getattr(row, "children", ()) or ():
            custom_id = str(getattr(child, "custom_id", "") or "")
            if custom_id.startswith("ticket_ctrl_"):
                return True
    return False


async def _migrate_open_ticket_messages(bot) -> None:
    global _MIGRATION_STARTED
    try:
        await bot.wait_until_ready()
        from . import tickets as tickets_mod

        cog = bot.get_cog("Tickets")
        if cog is None:
            return

        try:
            rows = await bot.db.fetchall(
                "SELECT guild_id, channel_id FROM tickets WHERE status = 'ouvert' ORDER BY id DESC"
            )
        except Exception:
            logger.warning("Migration des boutons de tickets : lecture DB impossible.", exc_info=True)
            return

        updated = 0
        scanned = 0
        for row in rows[:1000]:
            guild = bot.get_guild(int(row["guild_id"]))
            channel = guild.get_channel(int(row["channel_id"])) if guild else None
            if not isinstance(channel, discord.TextChannel):
                continue
            scanned += 1
            try:
                control_message = None
                # Le message d'ouverture est normalement parmi les tout premiers du salon.
                async for message in channel.history(limit=25, oldest_first=True):
                    if bot.user is not None and message.author.id != bot.user.id:
                        continue
                    if _is_ticket_control_message(message):
                        control_message = message
                        break
                if control_message is None:
                    continue
                settings = await tickets_mod.get_button_settings(bot, guild.id)
                await control_message.edit(view=tickets_mod.TicketControlView(settings))
                updated += 1
                # Étale légèrement les edits pour rester doux avec l'API Discord.
                await asyncio.sleep(0.08)
            except (discord.Forbidden, discord.NotFound):
                continue
            except discord.HTTPException:
                logger.debug(
                    "Migration boutons ticket impossible pour channel=%s.",
                    getattr(channel, "id", None),
                    exc_info=True,
                )
            except Exception:
                logger.debug("Erreur pendant la migration d'un ticket ouvert.", exc_info=True)

        logger.info(
            "Tickets : contrôles minimaux appliqués — %s/%s panneau(x) ouvert(s) actualisé(s).",
            updated,
            scanned,
        )
    finally:
        _MIGRATION_STARTED = False


def install(bot, extension_name: str = "") -> None:
    """Installe le mode minimal dès que le Cog Tickets est chargé. Idempotent."""
    global _INSTALLED, _MIGRATION_STARTED

    cog = bot.get_cog("Tickets")
    if cog is None:
        return

    from . import tickets as tickets_mod

    if not _INSTALLED:
        # La source de vérité de toutes les vues créées après ce point ne contient plus
        # que ces deux contrôles. Les anciennes clés restent dans la DB sans être utilisées.
        original_buttons = dict(tickets_mod.STAFF_BUTTONS)
        tickets_mod.STAFF_BUTTONS.clear()
        for key in _ALLOWED_KEYS:
            if key in original_buttons:
                tickets_mod.STAFF_BUTTONS[key] = original_buttons[key]
        tickets_mod.DEFAULT_ENABLED_BUTTONS = set(_ALLOWED_KEYS)

        # Si le menu de configuration des boutons a déjà été construit à l'import, ses
        # options ont été figées par le décorateur. On filtre donc les options de chaque
        # nouvelle instance afin de ne plus proposer les contrôles supprimés.
        view_cls = tickets_mod.ButtonSettingsView
        original_view_init = view_cls.__init__
        if not getattr(original_view_init, "_sentrix_minimal_ticket_controls", False):
            def minimal_settings_init(self, *args, **kwargs):
                original_view_init(self, *args, **kwargs)
                for item in self.children:
                    if isinstance(item, discord.ui.Select):
                        try:
                            item.options[:] = [
                                option for option in item.options
                                if str(getattr(option, "value", "")) in _ALLOWED_KEYS
                            ]
                        except Exception:
                            logger.debug("Impossible de filtrer les options ticket setup.", exc_info=True)

            minimal_settings_init._sentrix_minimal_ticket_controls = True
            view_cls.__init__ = minimal_settings_init

        # Même si un vieux message contient encore un custom_id supprimé, l'action métier
        # correspondante est refusée. Cela ferme le contournement avant même la migration UI.
        tickets_cls = type(cog)
        original_handler = tickets_cls.handle_control_button
        if not getattr(original_handler, "_sentrix_minimal_ticket_controls", False):
            async def minimal_control_handler(self, interaction: discord.Interaction, key: str):
                if str(key) not in _ALLOWED_KEYS:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "Ce contrôle a été retiré. Utilisez uniquement « Prendre en charge » ou « Fermer ».",
                            ephemeral=True,
                        )
                    return None
                return await original_handler(self, interaction, key)

            minimal_control_handler._sentrix_minimal_ticket_controls = True
            tickets_cls.handle_control_button = minimal_control_handler

        _INSTALLED = True
        logger.info("Tickets : seuls les boutons Prendre en charge et Fermer sont désormais autorisés.")

    # Une migration par processus suffit. Elle est asynchrone pour ne jamais ralentir
    # setup_hook/tree.sync ni le démarrage Railway.
    if not _MIGRATION_STARTED:
        try:
            _MIGRATION_STARTED = True
            asyncio.get_running_loop().create_task(
                _migrate_open_ticket_messages(bot),
                name="sentrix-ticket-controls-minimal-migration",
            )
        except RuntimeError:
            _MIGRATION_STARTED = False


__all__ = ["install"]
