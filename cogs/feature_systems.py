"""Interrupteurs globaux Économie / Niveaux pour chaque serveur SentriX.

Cette couche est volontairement indépendante des gros cogs Economy/Levels : elle peut être
installée avant eux puis repassée après chaque extension. Elle :
- bloque toutes les commandes du Cog Economy quand l'économie est coupée ;
- bloque les commandes XP/niveaux quand les niveaux sont coupés ;
- empêche les achats depuis les anciens panneaux persistants de boutique ;
- empêche les gains d'argent externes (+ mini-jeux) ;
- empêche tout nouveau gain d'XP sans arrêter les statistiques de messages ;
- conserve toutes les données pour une réactivation ultérieure.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, embeds
from utils.system_features import ensure_feature_table, get_system_features, is_system_enabled, set_system_feature

logger = logging.getLogger("bot.feature-systems")

_LEVEL_COMMAND_ROOTS = {
    "level", "rank", "leaderboard-levels", "level-roles", "levelroles",
    "set-level-role", "remove-level-role", "set-xp", "add-xp", "reset-levels",
    "levelcheck", "levelrepair",
}


def _is_level_command(command: commands.Command) -> bool:
    name = str(getattr(command, "qualified_name", "") or getattr(command, "name", "")).casefold().strip()
    root = name.split()[0] if name else ""
    return root in _LEVEL_COMMAND_ROOTS or "level" in root or root.endswith("-xp") or root.startswith("xp-")


def _state_from_text(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if normalized in {"on", "oui", "yes", "1", "true", "actif", "active", "activer", "enable", "enabled"}:
        return True
    if normalized in {"off", "non", "no", "0", "false", "inactif", "inactive", "désactiver", "desactiver", "disable", "disabled"}:
        return False
    return None


async def _send_interaction_disabled(interaction: discord.Interaction, text: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


class SystemFeatureCommands(commands.Cog, name="SystemFeatures"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def bot_check(self, ctx: commands.Context) -> bool:
        """Check global : protège les commandes préfixées ET les hybrid slash."""
        if ctx.guild is None or ctx.command is None:
            return True

        if getattr(ctx.command, "cog_name", None) == "Economy":
            if not await is_system_enabled(self.bot.db, ctx.guild.id, "economy"):
                raise checks.BotPermissionError(
                    "Le **système d'argent est désactivé** sur ce serveur. Les soldes, récompenses et boutiques sont actuellement bloqués."
                )

        if _is_level_command(ctx.command):
            if not await is_system_enabled(self.bot.db, ctx.guild.id, "levels"):
                raise checks.BotPermissionError(
                    "Le **système de niveaux est désactivé** sur ce serveur. Aucun XP ni palier de niveau n'est actif pour le moment."
                )
        return True

    async def _show_or_set(self, ctx: commands.Context, feature: str, etat: str | None):
        if ctx.guild is None:
            return await ctx.send(embed=embeds.error("Cette commande doit être utilisée sur un serveur."))

        current = await get_system_features(self.bot.db, ctx.guild.id, fresh=True)
        key = "economy_enabled" if feature == "economy" else "levels_enabled"
        requested = _state_from_text(etat)
        if etat is not None and requested is None:
            return await ctx.send(embed=embeds.warning("Utilisez `on` ou `off`."))

        if requested is None:
            label = "argent + boutiques" if feature == "economy" else "niveaux + XP"
            state = "activé" if current[key] else "désactivé"
            return await ctx.send(embed=embeds.info(f"Le système **{label}** est actuellement **{state}**."))

        values = await set_system_feature(self.bot.db, ctx.guild.id, feature, requested)
        active = values[key]
        if feature == "economy":
            description = (
                "💰 Le système d'argent est **activé**. Soldes, récompenses et boutiques fonctionnent à nouveau."
                if active else
                "💰 Le système d'argent est **désactivé**. Les commandes économiques, les gains monétaires, les achats et toutes les boutiques sont bloqués. Les anciens soldes sont conservés."
            )
        else:
            description = (
                "📈 Le système de niveaux est **activé**. Les membres peuvent de nouveau gagner de l'XP."
                if active else
                "📈 Le système de niveaux est **désactivé**. Les gains d'XP, classements et paliers de niveau sont bloqués. Les niveaux existants sont conservés."
            )
        await ctx.send(embed=embeds.success(description) if active else embeds.info(description))

    @commands.hybrid_command(
        name="economy-system",
        aliases=["money-system", "argent-system"],
        description="Activer ou désactiver tout le système d'argent et les boutiques.",
    )
    @app_commands.describe(etat="on/off — laissez vide pour afficher l'état")
    @checks.is_owner_or_admin()
    async def economy_system(self, ctx: commands.Context, etat: str = None):
        await self._show_or_set(ctx, "economy", etat)

    @commands.hybrid_command(
        name="level-system",
        aliases=["levels-system", "niveau-system", "niveaux-system"],
        description="Activer ou désactiver tout le système de niveaux et d'XP.",
    )
    @app_commands.describe(etat="on/off — laissez vide pour afficher l'état")
    @checks.is_owner_or_admin()
    async def level_system(self, ctx: commands.Context, etat: str = None):
        await self._show_or_set(ctx, "levels", etat)


def _patch_database(bot: commands.Bot) -> None:
    """Bloque aussi les écritures monétaires venant d'autres cogs (notamment les jeux)."""
    db = bot.db
    if getattr(db, "_sentrix_feature_economy_guard", False):
        return
    db._sentrix_feature_economy_guard = True

    original_add_balance = getattr(db, "add_balance", None)
    if original_add_balance is not None:
        async def guarded_add_balance(guild_id: int, *args, **kwargs):
            if not await is_system_enabled(db, guild_id, "economy"):
                return None
            return await original_add_balance(guild_id, *args, **kwargs)
        db.add_balance = guarded_add_balance

    original_pay_member = getattr(db, "pay_member", None)
    if original_pay_member is not None:
        async def guarded_pay_member(guild_id: int, *args, **kwargs):
            if not await is_system_enabled(db, guild_id, "economy"):
                return False
            return await original_pay_member(guild_id, *args, **kwargs)
        db.pay_member = guarded_pay_member

    original_claim = getattr(db, "claim_timed_reward", None)
    if original_claim is not None:
        async def guarded_claim(guild_id: int, *args, **kwargs):
            if not await is_system_enabled(db, guild_id, "economy"):
                return False, 0
            return await original_claim(guild_id, *args, **kwargs)
        db.claim_timed_reward = guarded_claim

    original_game_reward = getattr(db, "record_game_reward", None)
    if original_game_reward is not None:
        async def guarded_game_reward(guild_id: int, *args, **kwargs):
            if await is_system_enabled(db, guild_id, "economy"):
                return await original_game_reward(guild_id, *args, **kwargs)

            # Une partie reste valide et est enregistrée, mais son crédit monétaire vaut 0.
            # Signature actuelle : guild, user, game, session, result, amount, metadata.
            mutable = list(args)
            if len(mutable) >= 5:
                mutable[4] = 0
            elif "amount" in kwargs:
                kwargs["amount"] = 0
            return await original_game_reward(guild_id, *mutable, **kwargs)
        db.record_game_reward = guarded_game_reward


