"""SentriX V3.1 — expérience interactive visible dans Discord.

Complète community_v3 sans créer une nouvelle surface de commandes :
- +profile devient un hub à boutons (profil, missions, saison, succès, classements) ;
- classement mensuel de saison accessible depuis le profil ;
- notifications de missions plus lisibles avec progression de saison ;
- tickets : topic d'état EN ATTENTE / PRIS EN CHARGE + priorité ;
- réponses +ai : boutons « Plus simple » et « Plan d'action ».
"""
from __future__ import annotations

import functools
import logging
import types
from typing import Any

import discord
from discord.ext import commands

from utils import design_system, embeds, stats_service
from utils import sentrix_panels as panels
from . import community_v3

logger = logging.getLogger("bot.community-v31")


def _bar(current: int, target: int, blocks: int = 12) -> str:
    if target <= 0:
        return "█" * blocks
    ratio = max(0.0, min(1.0, float(current) / float(target)))
    filled = round(ratio * blocks)
    return "█" * filled + "░" * (blocks - filled)


def achievement_catalog(stats: dict[str, Any], progression: dict[str, Any]) -> list[dict[str, Any]]:
    """Catalogue stable des succès V3.1, utilisé par l'UI et les tests."""
    return [
        {"name": "📈 En progression", "unlocked": int(stats.get("current_level", 0)) >= 5, "hint": "Atteindre le niveau 5"},
        {"name": "💬 Pilier du serveur", "unlocked": int(stats.get("message_count", 0)) >= 1000, "hint": "Envoyer 1 000 messages"},
        {"name": "🎙️ Habitué du vocal", "unlocked": int(stats.get("voice_time", 0)) >= 10 * 3600, "hint": "Passer 10 h en vocal"},
        {"name": "💰 Entrepreneur", "unlocked": int(stats.get("total_money", 0)) >= 10_000, "hint": "Posséder 10 000 en économie"},
        {"name": "⭐ Apprécié", "unlocked": int(stats.get("reputation", 0)) >= 10, "hint": "Obtenir 10 points de réputation"},
        {"name": "🔥 Semaine parfaite", "unlocked": int(progression.get("longest_streak", 0)) >= 7, "hint": "Atteindre 7 jours de streak"},
        {"name": "🏆 Compétiteur de saison", "unlocked": int(progression.get("season_xp", 0)) >= 1500, "hint": "Gagner 1 500 XP de saison"},
        {"name": "💎 Élite de saison", "unlocked": int(progression.get("season_xp", 0)) >= 3000, "hint": "Gagner 3 000 XP de saison"},
    ]


def ticket_topic(ticket_id: int, priority: str | None, claimant: str | None = None) -> str:
    priority_text = "🔴 PRIORITÉ HAUTE" if str(priority or "").casefold() == "haute" else "⚪ Priorité normale"
    status = f"🟢 PRIS EN CHARGE • {claimant}" if claimant else "🟡 EN ATTENTE DU STAFF"
    return f"SentriX • Ticket #{int(ticket_id)} • {priority_text} • {status}"[:1024]


async def _season_rank(bot: commands.Bot, guild_id: int, user_id: int, season_id: str, season_xp: int) -> int:
    row = await bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM member_engagement "
        "WHERE guild_id=? AND season_id=? AND season_xp>?",
        (guild_id, season_id, int(season_xp)),
    )
    return int(row["n"] if row else 0) + 1


async def _season_top(bot: commands.Bot, guild: discord.Guild, season_id: str, limit: int = 10) -> list[str]:
    rows = await bot.db.fetchall(
        "SELECT user_id,season_xp FROM member_engagement "
        "WHERE guild_id=? AND season_id=? AND season_xp>0 "
        "ORDER BY season_xp DESC,user_id ASC LIMIT ?",
        (guild.id, season_id, int(limit)),
    )
    lines: list[str] = []
    rank = 0
    for row in rows:
        member = guild.get_member(int(row["user_id"]))
        if member is not None and member.bot:
            continue
        rank += 1
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**{rank}.**")
        name = member.display_name if member else f"Utilisateur {row['user_id']}"
        lines.append(f"{medal} {name} — **{stats_service.format_number(row['season_xp'])} XP**")
    return lines


