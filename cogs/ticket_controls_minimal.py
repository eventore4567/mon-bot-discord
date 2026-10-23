"""Compatibilité des contrôles opérationnels de tickets SentriX.

La configuration des tickets vit dans le dashboard, mais une fois un ticket ouvert le staff
doit conserver tous les contrôles utiles : prise en charge, abandon, ajout/retrait de membre,
renommage, transfert, note, relance et fermeture. Cette couche garde aussi la migration des
anciens messages afin que les tickets déjà ouverts récupèrent les contrôles disponibles.
"""
from __future__ import annotations

import asyncio
import logging
import re

import discord

logger = logging.getLogger("bot.ticket-controls-operational")

_ALLOWED_KEYS = (
    "claim",
    "unclaim",
    "add",
    "remove",
    "rename",
    "transfer",
    "note",
    "bump",
    "close",
)
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
        try:
            await bot.wait_until_ready()
        except RuntimeError:
            logger.debug("Migration tickets ignorée : client Discord non initialisé.")
            return

        from . import tickets as tickets_mod

        cog = bot.get_cog("Tickets")
        if cog is None:
            return

        try:
            rows = await bot.db.fetchall(
                "SELECT id, guild_id, channel_id, user_id, type_id, category FROM tickets "
                "WHERE status = 'ouvert' ORDER BY id DESC"
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
                async for message in channel.history(limit=25, oldest_first=True):
                    if bot.user is not None and message.author.id != bot.user.id:
                        continue
                    if _is_ticket_control_message(message):
                        control_message = message
                        break
                if control_message is None:
                    continue
                settings = await tickets_mod.get_button_settings(bot, guild.id)
                # Un message V2 ne peut être ramené à une vieille View sans
                # risquer HTTP 400. Il est déjà fonctionnel et ne se migre pas.
                flags = int(getattr(getattr(control_message, "flags", None), "value", 0) or 0)
                if flags & 32768:
                    continue

                # Migrer aussi les tickets encore ouverts AVANT ce déploiement.
                # Envoyer d'abord la nouvelle carte, et ne supprimer l'ancienne
                # qu'après succès : aucun ticket ne perd ses boutons en cas d'erreur.
                old_embed = control_message.embeds[0] if control_message.embeds else None
                opener = guild.get_member(int(row["user_id"])) if row["user_id"] else None
                if old_embed is not None and opener is not None:
                    from services import ticket_panels_v3
                    from utils import sentrix_panels as sx_panels

                    type_row = await bot.db.fetchone(
                        "SELECT name, open_message, staff_role_id, mention_staff "
                        "FROM ticket_types WHERE id=? AND guild_id=?",
                        (int(row["type_id"]), int(guild.id)),
                    ) if row["type_id"] else None
                    staff = guild.get_role(int(type_row["staff_role_id"])) if (
                        type_row and type_row["staff_role_id"] and type_row["mention_staff"]
                    ) else None
                    answers = await bot.db.fetchall(
                        "SELECT question_label, answer FROM ticket_answers WHERE ticket_id=? ORDER BY id",
                        (int(row["id"]),),
                    )
                    match = re.search(r"#(\d+)", str(old_embed.title or ""))
                    number = int(match.group(1)) if match else int(row["id"])
                    card = sx_panels.avec_composants(
                        ticket_panels_v3.opening_card(
                            ticket_number=number,
                            ticket_type=str(type_row["name"] if type_row else row["category"]),
                            opener=opener,
                            description=str(old_embed.description or "")[:420],
                            staff_role=staff,
                            answers=[(x["question_label"], x["answer"]) for x in answers],
                        ),
                        tickets_mod.TicketControlView(settings),
                    )
                    await channel.send(
                        view=card,
                        files=card.fichiers(),
                        # Migration silencieuse : pas de nouveau ping user/staff.
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    try:
                        await control_message.delete()
                    except discord.HTTPException:
                        logger.warning("Ancien panneau ticket non supprimé salon=%s", channel.id)
                else:
                    # Les messages historiques sans membre trouvé restent
                    # opérationnels : ne jamais les effacer sans remplacement.
                    await control_message.edit(view=tickets_mod.TicketControlView(settings))
                updated += 1
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
            "Tickets : contrôles opérationnels réappliqués — %s/%s panneau(x) ouvert(s) actualisé(s).",
            updated,
            scanned,
        )
    finally:
        _MIGRATION_STARTED = False


def install(bot, extension_name: str = "") -> None:
    """Conserve tous les contrôles runtime après le chargement du Cog Tickets."""
    global _INSTALLED, _MIGRATION_STARTED

    cog = bot.get_cog("Tickets")
    if cog is None:
        return

    from . import tickets as tickets_mod

    if not _INSTALLED:
        # Cette extension historique était autrefois limitée à claim + close. On garde
        # maintenant toute la surface opérationnelle, tandis que les commandes de setup
        # sont retirées séparément par sentrix_product_update.
        original_buttons = dict(tickets_mod.STAFF_BUTTONS)
        tickets_mod.STAFF_BUTTONS.clear()
        for key in _ALLOWED_KEYS:
            if key in original_buttons:
                tickets_mod.STAFF_BUTTONS[key] = original_buttons[key]
        tickets_mod.DEFAULT_ENABLED_BUTTONS = set(_ALLOWED_KEYS)

        view_cls = tickets_mod.ButtonSettingsView
        original_view_init = view_cls.__init__
        if not getattr(original_view_init, "_sentrix_operational_ticket_controls", False):
            def operational_settings_init(self, *args, **kwargs):
                original_view_init(self, *args, **kwargs)
                for item in self.children:
                    if isinstance(item, discord.ui.Select):
                        try:
                            item.options[:] = [
                                option for option in item.options
                                if str(getattr(option, "value", "")) in _ALLOWED_KEYS
                            ]
                        except Exception:
                            logger.debug("Impossible de filtrer les options ticket runtime.", exc_info=True)

            operational_settings_init._sentrix_operational_ticket_controls = True
            view_cls.__init__ = operational_settings_init

        tickets_cls = type(cog)
        original_handler = tickets_cls.handle_control_button
        if not getattr(original_handler, "_sentrix_operational_ticket_controls", False):
            async def operational_control_handler(self, interaction: discord.Interaction, key: str):
                if str(key) not in _ALLOWED_KEYS:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "Ce contrôle de ticket n'est pas disponible.",
                            ephemeral=True,
                        )
                    return None
                return await original_handler(self, interaction, key)

            operational_control_handler._sentrix_operational_ticket_controls = True
            tickets_cls.handle_control_button = operational_control_handler

        _INSTALLED = True
        logger.info(
            "Tickets : contrôles opérationnels complets actifs (%s).",
            ", ".join(_ALLOWED_KEYS),
        )

    if not _MIGRATION_STARTED:
        try:
            _MIGRATION_STARTED = True
            task = asyncio.get_running_loop().create_task(
                _migrate_open_ticket_messages(bot),
                name="sentrix-ticket-controls-operational-migration",
            )

            def _consume_result(done: asyncio.Task) -> None:
                try:
                    done.result()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Migration asynchrone des boutons ticket interrompue.")

            task.add_done_callback(_consume_result)
        except RuntimeError:
            _MIGRATION_STARTED = False


__all__ = ["install", "_ALLOWED_KEYS"]
