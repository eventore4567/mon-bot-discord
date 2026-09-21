"""Durcissement d'intégrité SentriX — zéro nouvelle commande.

Ce module corrige des risques transversaux confirmés pendant l'audit A→Z :
- pruning de commandes sûr face aux alias ;
- achat boutique remboursé si l'inventaire ne peut pas être crédité ;
- hiérarchie uniforme sur les actions de modération restantes ;
- boutons de tickets réellement réservés au staff ;
- suppression de ticket marquée en base uniquement après suppression Discord ;
- verrous de mini-jeux auto-récupérables après une exception.

Aucune commande publique n'est créée ici. Les callbacks existants sont conservés avec
leurs paramètres afin de ne pas casser +help, les convertisseurs discord.py ou le slash.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import types

import discord
from discord.ext import commands

from database.db import now
from utils import embeds, stats_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.integrity-hardening")

_GAME_LOCK_TTL_SECONDS = 1800.0


def _install_safe_pruning(bot: commands.Bot) -> bool:
    """Ne supprime jamais une commande canonique uniquement parce qu'un alias est pruné."""
    if getattr(bot, "_sentrix_integrity_safe_pruning", False):
        return True

    def safe_prune(this) -> list[str]:
        import main

        removed_names: list[str] = []
        skipped_aliases: list[str] = []
        for requested_name in sorted(main.PRUNED_COMMANDS):
            command = this.get_command(requested_name)
            if command is None:
                continue
            root = command.root_parent or command
            root_name = str(root.name)
            if root_name.casefold() != str(requested_name).casefold():
                skipped_aliases.append(str(requested_name))
                logger.warning(
                    "Pruning ignoré pour alias %r -> %r afin de préserver la commande canonique.",
                    requested_name,
                    root_name,
                )
                continue
            removed = this.remove_command(root_name)
            if removed is None:
                continue
            removed_names.append(root_name)
            app_command = getattr(removed, "app_command", None)
            app_name = getattr(app_command, "name", None)
            if app_name and this.tree.get_command(app_name):
                try:
                    this.tree.remove_command(app_name)
                except (TypeError, ValueError):
                    logger.debug("Slash %s déjà absent pendant le pruning.", app_name, exc_info=True)

        logger.info(
            "Nettoyage sûr : %s commande(s) retirée(s), %s alias protégés.",
            len(removed_names),
            len(skipped_aliases),
        )
        return removed_names

    bot._prune_redundant_commands = types.MethodType(safe_prune, bot)
    bot._sentrix_integrity_safe_pruning = True
    return True


def _install_economy(bot: commands.Bot) -> bool:
    economy = bot.get_cog("Economy")
    if economy is None:
        return False

    # Les opérations banque / sell / gamble / rob / give-money sont désormais
    # atomiques directement dans cogs/economy.py + services/economy.py.
    # Cette couche conserve uniquement le rollback/remboursement d’un achat
    # d’objet si l’écriture d’inventaire échoue.
    original_purchase = economy._purchase_item
    if not getattr(original_purchase, "_sentrix_integrity_refund", False):
        async def safe_purchase(this, ctx: commands.Context, item):
            if item["role_id"]:
                return await original_purchase(ctx, item)
            status, purchased = await bot.db.purchase_shop_item(
                ctx.guild.id, ctx.author.id, item["id"]
            )
            if status == "not_found":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Article introuvable ou prix invalide.')))
            if status == "insufficient_funds":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Solde insuffisant.')))
            try:
                await bot.db.execute(
                    "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,1) "
                    "ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=quantity+1",
                    (ctx.guild.id, ctx.author.id, purchased["name"]),
                )
            except Exception:
                logger.exception("Crédit inventaire impossible après achat #%s; remboursement.", item["id"])
                try:
                    await bot.db.refund_shop_item(
                        ctx.guild.id,
                        ctx.author.id,
                        purchased,
                        "Remboursement automatique : inventaire indisponible",
                    )
                except Exception:
                    logger.exception("Remboursement automatique impossible après échec inventaire.")
                    return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Achat interrompu. Le staff doit vérifier cette transaction.')))
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Achat annulé et automatiquement remboursé.')))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"**{purchased['name']}** acheté pour **{stats_service.format_number(purchased['price'])}** 🪙.")))

        safe_purchase._sentrix_integrity_refund = True
        economy._purchase_item = types.MethodType(safe_purchase, economy)

    bot._sentrix_integrity_economy = True
    return True


