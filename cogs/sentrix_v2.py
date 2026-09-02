"""SentriX V2 — couche d'expérience visible au-dessus des systèmes existants.

Cette extension ne remplace ni l'économie, ni les niveaux, ni les tickets, ni la
modération. Elle les regroupe dans des hubs interactifs, ajoute une progression globale,
un check-in quotidien et un marché entre membres utilisant la monnaie/inventaire actuels.
Toutes les commandes V2 sont préfixées uniquement afin de ne pas consommer le budget slash.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

import config
from utils import checks, design_system, embeds, stats_service
from utils import sentrix_panels as panels


V2_PUBLIC_COMMANDS = frozenset({
    "home", "profilecard", "economyhub", "gamehub", "aicenter", "ticketcenter",
    "progress", "checkin", "market", "market-sell", "market-buy", "market-cancel",
})
V2_DIRECT_COMMANDS = V2_PUBLIC_COMMANDS | {"modcenter"}

GAME_GROUPS = {
    "Rapides": ("rps", "guess-number", "trivia", "math-quiz", "slots", "blackjack"),
    "Duels": ("tictactoe", "duel", "connect4", "numberduel", "reactionduel", "quizduel"),
    "Événements": ("triviastart", "wordrace", "reactionevent", "guessrace", "mathrace", "emoji-race"),
    "Aventure": ("adventure", "dungeon", "mining", "fishing", "treasure", "hunt", "explore"),
    "Profil jeux": ("gameprofile", "gamehistory", "gamestats", "gametop", "dailygames"),
}

V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_daily_checkins (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    last_day TEXT,
    streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    total_claims INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS v2_daily_claims (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    claim_day TEXT NOT NULL,
    claimed_at INTEGER NOT NULL,
    reward INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, claim_day)
);
CREATE TABLE IF NOT EXISTS v2_market_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    seller_id INTEGER NOT NULL,
    buyer_id INTEGER,
    item_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at INTEGER NOT NULL,
    sold_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_v2_market_active
ON v2_market_listings (guild_id, status, id);
"""


def _fmt(value) -> str:
    return stats_service.format_number(value)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


class InteractionContext:
    """Adaptateur minimal pour réutiliser les callbacks de modération depuis un bouton."""

    def __init__(self, interaction: discord.Interaction, command):
        self.interaction = interaction
        self.guild = interaction.guild
        self.author = interaction.user
        self.bot = interaction.client
        self.channel = interaction.channel
        self.message = interaction.message
        self.command = command
        self.invoked_with = command.name
        self.prefix = "+"

    async def defer(self, *, ephemeral: bool = False):
        if not self.interaction.response.is_done():
            await self.interaction.response.defer(ephemeral=ephemeral)

    async def send(self, content=None, **kwargs):
        kwargs.pop("reference", None)
        kwargs.pop("mention_author", None)
        if self.interaction.response.is_done():
            kwargs.setdefault("wait", True)
            return await self.interaction.followup.send(content, **kwargs)
        return await self.interaction.response.send_message(content, **kwargs)

    def typing(self):
        return self.channel.typing()


class HomeButton(discord.ui.Button):
    def __init__(self, label: str, page: str, *, row: int, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, style=style, row=row)
        self.page = page

    async def callback(self, interaction: discord.Interaction):
        view: HomeView = self.view
        builders = {
            "home": view.cog.build_home_embed,
            "profile": view.cog.build_profile_embed,
            "economy": view.cog.build_economy_embed,
            "games": view.cog.build_games_embed,
            "progress": view.cog.build_progress_embed,
            "ai": view.cog.build_ai_embed,
            "tickets": view.cog.build_ticket_embed,
        }
        if self.page == "staff":
            if not await view.cog.can_staff_interaction(interaction, "moderate_members"):
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Vous n'avez pas accès au centre staff.")), ephemere=True)
            embed = await view.cog.build_mod_embed(view.guild, view.member)
        else:
            builder = builders.get(self.page, view.cog.build_home_embed)
            embed = await builder(view.guild, view.member)
        await interaction.response.edit_message(embed=embed, view=view)


class CheckinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Check-in", style=discord.ButtonStyle.success, row=1)

    async def callback(self, interaction: discord.Interaction):
        view: HomeView = self.view
        result = await view.cog.claim_checkin(view.guild, view.member)
        if result["claimed"]:
            message = f"Check-in validé : **+{_fmt(result['reward'])}** pièces · série **{result['streak']} j**."
            embed = embeds.success(message)
        else:
            embed = embeds.warning(f"Déjà récupéré aujourd'hui · série **{result['streak']} j**.")
        await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)