async def _profile_snapshot(bot: commands.Bot, guild: discord.Guild, member: discord.Member) -> dict[str, Any]:
    stats = await stats_service.get_member_statistics(bot, guild, member)
    progression = await community_v3.get_progression(bot, guild.id, member.id)
    settings = await bot.db.get_stats_settings(guild.id)
    design = await bot.db.get_design_settings(guild.id)
    bio_row = await bot.db.fetchone(
        "SELECT bio FROM profiles WHERE guild_id=? AND user_id=?",
        (guild.id, member.id),
    )
    ranks = await stats_service.get_category_ranks(bot, guild.id, stats)
    season_rank = await _season_rank(
        bot,
        guild.id,
        member.id,
        str(progression["season_id"]),
        int(progression["season_xp"]),
    )
    return {
        "stats": stats,
        "progression": progression,
        "settings": settings,
        "design": design,
        "bio": bio_row["bio"] if bio_row and bio_row["bio"] else None,
        "ranks": ranks,
        "season_rank": season_rank,
    }


def _profile_embed_base(member: discord.Member, data: dict[str, Any], title: str, description: str) -> discord.Embed:
    design = data["design"]
    style = design_system.CATEGORY_STYLES["levels"]
    return design_system.create_embed(
        title=title,
        description=description,
        colour=design.get("primary_color", style["colour"]),
        user=member if design.get("show_avatars", True) else None,
        thumbnail=member.display_avatar.url if design.get("show_avatars", True) else None,
        footer=design.get("footer") or "SentriX • Profil interactif",
    )