def _install_moderation(bot: commands.Bot) -> bool:
    moderation = bot.get_cog("Moderation")
    if moderation is None:
        return False

    # Les garde-fous de commandes (tempban actif, hiérarchie sur resetnick/move/
    # disconnect/clearwarnings/unwarn) sont dans cogs/moderation.py : aucun callback
    # n'est plus remplacé ici.

    # La levée des sanctions temporaires est assurée par Moderation.check_tempactions
    # (cogs/moderation.py), boucle résiliente et visible dans +health. L'ancien worker
    # parallèle qui l'annulait au démarrage a été supprimé.
    bot._sentrix_integrity_moderation = True
    return True


async def _ticket_staff_allowed(bot: commands.Bot, interaction, ticket) -> bool:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.id == guild.owner_id or member.guild_permissions.manage_channels:
        return True
    type_row = None
    if ticket and ticket["type_id"]:
        type_row = await bot.db.fetchone(
            "SELECT staff_role_id FROM ticket_types WHERE id=? AND guild_id=?",
            (ticket["type_id"], guild.id),
        )
    staff_role_id = int(type_row["staff_role_id"] or 0) if type_row else 0
    if staff_role_id and any(role.id == staff_role_id for role in member.roles):
        return True
    conf = await bot.db.get_guild_config(guild.id)
    mod_role_id = int(conf["mod_role"] or 0) if conf else 0
    return bool(mod_role_id and any(role.id == mod_role_id for role in member.roles))