class HomeView(design_system.SentriXView):
    def __init__(self, cog: "SentriXV2", guild: discord.Guild, member: discord.Member, staff: bool):
        super().__init__(author_id=member.id, allowed_staff=False, timeout=240)
        self.cog, self.guild, self.member = cog, guild, member
        self.add_item(HomeButton("Accueil", "home", row=0, style=discord.ButtonStyle.primary))
        self.add_item(HomeButton("Profil", "profile", row=0))
        self.add_item(HomeButton("Économie", "economy", row=0))
        self.add_item(HomeButton("Jeux", "games", row=0))
        self.add_item(HomeButton("Progression", "progress", row=0))
        self.add_item(HomeButton("IA", "ai", row=1))
        self.add_item(HomeButton("Tickets", "tickets", row=1))
        staff_button = HomeButton("Centre staff", "staff", row=1, style=discord.ButtonStyle.danger)
        staff_button.disabled = not staff
        self.add_item(staff_button)
        self.add_item(CheckinButton())
        self.add_item(discord.ui.Button(label="Dashboard", url=config.DASHBOARD_APP_URL, row=1))


class GameButton(discord.ui.Button):
    def __init__(self, group: str, row: int):
        super().__init__(label=group, style=discord.ButtonStyle.secondary, row=row)
        self.group = group

    async def callback(self, interaction: discord.Interaction):
        view: GameView = self.view
        names = [name for name in GAME_GROUPS[self.group] if interaction.client.get_command(name)]
        embed = await view.cog.category_embed(
            interaction.guild.id,
            "games",
            title=f"Game Hub — {self.group}",
            description=" · ".join(f"`+{name}`" for name in names) or "Aucun jeu chargé dans cette catégorie.",
            user=interaction.user,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class GameView(design_system.SentriXView):
    def __init__(self, cog: "SentriXV2", member: discord.Member):
        super().__init__(author_id=member.id, allowed_staff=False, timeout=180)
        self.cog = cog
        for i, group in enumerate(GAME_GROUPS):
            self.add_item(GameButton(group, i // 5))


class MarketView(design_system.SentriXView):
    def __init__(self, cog: "SentriXV2", member: discord.Member):
        super().__init__(author_id=member.id, allowed_staff=False, timeout=180)
        self.cog = cog

    @discord.ui.button(label="Actualiser", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(await self.cog.build_market_embed(interaction.guild, interaction.user)), self))


class MemberPicker(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Choisir un membre", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: ModView = self.view
        selected = self.values[0]
        member = selected if isinstance(selected, discord.Member) else None
        if member is None:
            try:
                member = await interaction.guild.fetch_member(selected.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Membre introuvable.')), ephemere=True)
        view.target_id = member.id
        view.sync()
        await interaction.response.edit_message(
            embed=await view.cog.build_member_mod_embed(interaction.guild, member), view=view
        )


class ModAction(discord.ui.Button):
    PERMS = {"warn": "moderate_members", "mute": "moderate_members", "ban": "ban_members"}

    def __init__(self, action: str, label: str, style):
        super().__init__(label=label, style=style, row=1, disabled=True)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        view: ModView = self.view
        if view.target_id is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning('Choisissez un membre.')), ephemere=True)
        if not await view.cog.can_staff_interaction(interaction, self.PERMS[self.action]):
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Permission insuffisante.')), ephemere=True)
        await interaction.response.send_modal(SanctionModal(view.cog, view, self.action, view.target_id))


class ModRefresh(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Actualiser", style=discord.ButtonStyle.secondary, row=1, disabled=True)

    async def callback(self, interaction: discord.Interaction):
        view: ModView = self.view
        member = interaction.guild.get_member(view.target_id) if view.target_id else None
        if member is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Membre introuvable.')), ephemere=True)
        await interaction.response.edit_message(embed=await view.cog.build_member_mod_embed(interaction.guild, member), view=view)


class ModView(design_system.SentriXView):
    def __init__(self, cog: "SentriXV2", member: discord.Member):
        super().__init__(author_id=member.id, allowed_staff=False, timeout=240)
        self.cog = cog
        self.target_id: int | None = None
        self.add_item(MemberPicker())
        self.add_item(ModAction("warn", "Warn", discord.ButtonStyle.secondary))
        self.add_item(ModAction("mute", "Mute", discord.ButtonStyle.secondary))
        self.add_item(ModAction("ban", "Ban", discord.ButtonStyle.danger))
        self.add_item(ModRefresh())

    def sync(self):
        for item in self.children:
            if isinstance(item, (ModAction, ModRefresh)):
                item.disabled = self.target_id is None


class SanctionModal(discord.ui.Modal):
    def __init__(self, cog: "SentriXV2", view: ModView, action: str, target_id: int):
        super().__init__(title={"warn": "Avertir", "mute": "Mute", "ban": "Bannir"}[action])
        self.cog, self.view_ref, self.action, self.target_id = cog, view, action, target_id
        self.reason = discord.ui.TextInput(label="Raison", style=discord.TextStyle.paragraph, max_length=800)
        self.add_item(self.reason)
        self.duration = None
        if action == "mute":
            self.duration = discord.ui.TextInput(label="Durée", default="10m", placeholder="10m, 1h, 1d", max_length=16)
            self.add_item(self.duration)

    async def on_submit(self, interaction: discord.Interaction):
        duration = str(self.duration.value).strip() if self.duration else None
        await self.cog.run_mod_action(
            interaction, self.view_ref, self.action, self.target_id, str(self.reason.value).strip(), duration
        )


class SentriXV2(commands.Cog, name="SentriXV2"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        for statement in [part.strip() for part in V2_SCHEMA.split(";") if part.strip()]:
            await self.bot.db.execute(statement)
        self.install_policy()
        self.install_help()

    def install_policy(self):
        for module_name in ("main", "__main__"):
            main = sys.modules.get(module_name)
            if main is None or not hasattr(main, "PUBLIC_COMMANDS"):
                continue
            main.PUBLIC_COMMANDS = main.PUBLIC_COMMANDS | V2_PUBLIC_COMMANDS
            main.DISCORD_PERMISSION_COMMANDS["modcenter"] = "moderate_members"
            main.KNOWN_PERMISSION_COMMANDS = (
                main.PUBLIC_COMMANDS | main.OWNER_ONLY_COMMANDS | main.CUSTOM_PERMISSION_COMMANDS
                | frozenset(main.DISCORD_PERMISSION_COMMANDS)
                | frozenset().union(*main.CATEGORY_COMMANDS.values())
            )
        try:
            from . import command_catalog_cleanup
            command_catalog_cleanup.NORMAL_DIRECT_COMMANDS = command_catalog_cleanup.NORMAL_DIRECT_COMMANDS | V2_DIRECT_COMMANDS
            command_catalog_cleanup.RESTORED_COMMANDS = command_catalog_cleanup.NORMAL_DIRECT_COMMANDS
            command_catalog_cleanup.apply_surface(self.bot)
        except Exception:
            pass

    def install_help(self):
        try:
            from . import help_complete
            if any(spec.key == "v2" for spec in help_complete.CATEGORIES):
                return
            help_complete.CATEGORIES = (
                help_complete.CategorySpec(
                    "v2", "◆", "SentriX V2",
                    "Centre de contrôle, hubs, progression, marché et centre staff.",
                    "essential", V2_DIRECT_COMMANDS, frozenset({"SentriXV2"}),
                ),
            ) + help_complete.CATEGORIES
        except Exception:
            pass

    async def category_embed(self, guild_id: int, category: str, *, title: str, description=None, user=None, thumbnail=None):
        design = await self.bot.db.get_design_settings(guild_id)
        style = design_system.CATEGORY_STYLES.get(category, {"colour": design_system.COLORS.primary})
        colour = design.get("primary_color", style["colour"]) if category == "utility" else style["colour"]
        return design_system.create_embed(
            title=title, description=description, colour=colour, user=user,
            thumbnail=thumbnail, footer=design.get("footer"),
        )

    async def checkin_row(self, guild_id: int, user_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM v2_daily_checkins WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )

    async def badge_data(self, guild: discord.Guild, member: discord.Member, stats: dict):
        row = await self.checkin_row(guild.id, member.id)
        streak = int(row["streak"] if row else 0)
        badges = []
        conditions = [
            (stats["message_count"] > 0 or stats["current_level"] > 0, "Premier pas", "Première activité"),
            (stats["message_count"] >= 100, "Actif", "100 messages"),
            (stats["message_count"] >= 1000, "Pilier", "1 000 messages"),
            (stats["current_level"] >= 10, "Niveau 10", "Niveau 10 atteint"),
            (stats["current_level"] >= 25, "Vétéran XP", "Niveau 25 atteint"),
            (stats["total_money"] >= 10_000, "Fortuné", "10 000 pièces"),
            (stats["total_money"] >= 1_000_000, "Millionnaire", "1 000 000 pièces"),
            (stats["reputation"] >= 10, "Respecté", "10 réputation"),
            (stats["voice_time"] >= 36000, "Voix du serveur", "10 h en vocal"),
            (streak >= 7, "Série 7", "7 check-ins consécutifs"),
            (streak >= 30, "Série 30", "30 check-ins consécutifs"),
        ]
        if member.joined_at:
            conditions.append(((datetime.now(timezone.utc) - member.joined_at).days >= 180, "Ancien", "180 jours sur le serveur"))
        for ok, name, desc in conditions:
            if ok:
                badges.append((name, desc))
        return badges

    async def can_staff_context(self, ctx, permission="moderate_members"):
        if ctx.guild is None:
            return False
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        return await checks.is_mod_or_permission(ctx, permission)

    async def can_staff_interaction(self, interaction, permission):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        class Ctx: pass
        ctx = Ctx()
        ctx.author, ctx.guild, ctx.bot = interaction.user, interaction.guild, interaction.client
        return await checks.is_mod_or_permission(ctx, permission)

    async def build_home_embed(self, guild, member):
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        ticket = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND user_id=? AND status='ouvert'", (guild.id, member.id)
        )
        badges = await self.badge_data(guild, member, stats)
        rank = f"#{stats['rank']}" if stats["rank"] else "Non classé"
        e = await self.category_embed(
            guild.id, "utility", title="SentriX V2 — Centre de contrôle",
            description="Tout SentriX dans un seul panneau interactif. Utilisez les boutons ci-dessous.",
            user=member, thumbnail=member.display_avatar.url,
        )
        e.add_field(name="Progression", value=f"Niveau **{stats['current_level']}** · Rang **{rank}**\nXP **{_fmt(stats['current_level_xp'])}/{_fmt(stats['required_xp'])}** ({stats['progress_pct']}%)", inline=True)
        e.add_field(name="Économie", value=f"Portefeuille **{_fmt(stats['wallet'])}**\nBanque **{_fmt(stats['bank'])}** · Total **{_fmt(stats['total_money'])}**", inline=True)
        e.add_field(name="Activité", value=f"Messages **{_fmt(stats['message_count'])}**\nVocal **{stats_service.format_duration(stats['voice_time'])}** · Badges **{len(badges)}**", inline=True)
        e.add_field(name="Serveur", value=f"**{guild.name}** · {_fmt(guild.member_count or 0)} membres · Tickets ouverts pour vous **{int(ticket['n'] if ticket else 0)}**", inline=False)
        return e

    async def build_profile_embed(self, guild, member):
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        profile = await self.bot.db.fetchone("SELECT bio FROM profiles WHERE guild_id=? AND user_id=?", (guild.id, member.id))
        checkin = await self.checkin_row(guild.id, member.id)
        badges = await self.badge_data(guild, member, stats)
        rank = f"#{stats['rank']}" if stats["rank"] else "Non classé"
        e = await self.category_embed(guild.id, "levels", title=f"Profil V2 — {member.display_name}", description=(profile["bio"] if profile and profile["bio"] else "Aucune bio. Utilisez `+set-bio`."), user=member, thumbnail=member.display_avatar.url)
        e.add_field(name="Progression", value=f"Niveau **{stats['current_level']}** · Rang **{rank}**\nXP totale **{_fmt(stats['total_xp'])}** · {stats['progress_pct']}%", inline=True)
        e.add_field(name="Économie", value=f"Total **{_fmt(stats['total_money'])}**\nCash {_fmt(stats['wallet'])} · Banque {_fmt(stats['bank'])}", inline=True)
        e.add_field(name="Communauté", value=f"Réputation **{_fmt(stats['reputation'])}**\nMessages {_fmt(stats['message_count'])} · Vocal {stats_service.format_duration(stats['voice_time'])}", inline=True)
        e.add_field(name=f"Badges ({len(badges)})", value="\n".join(f"**{n}** — {d}" for n, d in badges[:10]) or "Aucun badge pour le moment.", inline=False)
        e.add_field(name="Série", value=f"Actuelle **{int(checkin['streak'] if checkin else 0)} j** · Record **{int(checkin['best_streak'] if checkin else 0)} j**", inline=True)
        return e

    async def build_economy_embed(self, guild, member):
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        row = await self.checkin_row(guild.id, member.id)
        market = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM v2_market_listings WHERE guild_id=? AND status='active'", (guild.id,))
        streak = int(row["streak"] if row else 0)
        claimed = bool(row and row["last_day"] == _today())
        next_reward = min(50 + 10 * streak, 150) if row and row["last_day"] == _yesterday() else 50
        e = await self.category_embed(guild.id, "economy", title="Économie V2", description="Banque, boutique, check-in et marché entre membres.", user=member)
        e.add_field(name="Portefeuille", value=f"**{_fmt(stats['wallet'])}**", inline=True)
        e.add_field(name="Banque", value=f"**{_fmt(stats['bank'])}**", inline=True)
        e.add_field(name="Total", value=f"**{_fmt(stats['total_money'])}**", inline=True)
        e.add_field(name="Check-in", value=f"Série **{streak} j**\n" + ("Déjà récupéré aujourd'hui." if claimed else f"Prochaine récompense **{_fmt(next_reward)}**"), inline=True)
        e.add_field(name="Marché", value=f"**{int(market['n'] if market else 0)}** annonce(s) active(s) · `+market`", inline=True)
        e.add_field(name="Actions", value="`+daily` · `+weekly` · `+work` · `+shop` · `+inventory` · `+market`", inline=False)
        return e

    async def build_games_embed(self, guild, member):
        sections, total = [], 0
        for group, names in GAME_GROUPS.items():
            available = [n for n in names if self.bot.get_command(n)]
            if available:
                total += len(available)
                sections.append(f"**{group}**\n" + " · ".join(f"`+{n}`" for n in available))
        e = await self.category_embed(guild.id, "games", title="SentriX Game Hub", description=f"**{total} jeux/modes** détectés.\n\n" + ("\n\n".join(sections) or "Aucun jeu chargé."), user=member)
        e.add_field(name="Économie commune", value="Les récompenses utilisent la même monnaie que `+balance`, la boutique et le marché.", inline=False)
        return e

    async def build_ai_embed(self, guild, member):
        try:
            row = await self.bot.db.fetchone("SELECT enabled, default_model, memory_enabled FROM ai_settings WHERE guild_id=?", (guild.id,))
        except Exception:
            row = None
        enabled = bool(row["enabled"]) if row else bool(config.OPENAI_API_KEY)
        model = row["default_model"] if row else "auto"
        memory = bool(row["memory_enabled"]) if row else False
        e = await self.category_embed(guild.id, "ai", title="SentriX AI Center", description="Questions, rédaction, traduction, résumé et génération d'images depuis un même centre.", user=member)
        e.add_field(name="État", value="Disponible" if enabled else "Désactivée", inline=True)
        e.add_field(name="Mode", value=str(model or "auto").title(), inline=True)
        e.add_field(name="Mémoire", value="Activée" if memory else "Désactivée", inline=True)
        e.add_field(name="Commandes", value="`+sentrix <question>` · `+summarize` · `+rewrite` · `+correct` · `+image`", inline=False)
        return e

    async def build_ticket_embed(self, guild, member):
        rows = await self.bot.db.fetchall("SELECT channel_id, category, priority, claimed_by FROM tickets WHERE guild_id=? AND user_id=? AND status='ouvert' ORDER BY created_at DESC LIMIT 8", (guild.id, member.id))
        e = await self.category_embed(guild.id, "tickets", title="Ticket Center", description="Vos tickets actifs et le système de support SentriX.", user=member)
        if rows:
            lines = []
            for row in rows:
                channel = guild.get_channel(row["channel_id"])
                lines.append(f"{channel.mention if channel else '`'+str(row['channel_id'])+'`'} · **{row['category'] or 'general'}** · {row['priority'] or 'normale'} · " + (f"<@{row['claimed_by']}>" if row["claimed_by"] else "Non claim"))
            e.add_field(name=f"Tickets ouverts ({len(rows)})", value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Vos tickets", value="Aucun ticket ouvert.", inline=False)
        e.add_field(name="Configuration staff", value="`+ticketsetup` gère panels, formulaires, claims, transcripts et boutons staff.", inline=False)
        return e

    async def build_progress_embed(self, guild, member):
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        row = await self.checkin_row(guild.id, member.id)
        streak = int(row["streak"] if row else 0)
        badges = await self.badge_data(guild, member, stats)
        goals = []
        if stats["current_level"] < 10: goals.append(f"Niveau 10 — encore {10-stats['current_level']} niveau(x)")
        elif stats["current_level"] < 25: goals.append(f"Niveau 25 — encore {25-stats['current_level']} niveau(x)")
        if stats["message_count"] < 100: goals.append(f"100 messages — encore {100-stats['message_count']}")
        elif stats["message_count"] < 1000: goals.append(f"1 000 messages — encore {1000-stats['message_count']}")
        if stats["total_money"] < 10_000: goals.append(f"10 000 pièces — encore {_fmt(10000-stats['total_money'])}")
        elif stats["total_money"] < 1_000_000: goals.append(f"1 000 000 pièces — encore {_fmt(1000000-stats['total_money'])}")
        if streak < 7: goals.append(f"Série 7 jours — encore {7-streak}")
        elif streak < 30: goals.append(f"Série 30 jours — encore {30-streak}")
        e = await self.category_embed(guild.id, "levels", title="Progression globale", description=f"**{len(badges)} badge(s)** débloqué(s).", user=member, thumbnail=member.display_avatar.url)
        e.add_field(name="Badges", value="\n".join(f"**{n}** — {d}" for n, d in badges) or "Aucun badge pour le moment.", inline=False)
        e.add_field(name="Prochains objectifs", value="\n".join(f"• {g}" for g in goals[:4]) or "Tous les objectifs principaux sont atteints.", inline=False)
        return e

    async def build_mod_embed(self, guild, member):
        since = int(time.time()) - 86400
        queries = {
            "Sanctions 24 h": ("SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND created_at>=?", (guild.id, since)),
            "Warns 24 h": ("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND timestamp>=?", (guild.id, since)),
            "AutoMod 24 h": ("SELECT COUNT(*) AS n FROM automod_logs WHERE guild_id=? AND timestamp>=?", (guild.id, since)),
            "Tickets ouverts": ("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND status='ouvert'", (guild.id,)),
        }
        values = {}
        for label, (query, params) in queries.items():
            try:
                row = await self.bot.db.fetchone(query, params)
                values[label] = int(row["n"] if row else 0)
            except Exception:
                values[label] = 0
        automod = await self.bot.db.get_automod(guild.id)
        keys = ("antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke")
        protections = sum(1 for key in keys if automod and automod[key])
        e = await self.category_embed(guild.id, "moderation", title="Centre de modération V2", description="Vue opérationnelle des dernières 24 heures. `+modcenter` permet d'agir directement.", user=member)
        for label, value in values.items(): e.add_field(name=label, value=f"**{value}**", inline=True)
        e.add_field(name="Protections", value=f"**{protections}/11**", inline=True)
        e.add_field(name="Action rapide", value="Choisissez un membre puis utilisez **Warn**, **Mute** ou **Ban**.", inline=False)
        return e

    async def build_member_mod_embed(self, guild, member):
        warns = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (guild.id, member.id))
        sanctions = await self.bot.db.fetchall("SELECT case_number, action, reason, created_at FROM sanctions WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 5", (guild.id, member.id))
        e = await self.category_embed(guild.id, "moderation", title=f"Centre staff — {member.display_name}", description=f"{member.mention} · `{member.id}`", thumbnail=member.display_avatar.url)
        e.add_field(name="Avertissements", value=f"**{int(warns['n'] if warns else 0)}**", inline=True)
        e.add_field(name="Compte créé", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        e.add_field(name="Rôle principal", value=member.top_role.mention, inline=True)
        if sanctions:
            lines = [f"**#{r['case_number']} · {r['action']}** — {(r['reason'] or 'Aucune raison').replace(chr(10),' ')[:75]} · <t:{int(r['created_at'])}:R>" for r in sanctions]
            e.add_field(name="Dernières sanctions", value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Historique", value="Aucune sanction enregistrée.", inline=False)
        return e

    async def claim_checkin(self, guild, member):
        today, now_ts = _today(), int(time.time())
        cursor = await self.bot.db.execute("INSERT OR IGNORE INTO v2_daily_claims (guild_id,user_id,claim_day,claimed_at,reward) VALUES (?,?,?,?,0)", (guild.id, member.id, today, now_ts))
        if getattr(cursor, "rowcount", 0) == 0:
            row = await self.checkin_row(guild.id, member.id)
            return {"claimed": False, "streak": int(row["streak"] if row else 0), "reward": 0}
        previous = await self.checkin_row(guild.id, member.id)
        streak = int(previous["streak"]) + 1 if previous and previous["last_day"] == _yesterday() else 1
        best = max(streak, int(previous["best_streak"] if previous else 0))
        reward = min(50 + (streak - 1) * 10, 150)
        try:
            await self.bot.db.execute("INSERT INTO v2_daily_checkins (guild_id,user_id,last_day,streak,best_streak,total_claims) VALUES (?,?,?,?,?,1) ON CONFLICT(guild_id,user_id) DO UPDATE SET last_day=excluded.last_day, streak=excluded.streak, best_streak=MAX(v2_daily_checkins.best_streak,excluded.best_streak), total_claims=v2_daily_checkins.total_claims+1", (guild.id, member.id, today, streak, best))
            await self.bot.db.ensure_economy(guild.id, member.id)
            await self.bot.db.add_balance(guild.id, member.id, reward)
            await self.bot.db.execute("UPDATE v2_daily_claims SET reward=? WHERE guild_id=? AND user_id=? AND claim_day=?", (reward, guild.id, member.id, today))
            try:
                await self.bot.db.log_transaction(guild.id, None, member.id, "v2_checkin", reward, f"Check-in V2 — série {streak}")
            except Exception:
                pass
        except Exception:
            await self.bot.db.execute("DELETE FROM v2_daily_claims WHERE guild_id=? AND user_id=? AND claim_day=? AND reward=0", (guild.id, member.id, today))
            raise
        return {"claimed": True, "streak": streak, "reward": reward}

    async def run_mod_action(self, interaction, view, action, target_id, reason, duration):
        guild = interaction.guild
        member = guild.get_member(target_id) if guild else None
        if member is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Membre introuvable.')), ephemere=True)
        permission = ModAction.PERMS[action]
        if not await self.can_staff_interaction(interaction, permission):
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Permission insuffisante.')), ephemere=True)
        command = self.bot.get_command(action)
        cog = self.bot.get_cog("Moderation")
        if command is None or cog is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Module de modération indisponible.')), ephemere=True)
        ctx = InteractionContext(interaction, command)
        try:
            if action == "mute":
                await command.callback(cog, ctx, member, duration or "10m", raison=reason or "Aucune raison fournie")
            else:
                await command.callback(cog, ctx, member, raison=reason or "Aucune raison fournie")
        except discord.Forbidden:
            if interaction.response.is_done(): await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error('Discord refuse cette sanction. Vérifiez la hiérarchie.')), ephemere=True)
            else: await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Discord refuse cette sanction. Vérifiez la hiérarchie.')), ephemere=True)
        except discord.HTTPException:
            if interaction.response.is_done(): await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error("Discord a refusé l'action.")), ephemere=True)
            else: await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Discord a refusé l'action.")), ephemere=True)
        finally:
            try:
                if interaction.message:
                    await interaction.message.edit(embed=await self.build_member_mod_embed(guild, member), view=view)
            except Exception:
                pass

    async def build_market_embed(self, guild, member):
        rows = await self.bot.db.fetchall("SELECT id,seller_id,item_name,quantity,unit_price FROM v2_market_listings WHERE guild_id=? AND status='active' ORDER BY id DESC LIMIT 12", (guild.id,))
        e = await self.category_embed(guild.id, "economy", title="Marché entre membres", description="Objets de l'inventaire + monnaie SentriX existante.", user=member)
        if rows:
            e.add_field(name="Annonces actives", value="\n".join(f"**#{r['id']}** · {r['quantity']}× **{r['item_name']}** · {_fmt(r['unit_price'])}/u · <@{r['seller_id']}>" for r in rows), inline=False)
        else:
            e.add_field(name="Annonces actives", value="Aucune annonce.", inline=False)
        e.add_field(name="Vendre", value="`+market-sell <quantité> <prix_unitaire> <objet>`", inline=False)
        e.add_field(name="Acheter / annuler", value="`+market-buy <id>` · `+market-cancel <id>`", inline=False)
        return e

    @commands.hybrid_command(name="home", aliases=["sentrixhome"], description="Ouvrir le centre de contrôle SentriX V2.", with_app_command=False)
    async def home(self, ctx):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member): return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        view = HomeView(self, ctx.guild, ctx.author, await self.can_staff_context(ctx))
        view.message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await self.build_home_embed(ctx.guild, ctx.author)), view))

    @commands.hybrid_command(name="profilecard", description="Afficher une carte de profil V2.", with_app_command=False)
    async def profilecard(self, ctx, membre: discord.Member = None):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        await panels.envoyer(ctx, panels.depuis_embed(await self.build_profile_embed(ctx.guild, membre or ctx.author)))

    @commands.hybrid_command(name="economyhub", description="Ouvrir le hub économie V2.", with_app_command=False)
    async def economyhub(self, ctx):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        await panels.envoyer(ctx, panels.depuis_embed(await self.build_economy_embed(ctx.guild, ctx.author)))

    @commands.hybrid_command(name="gamehub", description="Ouvrir le hub interactif des jeux.", with_app_command=False)
    async def gamehub(self, ctx):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        view = GameView(self, ctx.author)
        view.message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await self.build_games_embed(ctx.guild, ctx.author)), view))

    @commands.hybrid_command(name="aicenter", description="Afficher le centre IA.", with_app_command=False)
    async def aicenter(self, ctx):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        await panels.envoyer(ctx, panels.depuis_embed(await self.build_ai_embed(ctx.guild, ctx.author)))

    @commands.hybrid_command(name="ticketcenter", description="Afficher le centre de tickets.", with_app_command=False)
    async def ticketcenter(self, ctx):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        await panels.envoyer(ctx, panels.depuis_embed(await self.build_ticket_embed(ctx.guild, ctx.author)))

    @commands.hybrid_command(name="progress", description="Afficher la progression globale et les badges.", with_app_command=False)
    async def progress(self, ctx, membre: discord.Member = None):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        await panels.envoyer(ctx, panels.depuis_embed(await self.build_progress_embed(ctx.guild, membre or ctx.author)))

    @commands.hybrid_command(name="checkin", description="Récupérer le check-in quotidien V2.", with_app_command=False)
    async def checkin(self, ctx):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        result = await self.claim_checkin(ctx.guild, ctx.author)
        if result["claimed"]: await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"**+{_fmt(result['reward'])}** pièces · série **{result['streak']} j**.")))
        else: await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"Déjà récupéré aujourd'hui · série **{result['streak']} j**.")))

    @commands.hybrid_command(name="market", description="Afficher le marché entre membres.", with_app_command=False)
    async def market(self, ctx):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        view = MarketView(self, ctx.author)
        view.message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await self.build_market_embed(ctx.guild, ctx.author)), view))

    @commands.hybrid_command(name="market-sell", description="Vendre un objet de votre inventaire.", with_app_command=False)
    async def market_sell(self, ctx, quantity: int, unit_price: int, *, item: str):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        item = item.strip()
        if not item or len(item) > 100 or quantity < 1 or quantity > 1000 or unit_price < 1 or unit_price > 1_000_000_000:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Objet, quantité ou prix invalide.')))
        cursor = await self.bot.db.execute("UPDATE inventory SET quantity=quantity-? WHERE guild_id=? AND user_id=? AND lower(item_name)=lower(?) AND quantity>=?", (quantity, ctx.guild.id, ctx.author.id, item, quantity))
        if getattr(cursor, "rowcount", 0) == 0: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Vous n'avez pas assez de cet objet.")))
        try:
            row = await self.bot.db.fetchone("SELECT item_name FROM inventory WHERE guild_id=? AND user_id=? AND lower(item_name)=lower(?)", (ctx.guild.id, ctx.author.id, item))
            canonical = row["item_name"] if row else item
            await self.bot.db.execute("DELETE FROM inventory WHERE guild_id=? AND user_id=? AND lower(item_name)=lower(?) AND quantity<=0", (ctx.guild.id, ctx.author.id, item))
            cur = await self.bot.db.execute("INSERT INTO v2_market_listings (guild_id,seller_id,item_name,quantity,unit_price,status,created_at) VALUES (?,?,?,?,?,'active',?)", (ctx.guild.id, ctx.author.id, canonical, quantity, unit_price, int(time.time())))
            listing_id = int(cur.lastrowid)
        except Exception:
            await self.bot.db.execute("INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=inventory.quantity+excluded.quantity", (ctx.guild.id, ctx.author.id, item, quantity))
            raise
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Annonce **#{listing_id}** : **{quantity}× {canonical}** à **{_fmt(unit_price)}**/u.')))

    @commands.hybrid_command(name="market-buy", description="Acheter une annonce du marché.", with_app_command=False)
    async def market_buy(self, ctx, listing_id: int):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        row = await self.bot.db.fetchone("SELECT * FROM v2_market_listings WHERE id=? AND guild_id=? AND status='active'", (listing_id, ctx.guild.id))
        if row is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Annonce indisponible.')))
        if int(row["seller_id"]) == ctx.author.id: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas acheter votre propre annonce.')))
        lock = await self.bot.db.execute("UPDATE v2_market_listings SET status='processing' WHERE id=? AND guild_id=? AND status='active'", (listing_id, ctx.guild.id))
        if getattr(lock, "rowcount", 0) == 0: return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning("Cette annonce vient d'être prise.")))
        total = int(row["quantity"]) * int(row["unit_price"])
        paid = await self.bot.db.pay_member(ctx.guild.id, ctx.author.id, int(row["seller_id"]), total, reason=f"Marché V2 #{listing_id}")
        if not paid:
            await self.bot.db.execute("UPDATE v2_market_listings SET status='active' WHERE id=? AND status='processing'", (listing_id,))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Pas assez d'argent liquide.")))
        try:
            await self.bot.db.execute("INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=inventory.quantity+excluded.quantity", (ctx.guild.id, ctx.author.id, row["item_name"], int(row["quantity"])))
            await self.bot.db.execute("UPDATE v2_market_listings SET status='sold',buyer_id=?,sold_at=? WHERE id=?", (ctx.author.id, int(time.time()), listing_id))
        except Exception:
            await self.bot.db.execute("UPDATE v2_market_listings SET status='error' WHERE id=?", (listing_id,))
            raise
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Achat terminé : **{row['quantity']}× {row['item_name']}** pour **{_fmt(total)}**.")))

    @commands.hybrid_command(name="market-cancel", description="Annuler une de vos annonces.", with_app_command=False)
    async def market_cancel(self, ctx, listing_id: int):
        if ctx.guild is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        row = await self.bot.db.fetchone("SELECT * FROM v2_market_listings WHERE id=? AND guild_id=? AND seller_id=? AND status='active'", (listing_id, ctx.guild.id, ctx.author.id))
        if row is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Annonce introuvable ou non annulable.')))
        cur = await self.bot.db.execute("UPDATE v2_market_listings SET status='cancelled' WHERE id=? AND guild_id=? AND seller_id=? AND status='active'", (listing_id, ctx.guild.id, ctx.author.id))
        if getattr(cur, "rowcount", 0) == 0: return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Annonce déjà indisponible.')))
        await self.bot.db.execute("INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=inventory.quantity+excluded.quantity", (ctx.guild.id, ctx.author.id, row["item_name"], int(row["quantity"])))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Annonce **#{listing_id}** annulée et objets rendus.')))

    @commands.hybrid_command(name="modcenter", description="Ouvrir le centre de modération interactif.", with_app_command=False)
    @checks.has_permission_or_modrole("moderate_members")
    async def modcenter(self, ctx, membre: discord.Member = None):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member): return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        view = ModView(self, ctx.author)
        if membre:
            view.target_id = membre.id
            view.sync()
            embed = await self.build_member_mod_embed(ctx.guild, membre)
        else:
            embed = await self.build_mod_embed(ctx.guild, ctx.author)
        view.message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view))


async def setup(bot: commands.Bot):
    await bot.add_cog(SentriXV2(bot))