async def build_profile_page(
    bot: commands.Bot,
    guild: discord.Guild,
    member: discord.Member,
    author_id: int,
    page: str,
) -> discord.Embed:
    data = await _profile_snapshot(bot, guild, member)
    stats = data["stats"]
    progression = data["progression"]
    settings = data["settings"]
    eco_emoji = settings.get("economy_emoji", "🪙")

    if page == "missions":
        embed = _profile_embed_base(
            member,
            data,
            f"🎯 Missions de {member.display_name}",
            f"Missions du **{community_v3.current_day()}** • elles changent chaque jour.",
        )
        if member.id != author_id:
            embed.description = "Les missions quotidiennes personnelles sont visibles uniquement par leur propriétaire."
            return embed
        total_possible = 0
        total_done = 0
        for mission in progression["missions"]:
            total_possible += int(mission["xp"])
            if mission["done"]:
                total_done += int(mission["xp"])
            icon = "✅" if mission["done"] else "▫️"
            embed.add_field(
                name=f"{icon} {mission['label']}",
                value=(
                    f"`{_bar(mission['current'], mission['target'])}` "
                    f"**{mission['current']}/{mission['target']}**\n"
                    f"Récompense : **+{mission['xp']} XP saison**"
                ),
                inline=False,
            )
        embed.add_field(
            name="Récompenses du jour",
            value=f"Déjà gagnées : **{total_done} XP** • Disponibles : **{total_possible} XP**",
            inline=False,
        )
        return embed

    if page == "season":
        top = await _season_top(bot, guild, str(progression["season_id"]))
        progress = _bar(progression["season_level_xp"], progression["season_level_target"])
        embed = _profile_embed_base(
            member,
            data,
            f"🏆 Saison {community_v3.season_label(progression['season_id'])}",
            f"{progression['tier']} • classement personnel **#{data['season_rank']}**",
        )
        embed.add_field(
            name=f"Niveau de saison {progression['season_level']}",
            value=(
                f"`{progress}` **{progression['season_level_xp']}/{progression['season_level_target']} XP**\n"
                f"Total saison : **{stats_service.format_number(progression['season_xp'])} XP**"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏅 Top saison du serveur",
            value="\n".join(top) if top else "Aucun joueur classé pour le moment.",
            inline=False,
        )
        return embed

    if page == "achievements":
        catalog = achievement_catalog(stats, progression)
        unlocked = sum(1 for item in catalog if item["unlocked"])
        embed = _profile_embed_base(
            member,
            data,
            f"🏅 Succès de {member.display_name}",
            f"**{unlocked}/{len(catalog)}** succès débloqués.",
        )
        lines = []
        for item in catalog:
            icon = "✅" if item["unlocked"] else "🔒"
            lines.append(f"{icon} **{item['name']}** — {item['hint']}")
        embed.add_field(name="Collection", value="\n".join(lines), inline=False)
        return embed

    if page == "rankings":
        ranks = data["ranks"]
        embed = _profile_embed_base(
            member,
            data,
            f"📊 Classements de {member.display_name}",
            "Position du membre dans les principaux classements du serveur.",
        )
        values = (
            ("📈 XP / Niveau", ranks.get("xp_rank")),
            ("💬 Messages", ranks.get("message_rank")),
            ("🎙️ Vocal", ranks.get("voice_rank")),
            ("💰 Économie", ranks.get("economy_rank")),
            ("⭐ Réputation", ranks.get("reputation_rank")),
            ("🏆 Saison", data["season_rank"]),
        )
        for label, rank in values:
            embed.add_field(name=label, value=f"**#{rank}**" if rank else "Non classé", inline=True)
        return embed

    progress = _bar(progression["season_level_xp"], progression["season_level_target"])
    embed = _profile_embed_base(
        member,
        data,
        f"🪪 {member.display_name} — Profil SentriX",
        (
            f"{member.mention} • Niveau **{stats['current_level']}**"
            + (f" • Rang XP **#{stats['rank']}**" if stats["is_ranked"] else " • Non classé")
            + f"\n{progression['tier']} • Saison **#{data['season_rank']}**"
        ),
    )
    embed.add_field(name="📈 Niveau", value=f"**{stats['current_level']}**", inline=True)
    embed.add_field(name="💬 Messages", value=stats_service.format_number(stats["message_count"]), inline=True)
    embed.add_field(name="🎙️ Vocal", value=stats_service.format_duration(stats["voice_time"]), inline=True)
    if settings.get("show_economy", True):
        embed.add_field(
            name="💰 Économie",
            value=(
                f"{stats_service.format_number(stats['wallet'])} {eco_emoji} cash\n"
                f"{stats_service.format_number(stats['bank'])} 🏦 banque"
            ),
            inline=True,
        )
    if settings.get("show_reputation", True):
        embed.add_field(name="⭐ Réputation", value=f"**{stats_service.format_number(stats['reputation'])}**", inline=True)
    embed.add_field(
        name="🔥 Streak",
        value=f"**{progression['daily_streak']} j** • record **{progression['longest_streak']} j**",
        inline=True,
    )
    embed.add_field(
        name=f"🏆 Saison • niveau {progression['season_level']}",
        value=(
            f"`{progress}` **{progression['season_level_xp']}/{progression['season_level_target']} XP**\n"
            f"Total : **{stats_service.format_number(progression['season_xp'])} XP**"
        ),
        inline=False,
    )
    unlocked = [item["name"] for item in achievement_catalog(stats, progression) if item["unlocked"]]
    embed.add_field(name="🏅 Succès récents", value=" • ".join(unlocked[-4:]) if unlocked else "Aucun succès débloqué.", inline=False)
    embed.add_field(
        name="📝 Bio",
        value=data["bio"] or "Aucune bio définie — utilise `+set-bio` pour en ajouter une.",
        inline=False,
    )
    return embed


class ProfileHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, member: discord.Member, author_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.member = member
        self.author_id = int(author_id)
        self.message: discord.Message | None = None
        if member.id != self.author_id:
            self.missions.disabled = True
        self._activate("overview")

    def _activate(self, page: str) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.style = discord.ButtonStyle.primary if child.custom_id == f"sentrix-profile:{page}" else discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            'Ce profil interactif appartient à la personne qui a lancé la commande. Utilisez `+profile` pour ouvrir le tien.',
            ephemeral=True,
        )
        return False

    async def _show(self, interaction: discord.Interaction, page: str) -> None:
        embed = await build_profile_page(self.bot, self.guild, self.member, self.author_id, page)
        self._activate(page)
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(embed), self))

    @discord.ui.button(label="Profil", emoji="🪪", style=discord.ButtonStyle.primary, custom_id="sentrix-profile:overview", row=0)
    async def overview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "overview")

    @discord.ui.button(label="Missions", emoji="🎯", style=discord.ButtonStyle.secondary, custom_id="sentrix-profile:missions", row=0)
    async def missions(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "missions")

    @discord.ui.button(label="Saison", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="sentrix-profile:season", row=0)
    async def season(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "season")

    @discord.ui.button(label="Succès", emoji="🏅", style=discord.ButtonStyle.secondary, custom_id="sentrix-profile:achievements", row=1)
    async def achievements(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "achievements")

    @discord.ui.button(label="Classements", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="sentrix-profile:rankings", row=1)
    async def rankings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "rankings")

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        logger.exception("Erreur profil interactif V3.1", exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Impossible de charger cette page pour le moment.", ephemeral=True)
            else:
                await interaction.response.send_message("Impossible de charger cette page pour le moment.", ephemeral=True)
        except discord.HTTPException:
            pass


def _replace_callback(command: commands.Command | None, callback, marker: str) -> bool:
    if command is None or getattr(command, marker, False):
        return False
    params = command.params.copy()
    callback = functools.wraps(command.callback)(callback)
    command.callback = callback
    command.params = params
    setattr(command, marker, True)
    return True


def _install_interactive_profile(bot: commands.Bot) -> None:
    command = bot.get_command("profile")
    if command is None:
        return

    async def interactive_profile(cog, ctx: commands.Context, membre: discord.Member = None):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande fonctionne uniquement sur un serveur.')))
        if ctx.interaction:
            await ctx.defer()
        member = membre or ctx.author
        view = ProfileHubView(bot, ctx.guild, member, ctx.author.id)
        embed = await build_profile_page(bot, ctx.guild, member, ctx.author.id, "overview")
        message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view))
        view.message = message

    _replace_callback(command, interactive_profile, "_sentrix_v31_interactive_profile")