def _install_tickets(bot: commands.Bot) -> bool:
    tickets = bot.get_cog("Tickets")
    if tickets is None:
        return False

    original_handle = tickets.handle_control_button
    if not getattr(original_handle, "_sentrix_integrity_staff", False):
        async def staff_only_controls(this, interaction: discord.Interaction, key: str):
            ticket = await this.get_ticket_by_channel(interaction.channel.id)
            if not ticket:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Ce salon n'est plus un ticket.")), ephemere=True)
            if not await _ticket_staff_allowed(bot, interaction, ticket):
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Cette action est réservée au staff du ticket.')), ephemere=True)
            return await original_handle(interaction, key)

        staff_only_controls._sentrix_integrity_staff = True
        tickets.handle_control_button = types.MethodType(staff_only_controls, tickets)

    if not getattr(tickets.btn_transfer, "_sentrix_integrity_staff_target", False):
        async def safe_transfer(this, interaction: discord.Interaction, ticket):
            select = discord.ui.UserSelect(placeholder="Choisir un membre du staff")
            view = discord.ui.View(timeout=60)

            async def cb(inter: discord.Interaction):
                member = select.values[0]
                proxy = types.SimpleNamespace(guild=inter.guild, user=member)
                if not await _ticket_staff_allowed(bot, proxy, ticket):
                    return await panels.envoyer(inter.response, panels.depuis_embed(embeds.error("Ce membre n'est pas autorisé à gérer les tickets.")), ephemere=True)
                cur = await bot.db.execute(
                    "UPDATE tickets SET claimed_by=? WHERE id=? AND guild_id=? AND status='ouvert'",
                    (member.id, ticket["id"], inter.guild.id),
                )
                if cur.rowcount < 1:
                    return await panels.envoyer(inter.response, panels.depuis_embed(embeds.warning("Ce ticket n'est plus ouvert.")), ephemere=True)
                await inter.channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
                await panels.envoyer(inter.response, panels.depuis_embed(embeds.success(f'Ticket transféré à {member.mention}.')))

            select.callback = cb
            view.add_item(select)
            return await interaction.response.send_message(
                'Choisissez le membre du staff.', view=view, ephemeral=True
            )

        safe_transfer._sentrix_integrity_staff_target = True
        tickets.btn_transfer = types.MethodType(safe_transfer, tickets)

    if not getattr(tickets._auto_delete, "_sentrix_integrity_delete_order", False):
        async def safe_auto_delete(this, channel: discord.TextChannel, ticket_id: int, delay: int):
            await asyncio.sleep(max(0, int(delay)))
            current = await bot.db.fetchone("SELECT status FROM tickets WHERE id=?", (ticket_id,))
            if not current or current["status"] != "ferme":
                return
            try:
                await channel.delete(reason="Ticket fermé : suppression automatique.")
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Suppression ticket #%s à réessayer; état conservé fermé.", ticket_id)
                return
            await bot.db.execute(
                "UPDATE tickets SET status='supprime' WHERE id=? AND status='ferme'",
                (ticket_id,),
            )

        safe_auto_delete._sentrix_integrity_delete_order = True
        tickets._auto_delete = types.MethodType(safe_auto_delete, tickets)

    old_cleanup = getattr(bot, "_sentrix_integrity_ticket_cleanup_task", None)
    if old_cleanup is None or old_cleanup.done():
        async def ticket_cleanup_worker():
            await bot.wait_until_ready()
            while not bot.is_closed():
                try:
                    rows = await bot.db.fetchall(
                        "SELECT id,guild_id,channel_id FROM tickets WHERE status='ferme' AND locked=1 "
                        "AND closed_at IS NOT NULL AND closed_at<=?",
                        (now() - 60,),
                    )
                    for row in rows[:100]:
                        guild = bot.get_guild(int(row["guild_id"]))
                        channel = guild.get_channel(int(row["channel_id"])) if guild else None
                        if channel is None:
                            await bot.db.execute(
                                "UPDATE tickets SET status='supprime' WHERE id=? AND status='ferme'",
                                (row["id"],),
                            )
                            continue
                        try:
                            await channel.delete(reason="Nettoyage d'un ticket fermé")
                        except (discord.Forbidden, discord.HTTPException):
                            continue
                        await bot.db.execute(
                            "UPDATE tickets SET status='supprime' WHERE id=? AND status='ferme'",
                            (row["id"],),
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Nettoyage de tickets fermés impossible.")
                await asyncio.sleep(300)

        bot._sentrix_integrity_ticket_cleanup_task = asyncio.create_task(ticket_cleanup_worker())

    bot._sentrix_integrity_tickets = True
    return True


def _install_games(bot: commands.Bot) -> bool:
    """Verify that the canonical game service has stale-lock recovery enabled."""
    from utils import game_rewards

    registry = getattr(game_rewards, "_registry", None)
    ready = isinstance(registry, game_rewards.PlayLockRegistry) and float(
        getattr(registry, "ttl", 0.0) or 0.0
    ) > 0.0
    bot._sentrix_integrity_game_locks = bool(ready)
    return bool(ready)

def _install_runtime_registry_audit(bot: commands.Bot) -> bool:
    if getattr(bot, "_sentrix_integrity_registry_audit", False):
        return True

    async def audit_on_ready():
        errors: list[str] = []
        active = list(bot.walk_commands())
        qualified = [str(cmd.qualified_name).casefold() for cmd in active]
        duplicates = sorted({name for name in qualified if qualified.count(name) > 1})
        if duplicates:
            errors.append("commandes dupliquées: " + ", ".join(duplicates))
        for command in active:
            callback = getattr(command, "callback", None)
            if callback is None or not inspect.iscoroutinefunction(callback):
                errors.append(f"callback invalide: {command.qualified_name}")
            try:
                _ = command.signature
            except Exception as exc:
                errors.append(
                    f"signature invalide {command.qualified_name}: {type(exc).__name__}"
                )
        try:
            from . import command_catalog_cleanup
            missing = sorted(
                name for name in command_catalog_cleanup.NORMAL_DIRECT_COMMANDS
                if bot.get_command(name) is None
            )
            if missing:
                errors.append("commandes directes absentes: " + ", ".join(missing))
        except Exception:
            logger.exception("Audit du catalogue direct impossible.")
        bot._sentrix_integrity_state = {
            "ready": not errors,
            "errors": tuple(errors),
            "commands_checked": len(active),
            "new_commands": 0,
            "safe_pruning": bool(getattr(bot, "_sentrix_integrity_safe_pruning", False)),
            "economy": bool(getattr(bot, "_sentrix_integrity_economy", False)),
            "moderation": bool(getattr(bot, "_sentrix_integrity_moderation", False)),
            "tickets": bool(getattr(bot, "_sentrix_integrity_tickets", False)),
            "game_locks": bool(getattr(bot, "_sentrix_integrity_game_locks", False)),
        }
        if errors:
            for error in errors:
                logger.error("Audit intégrité: %s", error)
        else:
            logger.info("Audit intégrité runtime OK : %s commandes vérifiées.", len(active))

    bot.add_listener(audit_on_ready, "on_ready")
    bot._sentrix_integrity_registry_audit = True
    return True


def install(bot: commands.Bot) -> None:
    """Installation idempotente. N'ajoute aucune commande au bot."""
    if getattr(bot, "_sentrix_integrity_hardening_installed", False):
        return
    safe_pruning = _install_safe_pruning(bot)
    economy = _install_economy(bot)
    moderation = _install_moderation(bot)
    tickets = _install_tickets(bot)
    games = _install_games(bot)
    audit = _install_runtime_registry_audit(bot)
    bot._sentrix_integrity_hardening_installed = True
    bot._sentrix_integrity_install_state = {
        "new_commands": 0,
        "safe_pruning": bool(safe_pruning),
        "economy": bool(economy),
        "moderation": bool(moderation),
        "tickets": bool(tickets),
        "games": bool(games),
        "audit": bool(audit),
    }
    logger.info(
        "SentriX Integrity actif : pruning=%s économie=%s modération=%s tickets=%s jeux=%s; 0 nouvelle commande.",
        safe_pruning,
        economy,
        moderation,
        tickets,
        games,
    )
