"""Durcissement d'intégrité SentriX — zéro nouvelle commande.

Ce module corrige des risques transversaux confirmés pendant l'audit A→Z :
- pruning de commandes sûr face aux alias ;
- transactions économie sérialisées (vente, casino, banque) ;
- remboursement d'un achat si l'inventaire ne peut pas être crédité ;
- hiérarchie uniforme sur les actions de modération restantes ;
- tempban persistant et réessayé si Discord refuse temporairement l'unban ;
- boutons de tickets réellement réservés au staff ;
- suppression de ticket marquée en base uniquement après suppression Discord ;
- verrous de mini-jeux auto-récupérables après une exception.

Aucune commande publique n'est créée ici. Les callbacks existants sont conservés avec
leurs paramètres afin de ne pas casser +help, les convertisseurs discord.py ou le slash.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import secrets
import time
import types
from collections import defaultdict

import discord
from discord.ext import commands

from database.db import now
from utils import embeds, stats_service
from utils import sentrix_panels as panels
from utils.v22_rules import clean_reason, parse_friendly_amount, parse_friendly_duration

logger = logging.getLogger("bot.integrity-hardening")

_GAME_LOCK_TTL_SECONDS = 1800.0


def _replace_callback(command, callback, marker: str) -> bool:
    if command is None or getattr(command, marker, False):
        return False
    params = command.params.copy()
    callback = functools.wraps(command.callback)(callback)
    command.callback = callback
    command.params = params
    setattr(command, marker, True)
    return True


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


async def _fetchone_conn(conn, query: str, params: tuple = ()):
    cur = await conn.execute(query, params)
    try:
        return await cur.fetchone()
    finally:
        await cur.close()


async def _atomic_bank_transfer(db, guild_id: int, user_id: int, raw_amount: str, *, deposit: bool):
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable", 0
    async with db._economy_lock:
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, user_id),
            )
            row = await _fetchone_conn(
                conn,
                "SELECT cash,bank FROM economy WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            source = int(row["cash"] if deposit else row["bank"]) if row else 0
            amount = parse_friendly_amount(str(raw_amount), source)
            if amount is None or int(amount) <= 0 or int(amount) > source:
                await conn.commit()
                return "invalid", 0
            amount = int(amount)
            if deposit:
                cur = await conn.execute(
                    "UPDATE economy SET cash=cash-?, bank=bank+? "
                    "WHERE guild_id=? AND user_id=? AND cash>=?",
                    (amount, amount, guild_id, user_id, amount),
                )
                transaction_type = "deposit"
                reason = "Dépôt bancaire"
            else:
                cur = await conn.execute(
                    "UPDATE economy SET cash=cash+?, bank=bank-? "
                    "WHERE guild_id=? AND user_id=? AND bank>=?",
                    (amount, amount, guild_id, user_id, amount),
                )
                transaction_type = "withdraw"
                reason = "Retrait bancaire"
            if cur.rowcount < 1:
                await conn.rollback()
                return "changed", 0
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (guild_id, user_id, user_id, transaction_type, amount, now(), reason),
            )
            await conn.commit()
            return "ok", amount
        except Exception:
            await conn.rollback()
            logger.exception("Transaction banque annulée (deposit=%s).", deposit)
            return "error", 0


async def _atomic_sell(db, guild_id: int, user_id: int, item_name: str):
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable", 0
    async with db._economy_lock:
        try:
            row = await _fetchone_conn(
                conn,
                "SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_name=?",
                (guild_id, user_id, item_name),
            )
            if not row or int(row["quantity"] or 0) < 1:
                return "missing", 0
            item = await _fetchone_conn(
                conn,
                "SELECT price FROM shop_items WHERE guild_id=? AND name=?",
                (guild_id, item_name),
            )
            price = max(0, int(int(item["price"]) * 0.5)) if item else 10
            cur = await conn.execute(
                "UPDATE inventory SET quantity=quantity-1 "
                "WHERE guild_id=? AND user_id=? AND item_name=? AND quantity>=1",
                (guild_id, user_id, item_name),
            )
            if cur.rowcount < 1:
                await conn.rollback()
                return "changed", 0
            await conn.execute(
                "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=? AND quantity<=0",
                (guild_id, user_id, item_name),
            )
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, user_id),
            )
            await conn.execute(
                "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                (price, guild_id, user_id),
            )
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,NULL,?,'sell',?,?,?)",
                (guild_id, user_id, price, now(), f"Vente : {item_name}"),
            )
            await conn.commit()
            return "ok", price
        except Exception:
            await conn.rollback()
            logger.exception("Vente atomique annulée.")
            return "error", 0


async def _atomic_gamble(db, guild_id: int, user_id: int, amount: int, *, win: bool):
    if amount <= 0:
        return "invalid"
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable"
    async with db._economy_lock:
        try:
            await conn.execute(
                "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                (guild_id, user_id),
            )
            delta = amount if win else -amount
            cur = await conn.execute(
                "UPDATE economy SET cash=cash+? "
                "WHERE guild_id=? AND user_id=? AND cash>=?",
                (delta, guild_id, user_id, amount),
            )
            if cur.rowcount < 1:
                await conn.rollback()
                return "insufficient"
            await conn.execute(
                "INSERT INTO economy_transactions "
                "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    guild_id,
                    None if win else user_id,
                    user_id if win else None,
                    "gamble_win" if win else "gamble_loss",
                    amount,
                    now(),
                    "Casino",
                ),
            )
            await conn.commit()
            return "ok"
        except Exception:
            await conn.rollback()
            logger.exception("Mise casino annulée.")
            return "error"


def _install_economy(bot: commands.Bot) -> bool:
    economy = bot.get_cog("Economy")
    if economy is None:
        return False

    async def safe_deposit(this, ctx: commands.Context, montant: str):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Disponible uniquement sur un serveur.')))
        status, amount = await _atomic_bank_transfer(
            bot.db, ctx.guild.id, ctx.author.id, montant, deposit=True
        )
        if status == "ok":
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'**{stats_service.format_number(amount)}** 🪙 déposés en banque.')))
        if status in {"invalid", "changed"}:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Montant invalide ou solde insuffisant.')))
        return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Banque temporairement indisponible.')))

    safe_deposit._sentrix_integrity = True
    economy._deposit_to_bank = types.MethodType(safe_deposit, economy)

    withdraw = bot.get_command("withdraw")
    if withdraw is not None:
        async def safe_withdraw(cog, ctx: commands.Context, montant: str):
            if ctx.guild is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Disponible uniquement sur un serveur.')))
            status, amount = await _atomic_bank_transfer(
                bot.db, ctx.guild.id, ctx.author.id, montant, deposit=False
            )
            if status == "ok":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'**{stats_service.format_number(amount)}** 🪙 retirés de la banque.')))
            if status in {"invalid", "changed"}:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Montant invalide ou solde insuffisant.')))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Banque temporairement indisponible.')))
        _replace_callback(withdraw, safe_withdraw, "_sentrix_integrity_atomic")

    sell = bot.get_command("sell")
    if sell is not None:
        async def safe_sell(cog, ctx: commands.Context, *, objet: str):
            if ctx.guild is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Disponible uniquement sur un serveur.')))
            item_name = str(objet or "").strip()
            if not item_name:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Indiquez l'objet à vendre.")))
            status, price = await _atomic_sell(bot.db, ctx.guild.id, ctx.author.id, item_name)
            if status == "ok":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'**{item_name}** vendu pour **{stats_service.format_number(price)}** 🪙.')))
            if status in {"missing", "changed"}:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne possèdes pas cet objet.')))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vente temporairement indisponible.')))
        _replace_callback(sell, safe_sell, "_sentrix_integrity_atomic")

    gamble = bot.get_command("gamble")
    if gamble is not None:
        async def safe_gamble(cog, ctx: commands.Context, montant: int):
            if ctx.guild is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Disponible uniquement sur un serveur.')))
            if int(montant) <= 0:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le montant doit être positif.')))
            win = secrets.randbelow(2) == 0
            status = await _atomic_gamble(bot.db, ctx.guild.id, ctx.author.id, int(montant), win=win)
            if status == "insufficient":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Solde insuffisant.')))
            if status != "ok":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Casino temporairement indisponible.')))
            amount_text = stats_service.format_number(int(montant))
            if win:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Vous gagnez **{amount_text}** 🪙.')))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Vous perds **{amount_text}** 🪙.')))
        _replace_callback(gamble, safe_gamble, "_sentrix_integrity_atomic")

    give_money = bot.get_command("give-money")
    if give_money is not None:
        original_give = give_money.callback

        async def positive_grant(cog, ctx: commands.Context, membre: discord.Member, montant: int):
            if int(montant) <= 0:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le montant doit être supérieur à 0.')))
            return await original_give(cog, ctx, membre, int(montant))

        _replace_callback(give_money, positive_grant, "_sentrix_integrity_positive_grant")

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

    target_locks: dict[tuple[int, int], asyncio.Lock] = getattr(
        bot, "_sentrix_integrity_mod_locks", None
    ) or defaultdict(asyncio.Lock)
    bot._sentrix_integrity_mod_locks = target_locks

    tempban = bot.get_command("tempban")
    if tempban is not None:
        async def safe_tempban(
            cog,
            ctx: commands.Context,
            membre: discord.Member,
            duree: str,
            *,
            raison: str = "Aucun motif",
        ):
            await cog._ack(ctx)
            if ctx.guild is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Disponible uniquement sur un serveur.')))
            if not await cog.check_targetable(ctx, membre):
                return
            seconds = parse_friendly_duration(duree)
            if seconds is None or int(seconds) <= 0:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide. Exemple : `30m`, `2h`, `1j`.')))
            reason = clean_reason(raison)
            key = (ctx.guild.id, membre.id)
            async with target_locks[key]:
                existing = await bot.db.fetchone(
                    "SELECT id FROM tempactions WHERE guild_id=? AND user_id=? AND action='ban' "
                    "AND expires_at>? LIMIT 1",
                    (ctx.guild.id, membre.id, now()),
                )
                if existing:
                    return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Un bannissement temporaire actif existe déjà.')))
                cur = await bot.db.execute(
                    "INSERT INTO tempactions (guild_id,user_id,action,expires_at) "
                    "VALUES (?,?,'ban',?)",
                    (ctx.guild.id, membre.id, now() + int(seconds)),
                )
                tempaction_id = int(cur.lastrowid)
                await cog._send_sanction_dm(ctx, membre, "tempban", reason, int(seconds))
                try:
                    await ctx.guild.ban(
                        membre,
                        reason=f"{ctx.author} (temporaire {duree}) : {reason}",
                        delete_message_seconds=0,
                    )
                except discord.HTTPException:
                    await bot.db.execute("DELETE FROM tempactions WHERE id=?", (tempaction_id,))
                    return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Discord a refusé le bannissement. Aucune durée n'a été enregistrée.")))
                result = await cog.log_sanction(
                    ctx,
                    "tempban",
                    membre,
                    reason,
                    duration_seconds=int(seconds),
                )
                return await ctx.send(embed=result)

        _replace_callback(tempban, safe_tempban, "_sentrix_integrity_tempban")

    for name in ("resetnick", "move", "disconnect", "clearwarnings"):
        command = bot.get_command(name)
        if command is None:
            continue
        original = command.callback

        async def hierarchy_wrapper(cog, ctx, *args, __original=original, **kwargs):
            target = kwargs.get("membre")
            if target is None:
                target = args[0] if args else None
            if isinstance(target, discord.Member) and not await cog.check_targetable(ctx, target):
                return None
            return await __original(cog, ctx, *args, **kwargs)

        _replace_callback(command, hierarchy_wrapper, "_sentrix_integrity_hierarchy")

    unwarn = bot.get_command("unwarn")
    if unwarn is not None:
        original_unwarn = unwarn.callback

        async def safe_unwarn(cog, ctx: commands.Context, warn_id: int):
            if ctx.guild is not None:
                row = await bot.db.fetchone(
                    "SELECT user_id FROM warnings WHERE id=? AND guild_id=?",
                    (int(warn_id), ctx.guild.id),
                )
                member = ctx.guild.get_member(int(row["user_id"])) if row else None
                if member is not None and not await cog.check_targetable(ctx, member):
                    return None
            return await original_unwarn(cog, ctx, int(warn_id))

        _replace_callback(unwarn, safe_unwarn, "_sentrix_integrity_hierarchy")

    try:
        if moderation.check_tempactions.is_running():
            moderation.check_tempactions.cancel()
    except Exception:
        logger.debug("Impossible d'arrêter le worker tempactions historique.", exc_info=True)

    old_task = getattr(bot, "_sentrix_integrity_tempaction_task", None)
    if old_task is None or old_task.done():
        async def tempaction_worker():
            await bot.wait_until_ready()
            while not bot.is_closed():
                try:
                    rows = await bot.db.fetchall(
                        "SELECT * FROM tempactions WHERE expires_at<=? ORDER BY expires_at,id",
                        (now(),),
                    )
                    for row in rows:
                        if row["action"] != "ban":
                            logger.warning("Tempaction inconnue conservée id=%s action=%s", row["id"], row["action"])
                            continue
                        guild = bot.get_guild(int(row["guild_id"]))
                        if guild is None:
                            continue
                        unbanned = False
                        try:
                            await guild.unban(
                                discord.Object(id=int(row["user_id"])),
                                reason="Fin du bannissement temporaire",
                            )
                            unbanned = True
                        except discord.NotFound:
                            unbanned = True
                        except (discord.Forbidden, discord.HTTPException):
                            logger.warning(
                                "Unban temporaire à réessayer (guild=%s user=%s).",
                                row["guild_id"],
                                row["user_id"],
                            )
                            continue
                        if unbanned:
                            try:
                                await bot.db.record_sanction(
                                    int(row["guild_id"]),
                                    int(row["user_id"]),
                                    int(getattr(bot.user, "id", 0) or 0),
                                    "unban",
                                    "Fin du bannissement temporaire (automatique)",
                                )
                            except Exception:
                                logger.exception("Journalisation de fin de tempban impossible.")
                            await bot.db.execute("DELETE FROM tempactions WHERE id=?", (row["id"],))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Worker tempactions sécurisé en échec; nouvel essai dans 60 s.")
                await asyncio.sleep(60)

        bot._sentrix_integrity_tempaction_task = asyncio.create_task(tempaction_worker())

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


class _ExpiringPlayLockRegistry:
    """Même API que game_rewards.PlayLockRegistry, mais une exception ne bloque pas à vie."""

    def __init__(self, ttl: float = _GAME_LOCK_TTL_SECONDS):
        self.ttl = float(ttl)
        self._locked: dict[tuple[int, int, str], float] = {}

    def _prune(self, current: float | None = None):
        current = time.monotonic() if current is None else current
        stale = [key for key, stamp in self._locked.items() if current - stamp >= self.ttl]
        for key in stale:
            self._locked.pop(key, None)

    def try_acquire(self, guild_id: int, user_id: int, game_name: str) -> bool:
        current = time.monotonic()
        self._prune(current)
        key = (int(guild_id), int(user_id), str(game_name))
        if key in self._locked:
            return False
        self._locked[key] = current
        return True

    def release(self, guild_id: int, user_id: int, game_name: str):
        self._locked.pop((int(guild_id), int(user_id), str(game_name)), None)


def _install_games(bot: commands.Bot) -> bool:
    from utils import game_rewards
    if isinstance(getattr(game_rewards, "_registry", None), _ExpiringPlayLockRegistry):
        return True
    game_rewards._registry = _ExpiringPlayLockRegistry()
    bot._sentrix_integrity_game_locks = True
    return True


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