async def _set_ticket_topic(channel, ticket_id: int, priority: str | None, claimant: str | None = None) -> None:
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.edit(topic=ticket_topic(ticket_id, priority, claimant), reason="SentriX : état du ticket")
    except discord.HTTPException:
        pass


def _install_ticket_status(bot: commands.Bot) -> None:
    tickets = bot.get_cog("Tickets")
    if tickets is None or getattr(tickets, "_sentrix_v31_status", False):
        return

    original_create = tickets.create_ticket
    original_claim = tickets.btn_claim
    original_unclaim = tickets.btn_unclaim

    async def create_with_status(this, interaction: discord.Interaction, ticket_type, answers: list):
        result = await original_create(interaction, ticket_type, answers)
        if interaction.guild and interaction.user:
            row = await bot.db.fetchone(
                "SELECT id,channel_id,priority FROM tickets WHERE guild_id=? AND user_id=? AND type_id=? AND status='ouvert' ORDER BY id DESC LIMIT 1",
                (interaction.guild.id, interaction.user.id, ticket_type["id"]),
            )
            if row:
                channel = interaction.guild.get_channel(int(row["channel_id"]))
                await _set_ticket_topic(channel, int(row["id"]), row["priority"], None)
        return result

    async def claim_with_status(this, interaction: discord.Interaction, ticket):
        result = await original_claim(interaction, ticket)
        await _set_ticket_topic(
            interaction.channel,
            int(ticket["id"]),
            ticket["priority"],
            getattr(interaction.user, "display_name", str(interaction.user)),
        )
        return result

    async def unclaim_with_status(this, interaction: discord.Interaction, ticket):
        result = await original_unclaim(interaction, ticket)
        await _set_ticket_topic(interaction.channel, int(ticket["id"]), ticket["priority"], None)
        return result

    async def transfer_with_status(this, interaction: discord.Interaction, ticket):
        select = discord.ui.UserSelect(placeholder="🔀 Transférer à un membre du staff")
        view = discord.ui.View(timeout=60)

        async def cb(inter: discord.Interaction):
            member = select.values[0]
            await bot.db.execute("UPDATE tickets SET claimed_by = ? WHERE id = ?", (member.id, ticket["id"]))
            await inter.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
            await _set_ticket_topic(inter.channel, int(ticket["id"]), ticket["priority"], getattr(member, "display_name", str(member)))
            await panels.envoyer(inter.response, panels.depuis_embed(embeds.success(f'🔀 Ticket transféré à {member.mention}.')))

        select.callback = cb
        view.add_item(select)
        await interaction.response.send_message("À quel membre du staff transférer ce ticket ?", view=view, ephemeral=True)

    tickets.create_ticket = types.MethodType(create_with_status, tickets)
    tickets.btn_claim = types.MethodType(claim_with_status, tickets)
    tickets.btn_unclaim = types.MethodType(unclaim_with_status, tickets)
    tickets.btn_transfer = types.MethodType(transfer_with_status, tickets)
    tickets._sentrix_v31_status = True


