"""Profil SentriX sobre et lisible, inspiré des interfaces compactes de bots premium."""
from __future__ import annotations

import functools

import discord
from discord.ext import commands

from utils import premium_style, stats_service, visual_v5
from . import community_v3, community_v31

CARD_COLOUR = premium_style.COLORS["profile"]


def _fmt(value) -> str:
    return stats_service.format_number(int(value or 0))


def _rank(value) -> str:
    return f"#{value}" if value else "Non classé"


async def _snapshot(bot: commands.Bot, guild: discord.Guild, member: discord.Member):
    return await community_v31._profile_snapshot(bot, guild, member)


def _base(bot: commands.Bot, member: discord.Member, title: str, subtitle: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=subtitle or None,
        colour=discord.Colour(CARD_COLOUR),
    )
    if bot.user is not None:
        embed.set_author(name="SentriX • Profil", icon_url=bot.user.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="SentriX • Profil")
    return embed


def _badges(member: discord.Member, stats: dict, progression: dict) -> list[str]:
    """Badges calculés uniquement à partir des vraies données du membre."""
    badges: list[str] = []
    if int(stats.get("message_count", 0)) >= 1000:
        badges.append("Actif")
    if int(stats.get("wallet", 0)) + int(stats.get("bank", 0)) >= 10_000:
        badges.append("Économiste")
    if int(progression.get("season_xp", 0)) > 0:
        badges.append("Saisonnier")
    if member.guild_permissions.manage_messages or member.guild_permissions.moderate_members:
        badges.append("Staff")
    account_days = max(0, (discord.utils.utcnow() - member.created_at).days)
    if account_days >= 365:
        badges.append("Vétéran")
    return badges[:5]


