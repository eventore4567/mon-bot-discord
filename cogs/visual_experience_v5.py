"""Fonctions visuelles utiles de SentriX, sans ancien centre V5 ni dépendance d'alias.

Ce Cog reste la dernière extension de main.py, mais il ne peut plus empêcher la finalisation
du bot parce qu'une ancienne commande `status` ou un ancien panneau a disparu.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from pathlib import Path

import discord
from discord.ext import commands

from database.db import PRIMARY_CREATOR_DISPLAY_NAME
from utils import checks, premium_style, stats_service, visual_v5

logger = logging.getLogger("bot.visual-v5")
VERSION = "5.1"
ICON_CATEGORIES = (
    "security", "moderation", "tickets", "economy", "levels", "music",
    "games", "events", "invites", "ai", "configuration", "leaderboard",
)


def _base(bot: commands.Bot, title: str, description: str = "", colour: int = 0x6C5CE7) -> discord.Embed:
    embed = discord.Embed(title=title, description=description or None, colour=discord.Colour(colour))
    embed.set_footer(text="SentriX")
    return embed


async def build_status_embed(bot: commands.Bot, guild: discord.Guild | None) -> discord.Embed:
    del guild
    latency = max(0, round(float(bot.latency) * 1000))
    database_ok = False
    try:
        row = await bot.db.fetchone("SELECT 1 AS ok")
        database_ok = bool(row and row["ok"] == 1)
    except Exception:
        pass
    services = sum((database_ok, bot.get_cog("Ai") is not None, bot.get_cog("Music") is not None))
    embed = _base(bot, "Statut", "État des services principaux.", 0x2FBF71 if services == 3 else 0xF0B232)
    embed.add_field(name="Discord", value=f"{latency} ms", inline=True)
    embed.add_field(name="Base", value="Disponible" if database_ok else "Indisponible", inline=True)
    embed.add_field(name="Services", value=f"{services}/3", inline=True)
    return embed


def build_about_embed(bot: commands.Bot) -> discord.Embed:
    members = sum(int(guild.member_count or 0) for guild in bot.guilds)
    embed = _base(bot, "À propos", "Assistant Discord pour protéger, configurer et animer un serveur.")
    embed.add_field(name="Version", value=VERSION, inline=True)
    embed.add_field(name="Créateur", value=PRIMARY_CREATOR_DISPLAY_NAME, inline=True)
    embed.add_field(name="Serveurs", value=premium_style.format_number(len(bot.guilds)), inline=True)
    embed.add_field(name="Membres", value=premium_style.format_number(members), inline=True)
    return embed


def build_updates_embed(bot: commands.Bot) -> discord.Embed:
    del bot
    return _base(
        None,
        "Nouveautés",
        "Interface simplifiée, aide recherchable, catalogue slash nettoyé et runtime unifié.",
    )


class VisualExperienceV5(commands.Cog, name="VisualExperienceV5"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self._patch_status()
        self._patch_changelog()

    def _patch_status(self):
        command = self.bot.get_command("bot-status") or self.bot.get_command("status")
        if command is None or getattr(command, "_sentrix_v5_status", False):
            return
        original_params = command.params.copy()

        async def callback(_cog, ctx: commands.Context):
            await ctx.send(embed=await build_status_embed(self.bot, ctx.guild))

        command.callback = functools.wraps(command.callback)(callback)
        command.params = original_params
        command._sentrix_v5_status = True

    def _patch_changelog(self):
        command = self.bot.get_command("changelog")
        if command is None or getattr(command, "_sentrix_v5_changelog", False):
            return
        original_params = command.params.copy()

        async def callback(_cog, ctx: commands.Context):
            await ctx.send(embed=build_updates_embed(self.bot))

        command.callback = functools.wraps(command.callback)(callback)
        command.params = original_params
        command._sentrix_v5_changelog = True

    @commands.command(name="about")
    async def about_command(self, ctx: commands.Context):
        await ctx.send(embed=build_about_embed(self.bot))

    @commands.command(name="design-theme", aliases=["theme-design"])
    @commands.guild_only()
    @checks.is_owner_or_admin_for("configuration")
    async def design_theme(self, ctx: commands.Context, preset: str | None = None):
        if not preset:
            choices = ", ".join(visual_v5.THEME_PRESETS)
            return await ctx.send(embed=_base(self.bot, "Thèmes", f"Choix disponibles : `{choices}`."))
        resolved = visual_v5.resolve_theme(preset)
        if resolved is None:
            choices = ", ".join(visual_v5.THEME_PRESETS)
            return await ctx.send(embed=_base(self.bot, "Thème introuvable", f"Choisis : `{choices}`.", 0xED4245))
        await self.bot.db.set_design_settings(ctx.guild.id, visual_v5.theme_settings(resolved))
        label = visual_v5.THEME_PRESETS[resolved]["label"]
        await ctx.send(embed=_base(self.bot, "Thème enregistré", f"Thème actif : **{label}**.", 0x2FBF71))

    @commands.command(name="profile-card", aliases=["card"])
    @commands.guild_only()
    async def profile_card(self, ctx: commands.Context, member: discord.Member | None = None):
        member = member or ctx.author
        permissions = ctx.channel.permissions_for(ctx.guild.me)
        if not permissions.attach_files:
            return await ctx.send(embed=_base(self.bot, "Permission requise", "Ajoute **Joindre des fichiers** au rôle du bot.", 0xED4245))

        loading = await ctx.send(embed=_base(self.bot, "Carte de profil", "Préparation en cours."))
        try:
            buffer = await asyncio.wait_for(self._render_profile(ctx.guild, member), timeout=15)
        except Exception:
            logger.exception("Rendu de la carte de profil impossible.")
            return await loading.edit(content=None, embed=_base(self.bot, "Carte indisponible", "Réessaie dans quelques instants.", 0xED4245))

        file = discord.File(buffer, filename="sentrix-profile.png")
        embed = _base(self.bot, "Carte de profil", f"Profil de **{member.display_name}**")
        embed.set_image(url="attachment://sentrix-profile.png")
        try:
            await ctx.channel.send(content=None, embed=embed, file=file)
            try:
                await loading.delete()
            except discord.HTTPException:
                await loading.edit(content=None, embed=_base(self.bot, "Carte prête", "La carte est affichée ci-dessous."))
        except (discord.Forbidden, discord.HTTPException):
            await loading.edit(content=None, embed=_base(self.bot, "Envoi impossible", "Vérifie **Joindre des fichiers** et **Intégrer des liens**.", 0xED4245))

    async def _render_profile(self, guild: discord.Guild, member: discord.Member):
        try:
            stats = await stats_service.get_member_statistics(self.bot, guild, member)
        except Exception:
            stats = {
                "current_level": 0, "current_level_xp": 0, "required_xp": 100,
                "rank": None, "is_ranked": False, "message_count": 0, "total_money": 0,
            }
        try:
            settings = await self.bot.db.get_design_settings(guild.id)
        except Exception:
            settings = visual_v5.theme_settings("sentrix")
        return await visual_v5.render_member_card(member, guild, stats, settings)

    @commands.command(name="iconsetup", aliases=["icons-setup"])
    @commands.guild_only()
    @checks.is_owner_or_admin_for("configuration")
    async def iconsetup(self, ctx: commands.Context, category: str = "all"):
        if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
            return await ctx.send(embed=_base(self.bot, "Permission requise", "Donne au bot **Gérer les expressions**.", 0xED4245))
        selected = list(ICON_CATEGORIES) if category.casefold() == "all" else [category.casefold()]
        selected = [item for item in selected if item in ICON_CATEGORIES]
        if not selected:
            return await ctx.send(embed=_base(self.bot, "Catégorie inconnue", f"Choisis : `{', '.join(ICON_CATEGORIES)}` ou `all`."))

        existing = {emoji.name for emoji in ctx.guild.emojis}
        created = skipped = failed = 0
        for name in selected:
            emoji_name = f"sx_{name}"
            if emoji_name in existing:
                skipped += 1
                continue
            path = Path(visual_v5.ASSET_DIR) / f"{name}.png"
            try:
                data = await asyncio.to_thread(path.read_bytes)
                await ctx.guild.create_custom_emoji(name=emoji_name, image=data, reason="Pack SentriX")
                created += 1
            except (OSError, discord.HTTPException):
                failed += 1
        await ctx.send(embed=_base(
            self.bot,
            "Icônes",
            f"Créées : **{created}**\nDéjà présentes : **{skipped}**\nÉchecs : **{failed}**",
            0x2FBF71 if failed == 0 else 0xF0B232,
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(VisualExperienceV5(bot))
    # Les commandes propres à ce Cog sont les seules exigences. Un ancien alias comme
    # `status` ne peut plus bloquer la finalisation de tout SentriX.
    required = ("about", "design-theme", "profile-card", "iconsetup")
    missing = [name for name in required if bot.get_command(name) is None]
    if missing:
        raise RuntimeError("Commandes visuelles non enregistrées : " + ", ".join(missing))
