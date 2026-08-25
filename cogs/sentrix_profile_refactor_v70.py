"""Profil SentriX V70 — présentation compacte sans modifier les statistiques métier."""
from __future__ import annotations

import functools

import discord
from discord.ext import commands

from utils import embeds, stats_service


def _fmt_date(value) -> str:
    if value is None:
        return "Non disponible"
    try:
        return value.astimezone().strftime("%d/%m/%Y")
    except Exception:
        return "Non disponible"


def _main_role(member: discord.Member) -> str:
    role = member.top_role
    if role is None or role.id == member.guild.default_role.id:
        return "Aucun rôle principal"
    return role.mention


def install(bot: commands.Bot) -> None:
    command = bot.get_command("profile")
    if command is None or getattr(command, "_sentrix_profile_v70", False):
        return

    original = command.callback
    original_params = command.params.copy()

    async def profile_v70(_cog, ctx: commands.Context, membre: discord.Member | None = None):
        if ctx.interaction:
            await ctx.defer()
        member = membre or ctx.author
        if not isinstance(member, discord.Member) or ctx.guild is None:
            return await ctx.send(embed=embeds.error("Cette commande doit être utilisée dans un serveur."))

        try:
            stats = await stats_service.get_member_statistics(bot, ctx.guild, member)
            bio_row = await bot.db.fetchone(
                "SELECT * FROM profiles WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, member.id),
            )
        except Exception:
            return await ctx.send(embed=embeds.error("Impossible de préparer ce profil pour le moment."))

        profile = embeds.profile_embed(
            f"Profil de {member.display_name}",
            member.mention,
            thumbnail=str(member.display_avatar.url),
        )

        account = (
            f"Nom : **{discord.utils.escape_markdown(member.display_name)}**\n"
            f"ID : `{member.id}`\n"
            f"Compte créé : **{_fmt_date(member.created_at)}**"
        )
        server = (
            f"Arrivé : **{_fmt_date(stats.get('joined_at') or member.joined_at)}**\n"
            f"Rôle principal : {_main_role(member)}\n"
            f"Niveau : **{stats.get('current_level', 0)}**"
        )
        economy = (
            f"Portefeuille : **{stats_service.format_number(stats.get('wallet', 0))}**\n"
            f"Banque : **{stats_service.format_number(stats.get('bank', 0))}**\n"
            f"Total : **{stats_service.format_number(stats.get('total_money', 0))}**"
        )
        activity = (
            f"Messages : **{stats_service.format_number(stats.get('message_count', 0))}**\n"
            f"Temps vocal : **{stats_service.format_duration(stats.get('voice_time', 0))}**\n"
            f"Réputation : **{stats_service.format_number(stats.get('reputation', 0))}**"
        )

        profile.add_field(name="Compte", value=account, inline=True)
        profile.add_field(name="Serveur", value=server, inline=True)
        profile.add_field(name="Économie", value=economy, inline=True)
        profile.add_field(name="Activité", value=activity, inline=True)

        bio = str(bio_row["bio"] if bio_row and bio_row["bio"] else "").strip()
        if bio:
            # La bio est une donnée utilisateur : elle n'est jamais nettoyée d'emojis.
            profile.add_field(name="Bio", value=embeds.clip(bio, 1024), inline=False)

        return await ctx.send(embed=profile)

    profile_v70 = functools.wraps(original)(profile_v70)
    command.callback = profile_v70
    command.params = original_params
    command._sentrix_profile_v70 = True
