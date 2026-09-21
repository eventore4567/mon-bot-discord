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
import time
import types
from collections import defaultdict

import discord
from discord.ext import commands

from services import economy as economy_service
from utils import embeds, stats_service
from utils import sentrix_panels as panels
from utils.v22_rules import (
    clean_reason,
    parse_friendly_amount,
    parse_friendly_duration,
    ttl_is_fresh,
)

logger = logging.getLogger("bot.sentrix-v22")

AI_SETTINGS_TTL = 20.0
GAME_SETTINGS_TTL = 20.0
TICKET_BUTTON_SETTINGS_TTL = 15.0


async def _safe_interaction_message(interaction: discord.Interaction, embed: discord.Embed):
    try:
        if interaction.response.is_done():
            await panels.envoyer(interaction.followup, panels.depuis_embed(embed), ephemere=True)
        else:
            await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)
    except discord.HTTPException:
        pass


class SentriXV22(commands.Cog):
    """Runtime de durcissement. Zéro nouvelle commande publique."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ticket_open_locks: dict[tuple[int, int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ticket_create_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ticket_close_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
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
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
            if membre.id == ctx.author.id:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas vous voler vous-même.')))
            if membre.bot:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas voler un bot.')))

            kind, value = await economy_service.atomic_rob(self.bot.db, ctx.guild.id, ctx.author.id, membre.id)
            if kind == "cooldown":
                minutes = max(1, (int(value) + 59) // 60)
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Vous devez attendre encore **{minutes} min** avant de retenter un vol.')))
            if kind == "poor":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"{membre.display_name} n'a pas assez d'argent liquide à voler.")))
            if kind == "retry":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Le solde de la cible vient de changer. Réessayez.')))
            if kind == "success":
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Vous avez volé **{stats_service.format_number(value)} 🪙** à {membre.display_name}.')))
            if kind == "failed":
                if value:
                    return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Vous avez été attrapé : **{stats_service.format_number(value)} 🪙** d'amende.")))
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous avez été attrapé, mais votre portefeuille était déjà vide.')))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Le vol n'a pas pu être traité. Réessayez.")))

        self._replace_command_callback(command, atomic_rob, "_sentrix_v22_atomic_rob")

    def _install_moderation_hardening(self):
        """Borne le MP de sanction historique à 2,5 s.

        Les remplacements de callbacks (unmute/warn/ban/kick/unban/tempban/mute)
        qui vivaient ici ont été supprimés : leurs fermetures partageaient la
        variable ``original`` réassignée à chaque boucle, si bien que ``+unmute``
        et ``+warn`` exécutaient en production le callback de ``mute`` (dernier
        assigné). Le nettoyage de la raison (``clean_reason``) est désormais fait
        par cogs/moderation.py lui-même.
        """
        moderation = self.bot.get_cog("Moderation")
        if moderation is None:
            return

        original_dm = getattr(moderation, "_send_sanction_dm", None)
        if original_dm is not None and not getattr(original_dm, "_sentrix_v22", False):
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

        # Claim / unclaim / close are already provided by ticket_claim_security.py.
        # That canonical runtime owns permission changes, compare-and-set DB updates,
        # transcript/log behavior and rollback when Discord permission edits fail.
        # V2.2 used to replace those methods again here with narrower callbacks,
        # silently discarding part of the canonical behavior because V2.2 loads later.
        # Keep only the cache + start/create serialization above; do not re-patch
        # claim, unclaim or close at instance level.
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