def _install_ai_quick_actions(bot: commands.Bot) -> None:
    try:
        from . import ai as ai_module
    except Exception:
        return
    base = ai_module.AiResponseView
    if getattr(base, "_sentrix_v31_quick_actions", False):
        return

    class EnhancedAiResponseView(base):
        _sentrix_v31_quick_actions = True

        @discord.ui.button(label="Plus simple", style=discord.ButtonStyle.secondary, emoji="🧩", row=1)
        async def simpler(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self._regenerate(
                interaction,
                "\n\nRéexplique la réponse avec des mots très simples, des phrases courtes et un exemple concret si utile.",
            )

        @discord.ui.button(label="Plan d'action", style=discord.ButtonStyle.success, emoji="✅", row=1)
        async def action_plan(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self._regenerate(
                interaction,
                "\n\nTransforme la réponse en plan d'action concret et court, sous forme d'étapes à suivre dans l'ordre.",
            )

    ai_module.AiResponseView = EnhancedAiResponseView
    ai_cog = bot.get_cog("Ai")
    if ai_cog is not None:
        ai_cog._sentrix_v31_quick_actions = True


def _install_mission_reward_card(bot: commands.Bot) -> None:
    if getattr(community_v3._notify_mission_rewards, "_sentrix_v31_reward_card", False):
        return

    async def premium_reward(ctx: commands.Context, rewards: list[tuple[str, int]]) -> None:
        if not rewards or ctx.guild is None:
            return
        progression = await community_v3.get_progression(bot, ctx.guild.id, ctx.author.id)
        total = sum(xp for _, xp in rewards)
        lines = "\n".join(f"✅ {label} → **+{xp} XP**" for label, xp in rewards)
        embed = embeds.success(
            f"{lines}\n\n**+{total} XP saison** • Total : **{stats_service.format_number(progression['season_xp'])} XP**\nRang : {progression['tier']} • Niveau de saison **{progression['season_level']}**\n\nUtilisez `+profile` puis **Missions** pour voir la suite.",
            title="🎯 Mission terminée",
        )
        try:
            await panels.envoyer(ctx, panels.depuis_embed(embed))
        except discord.HTTPException:
            pass

    premium_reward._sentrix_v31_reward_card = True
    community_v3._notify_mission_rewards = premium_reward


def install(bot: commands.Bot) -> None:
    """Installe les améliorations V3.1 de façon idempotente."""
    if getattr(bot, "_sentrix_community_v31_installed", False):
        _install_interactive_profile(bot)
        _install_ticket_status(bot)
        _install_ai_quick_actions(bot)
        _install_mission_reward_card(bot)
        return

    _install_interactive_profile(bot)
    _install_ticket_status(bot)
    _install_ai_quick_actions(bot)
    _install_mission_reward_card(bot)

    async def ready_listener():
        _install_interactive_profile(bot)
        _install_ticket_status(bot)
        _install_ai_quick_actions(bot)
        _install_mission_reward_card(bot)

    bot.add_listener(ready_listener, "on_ready")
    bot._sentrix_community_v31_installed = True
    bot._sentrix_community_v31_state = {
        "ready": True,
        "features": (
            "interactive_profile",
            "season_leaderboard",
            "achievement_collection",
            "ticket_live_status",
            "ai_quick_actions",
            "premium_mission_rewards",
        ),
    }
    logger.info("SentriX V3.1 installé : profil interactif, saison, tickets live, actions IA et récompenses.")