async def build_page(bot: commands.Bot, guild: discord.Guild, member: discord.Member, author_id: int, page: str):
    data = await _snapshot(bot, guild, member)
    stats = data["stats"]
    progression = data["progression"]

    if page == "missions":
        embed = _base(bot, member, "Missions du jour", member.display_name)
        if member.id != author_id:
            embed.description = "Les missions personnelles ne sont visibles que par leur propriétaire."
            return embed

        missions = list(progression.get("missions") or [])[:3]
        done = sum(1 for mission in missions if mission.get("done"))
        embed.description = f"{done}/{len(missions)} terminées aujourd’hui" if missions else "Aucune mission aujourd’hui."
        for mission in missions:
            current = int(mission.get("current", 0))
            target = int(mission.get("target", 0))
            reward = int(mission.get("xp", 0))
            state = "Terminée" if mission.get("done") else f"{current}/{target}"
            embed.add_field(
                name=str(mission.get("label") or "Mission"),
                value=(
                    f"{premium_style.progress_bar(current, target, length=10)}\n"
                    f"{state} • +{reward} XP saison"
                ),
                inline=False,
            )
        return embed

    if page == "season":
        embed = _base(bot, member, "Saison", community_v3.season_label(progression["season_id"]))
        embed.add_field(
            name="Rang",
            value=f"{progression['tier']} • {_rank(data['season_rank'])}",
            inline=False,
        )
        embed.add_field(
            name="Progression",
            value=(
                f"{premium_style.progress_bar(progression['season_level_xp'], progression['season_level_target'])}\n"
                f"Niveau {progression['season_level']} • "
                f"{progression['season_level_xp']}/{progression['season_level_target']} XP\n"
                f"Total saison : {_fmt(progression['season_xp'])} XP"
            ),
            inline=False,
        )
        top = await community_v31._season_top(bot, guild, str(progression["season_id"]), limit=5)
        if top:
            # Le classement historique contient des emojis/markdown : on le réécrit sobrement.
            cleaned = []
            for index, line in enumerate(top[:5], start=1):
                text = str(line).replace("**", "")
                for token in ("🥇", "🥈", "🥉"):
                    text = text.replace(token, "")
                cleaned.append(f"{index}. {text.strip().lstrip('1234567890. ')}")
            embed.add_field(name="Top 5", value="\n".join(cleaned), inline=False)
        badges = _badges(member, stats, progression)
        embed.add_field(
            name="Badges",
            value=" • ".join(badges) if badges else "Aucun badge débloqué",
            inline=False,
        )
        return embed

    if page == "rankings":
        ranks = data["ranks"]
        embed = _base(bot, member, "Classements", member.display_name)
        embed.colour = discord.Colour(premium_style.COLORS["leaderboard"])
        lines = [
            f"Niveau : {_rank(ranks.get('xp_rank'))}",
            f"Messages : {_rank(ranks.get('message_rank'))}",
            f"Économie : {_rank(ranks.get('economy_rank'))}",
            f"Saison : {_rank(data['season_rank'])}",
        ]
        embed.description = "\n".join(lines)
        return embed

    # Vue principale : volontairement courte. Les détails sont dans les boutons.
    embed = _base(bot, member, f"Profil de {member.display_name}", data.get("bio") or "Carte membre SentriX")
    level_rank = _rank(stats.get("rank")) if stats.get("is_ranked") else "Non classé"
    embed.add_field(
        name="Progression",
        value=(
            f"{premium_style.progress_bar(progression['season_level_xp'], progression['season_level_target'])}\n"
            f"Niveau {stats['current_level']} • Rang {level_rank}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Économie",
        value=f"{_fmt(stats['wallet'])} portefeuille • {_fmt(stats['bank'])} banque",
        inline=False,
    )
    embed.add_field(
        name="Activité",
        value=(
            f"{_fmt(stats['message_count'])} messages • "
            f"{stats_service.format_duration(stats['voice_time'])} vocal • "
            f"streak {progression['daily_streak']} j"
        ),
        inline=False,
    )
    return embed


class CleanProfileView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, member: discord.Member, author_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.member = member
        self.author_id = int(author_id)
        self.message: discord.Message | None = None
        self.page = "overview"
        self._set_active("overview")

    def _set_active(self, page: str):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.style = discord.ButtonStyle.primary if child.custom_id == f"sentrix-clean-profile:{page}" else discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("Ouvre ton propre profil avec `+profile`.", ephemeral=True)
        return False

    async def _show(self, interaction: discord.Interaction, page: str):
        embed = await build_page(self.bot, self.guild, self.member, self.author_id, page)
        self.page = page
        self._set_active(page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Profil", style=discord.ButtonStyle.primary, custom_id="sentrix-clean-profile:overview")
    async def overview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "overview")

    @discord.ui.button(label="Missions", style=discord.ButtonStyle.secondary, custom_id="sentrix-clean-profile:missions")
    async def missions(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "missions")

    @discord.ui.button(label="Saison", style=discord.ButtonStyle.secondary, custom_id="sentrix-clean-profile:season")
    async def season(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "season")

    @discord.ui.button(label="Classement", style=discord.ButtonStyle.secondary, custom_id="sentrix-clean-profile:rankings")
    async def rankings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "rankings")

    @discord.ui.button(label="Carte", style=discord.ButtonStyle.primary, custom_id="sentrix-clean-profile:card", row=1)
    async def card(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await _snapshot(self.bot, self.guild, self.member)
            settings = await self.bot.db.get_design_settings(self.guild.id)
            buffer = await visual_v5.render_member_card(
                self.member,
                self.guild,
                data["stats"],
                settings,
            )
            file = discord.File(buffer, filename="sentrix-profile.png")
            embed = _base(self.bot, self.member, "Carte de profil", self.member.display_name)
            embed.set_image(url="attachment://sentrix-profile.png")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
        except Exception:
            await interaction.followup.send(
                "La carte est temporairement indisponible. Réessaie dans quelques instants.",
                ephemeral=True,
            )

    @discord.ui.button(label="Actualiser", style=discord.ButtonStyle.secondary, custom_id="sentrix-clean-profile:refresh", row=1)
    async def refresh(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._show(interaction, self.page)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, custom_id="sentrix-clean-profile:close", row=1)
    async def close(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def install(bot: commands.Bot) -> None:
    command = bot.get_command("profile")
    if command is None or getattr(command, "_sentrix_oxyde_profile", False):
        return

    # Utilise le transport discord.py brut pour préserver exactement cette carte, sans que
    # premium_style_runtime ne rajoute des titres/footers/champs historiques.
    try:
        from . import premium_style_runtime
        raw_context_send = premium_style_runtime._ORIGINALS.get("context_send") or commands.Context.send
    except Exception:
        raw_context_send = commands.Context.send

    async def profile_callback(cog, ctx: commands.Context, membre: discord.Member = None):
        if ctx.guild is None:
            return await ctx.send("Cette commande fonctionne uniquement sur un serveur.")
        member = membre or ctx.author
        view = CleanProfileView(bot, ctx.guild, member, ctx.author.id)
        embed = await build_page(bot, ctx.guild, member, ctx.author.id, "overview")
        message = await raw_context_send(ctx, embed=embed, view=view)
        view.message = message

    params = command.params.copy()
    profile_callback = functools.wraps(command.callback)(profile_callback)
    command.callback = profile_callback
    command.params = params
    command._sentrix_oxyde_profile = True
