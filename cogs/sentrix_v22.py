"""SentriX V2.2 — polish, performance et fiabilité SANS nouvelle commande.

Cette couche améliore uniquement les systèmes déjà existants : parsing UX, statistiques,
économie, modération, tickets, IA et mini-jeux. Elle ne déclare aucune nouvelle commande.
Les patchs conservent les paramètres des Command existantes afin de ne pas reproduire les
anciens problèmes de signatures visibles dans +help.
"""
from __future__ import annotations

import asyncio
import copy
import functools
import logging
import secrets
import time
import types
from collections import defaultdict

import discord
from discord.ext import commands

from utils import embeds, stats_service
from utils.v22_rules import (
    clean_reason,
    parse_friendly_amount,
    parse_friendly_duration,
    safe_penalty,
    ttl_is_fresh,
)

logger = logging.getLogger("bot.sentrix-v22")

ROB_COOLDOWN_SECONDS = 3600
AI_SETTINGS_TTL = 20.0
GAME_SETTINGS_TTL = 20.0
TICKET_BUTTON_SETTINGS_TTL = 15.0


async def _safe_interaction_message(interaction: discord.Interaction, embed: discord.Embed):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        pass


class SentriXV22(commands.Cog):
    """Runtime de durcissement. Zéro nouvelle commande publique."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ticket_open_locks: dict[tuple[int, int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ticket_create_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ticket_close_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._warn_locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ai_settings_cache: dict[tuple[int, int], tuple[float, dict]] = {}
        self._game_settings_cache: dict[tuple[int, int], tuple[float, dict]] = {}
        self._ticket_button_cache: dict[tuple[int, int], tuple[float, dict]] = {}

    async def cog_load(self):
        await self._install_database_tuning()
        self._install_shared_parsers()
        self._install_economy_hardening()
        self._install_moderation_hardening()
        self._install_ticket_hardening()
        self._install_ai_cache()
        self._install_game_cache()
        self.bot._sentrix_v22_ready = True
        self.bot._sentrix_v22_state = {
            "ready": True,
            "new_commands": 0,
            "installed_at": int(time.time()),
            "features": [
                "stats-query-collapse", "persistent-atomic-rob", "moderation-guards",
                "ticket-concurrency", "ai-settings-cache", "game-settings-cache",
                "sqlite-tuning", "friendly-arguments",
            ],
        }
        logger.info("SentriX V2.2 installé : polish/performance/fiabilité, 0 nouvelle commande.")

    async def _install_database_tuning(self):
        conn = getattr(self.bot.db, "_conn", None)
        if conn is None:
            return
        try:
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("PRAGMA cache_size=-20000")
            await conn.execute("PRAGMA temp_store=MEMORY")
            await conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_tickets_member_type_status
                  ON tickets (guild_id, user_id, type_id, status);
                CREATE INDEX IF NOT EXISTS idx_tickets_claim_status
                  ON tickets (guild_id, status, claimed_by);
                CREATE INDEX IF NOT EXISTS idx_economy_tx_sender_time
                  ON economy_transactions (guild_id, sender_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_economy_tx_receiver_time
                  ON economy_transactions (guild_id, receiver_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_ai_usage_day_guild
                  ON ai_usage (day, guild_id);
                CREATE INDEX IF NOT EXISTS idx_market_seller_status
                  ON v2_market_listings (guild_id, seller_id, status);
                """
            )
            await conn.commit()
        except Exception:
            logger.exception("V2.2 : optimisation SQLite impossible, démarrage poursuivi.")

    def _install_shared_parsers(self):
        from utils import helpers
        from . import economy as economy_module

        if not getattr(helpers.parse_duration, "_sentrix_v22", False):
            parse_friendly_duration._sentrix_v22 = True
            helpers.parse_duration = parse_friendly_duration

        if not getattr(economy_module._parse_amount, "_sentrix_v22", False):
            def friendly_amount(value: str, available: int):
                return parse_friendly_amount(value, available)
            friendly_amount._sentrix_v22 = True
            economy_module._parse_amount = friendly_amount

    @staticmethod
    def _replace_command_callback(command, callback, marker: str):
        if command is None or getattr(command, marker, False):
            return False
        params = command.params.copy()
        callback = functools.wraps(command.callback)(callback)
        command.callback = callback
        command.params = params
        setattr(command, marker, True)
        return True

    def _install_economy_hardening(self):
        command = self.bot.get_command("rob")
        if command is None or getattr(command, "_sentrix_v22_atomic_rob", False):
            return

        async def atomic_rob(economy_cog, ctx: commands.Context, membre: discord.Member):
            if ctx.guild is None:
                return await ctx.send(embed=embeds.error("Utilisez cette commande sur un serveur."))
            if membre.id == ctx.author.id:
                return await ctx.send(embed=embeds.error("Vous ne pouvez pas vous voler vous-même."))
            if membre.bot:
                return await ctx.send(embed=embeds.error("Vous ne pouvez pas voler un bot."))

            db = self.bot.db
            conn = getattr(db, "_conn", None)
            if conn is None:
                return await ctx.send(embed=embeds.error("L'économie est temporairement indisponible."))

            result = ("error", 0)
            async with db._economy_lock:
                try:
                    await conn.execute(
                        "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                        (ctx.guild.id, ctx.author.id),
                    )
                    await conn.execute(
                        "INSERT OR IGNORE INTO economy (guild_id,user_id) VALUES (?,?)",
                        (ctx.guild.id, membre.id),
                    )
                    actor = await db.fetchone(
                        "SELECT cash,last_rob FROM economy WHERE guild_id=? AND user_id=?",
                        (ctx.guild.id, ctx.author.id),
                    )
                    target = await db.fetchone(
                        "SELECT cash FROM economy WHERE guild_id=? AND user_id=?",
                        (ctx.guild.id, membre.id),
                    )
                    actor_cash = int(actor["cash"] if actor else 0)
                    target_cash = int(target["cash"] if target else 0)
                    last_rob = int(actor["last_rob"] if actor else 0)
                    now_ts = int(time.time())
                    remaining = ROB_COOLDOWN_SECONDS - (now_ts - last_rob) if last_rob else 0
                    if remaining > 0:
                        # Les INSERT OR IGNORE ci-dessus peuvent avoir ouvert une transaction
                        # sur un compte neuf. On la ferme explicitement même sans vol.
                        await conn.commit()
                        result = ("cooldown", remaining)
                    elif target_cash < 50:
                        await conn.commit()
                        result = ("poor", 0)
                    else:
                        await conn.execute(
                            "UPDATE economy SET last_rob=? WHERE guild_id=? AND user_id=?",
                            (now_ts, ctx.guild.id, ctx.author.id),
                        )
                        if secrets.randbelow(100) < 40:
                            ceiling = min(target_cash, 300)
                            amount = 1 + secrets.randbelow(ceiling)
                            debit = await conn.execute(
                                "UPDATE economy SET cash=cash-? WHERE guild_id=? AND user_id=? AND cash>=?",
                                (amount, ctx.guild.id, membre.id, amount),
                            )
                            if debit.rowcount < 1:
                                await conn.rollback()
                                result = ("retry", 0)
                            else:
                                await conn.execute(
                                    "UPDATE economy SET cash=cash+? WHERE guild_id=? AND user_id=?",
                                    (amount, ctx.guild.id, ctx.author.id),
                                )
                                await conn.execute(
                                    "INSERT INTO economy_transactions "
                                    "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                                    "VALUES (?,?,?,?,?,?,?)",
                                    (ctx.guild.id, membre.id, ctx.author.id, "rob", amount, now_ts, "Vol réussi V2.2"),
                                )
                                await conn.commit()
                                result = ("success", amount)
                        else:
                            requested = 20 + secrets.randbelow(81)
                            penalty = safe_penalty(actor_cash, requested)
                            if penalty:
                                await conn.execute(
                                    "UPDATE economy SET cash=cash-? WHERE guild_id=? AND user_id=? AND cash>=?",
                                    (penalty, ctx.guild.id, ctx.author.id, penalty),
                                )
                                await conn.execute(
                                    "INSERT INTO economy_transactions "
                                    "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                                    "VALUES (?,?,NULL,?,?,?,?)",
                                    (ctx.guild.id, ctx.author.id, "rob_fail", penalty, now_ts, "Vol raté, amende V2.2"),
                                )
                            await conn.commit()
                            result = ("failed", penalty)
                except Exception:
                    await conn.rollback()
                    logger.exception("V2.2 : transaction +rob annulée.")
                    result = ("error", 0)

            kind, value = result
            if kind == "cooldown":
                minutes = max(1, (int(value) + 59) // 60)
                return await ctx.send(embed=embeds.warning(f"Vous devez attendre encore **{minutes} min** avant de retenter un vol."))
            if kind == "poor":
                return await ctx.send(embed=embeds.warning(f"{membre.display_name} n'a pas assez d'argent liquide à voler."))
            if kind == "retry":
                return await ctx.send(embed=embeds.warning("Le solde de la cible vient de changer. Réessayez."))
            if kind == "success":
                return await ctx.send(embed=embeds.success(
                    f"Vous avez volé **{stats_service.format_number(value)} 🪙** à {membre.display_name}."
                ))
            if kind == "failed":
                if value:
                    return await ctx.send(embed=embeds.error(
                        f"Vous avez été attrapé : **{stats_service.format_number(value)} 🪙** d'amende."
                    ))
                return await ctx.send(embed=embeds.error("Vous avez été attrapé, mais votre portefeuille était déjà vide."))
            return await ctx.send(embed=embeds.error("Le vol n'a pas pu être traité. Réessayez."))

        self._replace_command_callback(command, atomic_rob, "_sentrix_v22_atomic_rob")

    def _install_moderation_hardening(self):
        moderation = self.bot.get_cog("Moderation")
        if moderation is None:
            return

        original_dm = moderation._send_sanction_dm
        if not getattr(original_dm, "_sentrix_v22", False):
            async def bounded_dm(this, ctx, target, action, reason, duration_seconds=None):
                try:
                    return await asyncio.wait_for(
                        original_dm(ctx, target, action, clean_reason(reason), duration_seconds),
                        timeout=2.5,
                    )
                except asyncio.TimeoutError:
                    logger.info("V2.2 : MP de sanction expiré après 2.5 s (action=%s).", action)
                    return False
            bounded_dm._sentrix_v22 = True
            moderation._send_sanction_dm = types.MethodType(bounded_dm, moderation)

        unmute = self.bot.get_command("unmute")
        if unmute is not None and not getattr(unmute, "_sentrix_v22_hierarchy", False):
            original = unmute.callback
            async def guarded_unmute(cog, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
                if not await cog.check_targetable(ctx, membre):
                    return
                return await original(cog, ctx, membre, raison=clean_reason(raison))
            self._replace_command_callback(unmute, guarded_unmute, "_sentrix_v22_hierarchy")

        warn = self.bot.get_command("warn")
        if warn is not None and not getattr(warn, "_sentrix_v22_serial_warn", False):
            original = warn.callback
            async def serial_warn(cog, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
                key = (ctx.guild.id, membre.id)
                async with self._warn_locks[key]:
                    return await original(cog, ctx, membre, raison=clean_reason(raison))
            self._replace_command_callback(warn, serial_warn, "_sentrix_v22_serial_warn")

        for name in ("ban", "kick", "unban"):
            command = self.bot.get_command(name)
            if command is None or getattr(command, "_sentrix_v22_reason", False):
                continue
            original = command.callback
            async def reason_wrapper(cog, ctx, *args, __original=original, **kwargs):
                if "raison" in kwargs:
                    kwargs["raison"] = clean_reason(kwargs.get("raison"))
                return await __original(cog, ctx, *args, **kwargs)
            self._replace_command_callback(command, reason_wrapper, "_sentrix_v22_reason")

        for name in ("tempban", "mute"):
            command = self.bot.get_command(name)
            if command is None or getattr(command, "_sentrix_v22_reason", False):
                continue
            original = command.callback
            async def reason_duration_wrapper(cog, ctx, *args, __original=original, **kwargs):
                if "raison" in kwargs:
                    kwargs["raison"] = clean_reason(kwargs.get("raison"))
                return await __original(cog, ctx, *args, **kwargs)
            self._replace_command_callback(command, reason_duration_wrapper, "_sentrix_v22_reason")

    def _install_ticket_hardening(self):
        from . import tickets as tickets_module
        tickets_cog = self.bot.get_cog("Tickets")
        if tickets_cog is None:
            return

        original_get_buttons = tickets_module.get_button_settings
        original_save_buttons = tickets_module.save_button_settings
        if not getattr(original_get_buttons, "_sentrix_v22", False):
            async def cached_buttons(bot, guild_id: int):
                key = (id(bot), int(guild_id))
                now_value = time.monotonic()
                cached = self._ticket_button_cache.get(key)
                if cached and ttl_is_fresh(cached[0], now_value, TICKET_BUTTON_SETTINGS_TTL):
                    return copy.deepcopy(cached[1])
                value = await original_get_buttons(bot, guild_id)
                self._ticket_button_cache[key] = (now_value, copy.deepcopy(value))
                return value
            cached_buttons._sentrix_v22 = True
            tickets_module.get_button_settings = cached_buttons

            async def save_and_invalidate(bot, guild_id: int, settings: dict):
                await original_save_buttons(bot, guild_id, settings)
                self._ticket_button_cache.pop((id(bot), int(guild_id)), None)
            save_and_invalidate._sentrix_v22 = True
            tickets_module.save_button_settings = save_and_invalidate

        original_start = tickets_cog.start_ticket_flow
        if not getattr(original_start, "_sentrix_v22", False):
            async def serialized_start(this, interaction: discord.Interaction, type_id: int):
                if interaction.guild is None:
                    return await _safe_interaction_message(interaction, embeds.error("Serveur introuvable."))
                key = (interaction.guild.id, interaction.user.id, int(type_id))
                lock = self._ticket_open_locks[key]
                if lock.locked():
                    return await _safe_interaction_message(
                        interaction, embeds.warning("Une ouverture de ticket est déjà en cours. Patientez un instant.")
                    )
                async with lock:
                    return await original_start(interaction, type_id)
            serialized_start._sentrix_v22 = True
            tickets_cog.start_ticket_flow = types.MethodType(serialized_start, tickets_cog)

        # Le formulaire Discord peut survivre plus longtemps que le verrou start_ticket_flow.
        # On protège donc AUSSI la création réelle du salon. Le verrou par serveur garantit
        # un numéro de ticket unique avec l'algorithme historique COUNT(*)+1 et on revérifie
        # la limite du membre juste avant l'appel Discord create_text_channel().
        original_create = tickets_cog.create_ticket
        if not getattr(original_create, "_sentrix_v22", False):
            async def serialized_create(this, interaction: discord.Interaction, ticket_type, answers: list):
                guild = interaction.guild
                if guild is None:
                    return await _safe_interaction_message(interaction, embeds.error("Serveur introuvable."))
                async with self._ticket_create_locks[guild.id]:
                    type_id = int(ticket_type["id"])
                    limit = max(1, int(ticket_type["max_per_member"] or 1))
                    open_count = await self.bot.db.fetchone(
                        "SELECT COUNT(*) AS c FROM tickets WHERE guild_id=? AND user_id=? AND type_id=? AND status='ouvert'",
                        (guild.id, interaction.user.id, type_id),
                    )
                    count = int(open_count["c"] if open_count else 0)
                    if count >= limit:
                        return await _safe_interaction_message(
                            interaction,
                            embeds.warning(
                                f"Vous avez déjà **{count}** ticket(s) « {ticket_type['name']} » ouvert(s) "
                                f"(maximum : {limit})."
                            ),
                        )
                    return await original_create(interaction, ticket_type, answers)
            serialized_create._sentrix_v22 = True
            tickets_cog.create_ticket = types.MethodType(serialized_create, tickets_cog)

        if not getattr(tickets_cog.btn_claim, "_sentrix_v22", False):
            async def atomic_claim(this, interaction: discord.Interaction, ticket):
                cursor = await self.bot.db.execute(
                    "UPDATE tickets SET claimed_by=? WHERE id=? AND guild_id=? AND status='ouvert' AND claimed_by IS NULL",
                    (interaction.user.id, ticket["id"], interaction.guild.id),
                )
                if getattr(cursor, "rowcount", 0) < 1:
                    current = await self.bot.db.fetchone(
                        "SELECT claimed_by,status FROM tickets WHERE id=? AND guild_id=?",
                        (ticket["id"], interaction.guild.id),
                    )
                    if current and current["status"] == "ouvert" and current["claimed_by"]:
                        return await interaction.response.send_message(
                            embed=embeds.warning(f"Ce ticket est déjà pris en charge par <@{int(current['claimed_by'])}>."),
                            ephemeral=True,
                        )
                    return await interaction.response.send_message(embed=embeds.warning("Ce ticket n'est plus disponible."), ephemeral=True)
                await interaction.response.send_message(embed=embeds.success(f"{interaction.user.mention} a pris en charge ce ticket."))
            atomic_claim._sentrix_v22 = True
            tickets_cog.btn_claim = types.MethodType(atomic_claim, tickets_cog)

        if not getattr(tickets_cog.btn_unclaim, "_sentrix_v22", False):
            async def guarded_unclaim(this, interaction: discord.Interaction, ticket):
                current = await self.bot.db.fetchone(
                    "SELECT claimed_by,status FROM tickets WHERE id=? AND guild_id=?",
                    (ticket["id"], interaction.guild.id),
                )
                if not current or current["status"] != "ouvert":
                    return await interaction.response.send_message(embed=embeds.warning("Ce ticket n'est plus ouvert."), ephemeral=True)
                claimed_by = current["claimed_by"]
                if not claimed_by:
                    return await interaction.response.send_message(embed=embeds.warning("Ce ticket n'est pas claim."), ephemeral=True)
                member = interaction.user
                can_force = bool(member.guild_permissions.manage_channels or member.id == interaction.guild.owner_id)
                if int(claimed_by) != member.id and not can_force:
                    return await interaction.response.send_message(
                        embed=embeds.error("Seul le staff qui a claim ce ticket (ou un responsable) peut l'abandonner."),
                        ephemeral=True,
                    )
                cursor = await self.bot.db.execute(
                    "UPDATE tickets SET claimed_by=NULL WHERE id=? AND guild_id=? AND status='ouvert' AND claimed_by=?",
                    (ticket["id"], interaction.guild.id, claimed_by),
                )
                if getattr(cursor, "rowcount", 0) < 1:
                    return await interaction.response.send_message(
                        embed=embeds.warning("La prise en charge vient de changer. Actualisez le ticket."), ephemeral=True
                    )
                await interaction.response.send_message(embed=embeds.success("Prise en charge annulée."))
            guarded_unclaim._sentrix_v22 = True
            tickets_cog.btn_unclaim = types.MethodType(guarded_unclaim, tickets_cog)

        original_close = tickets_cog.close_ticket
        if not getattr(original_close, "_sentrix_v22", False):
            async def serialized_close(this, interaction: discord.Interaction, ticket_id: int, reason: str):
                lock = self._ticket_close_locks[int(ticket_id)]
                if lock.locked():
                    return await _safe_interaction_message(
                        interaction, embeds.warning("La fermeture de ce ticket est déjà en cours.")
                    )
                async with lock:
                    current = await self.bot.db.fetchone(
                        "SELECT status FROM tickets WHERE id=? AND guild_id=?",
                        (ticket_id, interaction.guild.id),
                    )
                    if not current or current["status"] != "ouvert":
                        return await _safe_interaction_message(interaction, embeds.warning("Ce ticket est déjà fermé."))
                    return await original_close(interaction, ticket_id, clean_reason(reason, maximum=300))
            serialized_close._sentrix_v22 = True
            tickets_cog.close_ticket = types.MethodType(serialized_close, tickets_cog)

    def _install_ai_cache(self):
        from utils import ai_service
        original_get = ai_service.get_settings
        original_update = ai_service.update_setting
        if getattr(original_get, "_sentrix_v22", False):
            return

        async def cached_get(bot, guild_id: int):
            key = (id(bot), int(guild_id))
            now_value = time.monotonic()
            cached = self._ai_settings_cache.get(key)
            if cached and ttl_is_fresh(cached[0], now_value, AI_SETTINGS_TTL):
                return copy.deepcopy(cached[1])
            value = await original_get(bot, guild_id)
            self._ai_settings_cache[key] = (now_value, copy.deepcopy(value))
            return value

        async def update_and_invalidate(bot, guild_id: int, field: str, value):
            await original_update(bot, guild_id, field, value)
            self._ai_settings_cache.pop((id(bot), int(guild_id)), None)

        cached_get._sentrix_v22 = True
        update_and_invalidate._sentrix_v22 = True
        ai_service.get_settings = cached_get
        ai_service.update_setting = update_and_invalidate

    def _install_game_cache(self):
        from utils import game_rewards
        original_get = game_rewards.get_settings
        original_set = game_rewards.set_settings
        if getattr(original_get, "_sentrix_v22", False):
            return

        async def cached_get(bot, guild_id: int):
            key = (id(bot), int(guild_id))
            now_value = time.monotonic()
            cached = self._game_settings_cache.get(key)
            if cached and ttl_is_fresh(cached[0], now_value, GAME_SETTINGS_TTL):
                return copy.deepcopy(cached[1])
            value = await original_get(bot, guild_id)
            self._game_settings_cache[key] = (now_value, copy.deepcopy(value))
            return value

        async def set_and_invalidate(bot, guild_id: int, updates: dict):
            self._game_settings_cache.pop((id(bot), int(guild_id)), None)
            value = await original_set(bot, guild_id, updates)
            self._game_settings_cache.pop((id(bot), int(guild_id)), None)
            return value

        cached_get._sentrix_v22 = True
        set_and_invalidate._sentrix_v22 = True
        game_rewards.get_settings = cached_get
        game_rewards.set_settings = set_and_invalidate