def _patch_economy(bot: commands.Bot) -> None:
    cog = bot.get_cog("Economy")
    if cog is None or getattr(cog, "_sentrix_feature_guard", False):
        return
    cog._sentrix_feature_guard = True

    original = getattr(cog, "handle_shop_selection", None)
    if original is not None:
        async def guarded_shop_selection(_self, interaction: discord.Interaction, selected_value: str):
            guild_id = interaction.guild_id
            if guild_id and not await is_system_enabled(bot.db, guild_id, "economy"):
                return await _send_interaction_disabled(
                    interaction,
                    "💰 Le système d'argent est désactivé sur ce serveur : **la boutique et les achats sont bloqués**.",
                )
            return await original(interaction, selected_value)
        cog.handle_shop_selection = MethodType(guarded_shop_selection, cog)

    logger.info("Garde économie installée : commandes + boutiques + écritures monétaires.")


def _disabled_embed(system: str) -> discord.Embed:
    if system == "economy":
        return embeds.info(
            "Le système d'argent est désactivé sur ce serveur. Les anciennes données sont conservées, mais les soldes et boutiques ne sont pas actifs."
        )
    return embeds.info(
        "Le système de niveaux est désactivé sur ce serveur. Les anciens niveaux sont conservés, mais aucun nouvel XP n'est gagné."
    )


def _patch_levels(bot: commands.Bot) -> None:
    cog = bot.get_cog("Levels")
    if cog is None or getattr(cog, "_sentrix_feature_guard", False):
        return
    cog._sentrix_feature_guard = True

    original_apply = getattr(cog, "_apply_xp_delta", None)
    if original_apply is not None:
        async def guarded_apply_xp(_self, guild_id: int, user_id: int, delta: int):
            if not await is_system_enabled(bot.db, guild_id, "levels"):
                row = await bot.db.get_level(guild_id, user_id)
                if row is None:
                    return 0, 0, False
                return int(row["xp"] or 0), int(row["level"] or 0), False
            return await original_apply(guild_id, user_id, delta)
        cog._apply_xp_delta = MethodType(guarded_apply_xp, cog)

    original_level_embed = getattr(cog, "build_level_embed", None)
    if original_level_embed is not None:
        async def guarded_level_embed(_self, guild: discord.Guild, member: discord.Member, *args, **kwargs):
            if not await is_system_enabled(bot.db, guild.id, "levels"):
                return _disabled_embed("levels")
            return await original_level_embed(guild, member, *args, **kwargs)
        cog.build_level_embed = MethodType(guarded_level_embed, cog)

    original_economy_embed = getattr(cog, "build_economy_embed", None)
    if original_economy_embed is not None:
        async def guarded_economy_embed(_self, guild: discord.Guild, member: discord.Member, *args, **kwargs):
            if not await is_system_enabled(bot.db, guild.id, "economy"):
                return _disabled_embed("economy")
            return await original_economy_embed(guild, member, *args, **kwargs)
        cog.build_economy_embed = MethodType(guarded_economy_embed, cog)

    logger.info("Garde niveaux installée : XP et affichages niveau/économie respectent les interrupteurs.")


async def install(bot: commands.Bot) -> None:
    """Peut être rappelé après chaque extension ; seules les nouvelles cibles sont patchées."""
    await ensure_feature_table(bot.db)
    _patch_database(bot)

    if bot.get_cog("SystemFeatures") is None:
        await bot.add_cog(SystemFeatureCommands(bot))
        logger.info("Commandes +economy-system et +level-system chargées.")

    _patch_economy(bot)
    _patch_levels(bot)
