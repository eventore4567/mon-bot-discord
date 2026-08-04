"""
Cog STATISTIQUES / DÉVELOPPEMENT.
/bot-status /server-growth /command-stats /latency /changelog /feedback /botinfo
"""

import time
import platform
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, design_system
from database.db import now

START_TIME = time.time()


class Stats(commands.Cog, name="Stats"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _embed(self, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed statut/dev cohérent avec +designsetup (catégorie CATEGORY_STYLES["utility"],
        car ces commandes techniques n'ont pas leur propre catégorie visuelle dédiée)."""
        style = design_system.CATEGORY_STYLES["utility"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

    # NOTE : le nom de méthode ne doit JAMAIS commencer par "bot_" ou "cog_"
    # (restriction interne de discord.py sur les Cogs). D'où "system_status"
    # ici, alors que la commande visible reste "/bot-status" et "+bot-status".
    @commands.hybrid_command(name="bot-status", description="Afficher l'état général du bot.")
    async def system_status(self, ctx: commands.Context):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title="État du bot")
        e.add_field(name="Latence", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        e.add_field(name="Serveurs", value=len(self.bot.guilds), inline=True)
        e.add_field(name="Utilisateurs", value=sum(g.member_count for g in self.bot.guilds), inline=True)
        e.add_field(name="Python", value=platform.python_version(), inline=True)
        e.add_field(name="discord.py", value=discord.__version__, inline=True)
        uptime = int(time.time() - START_TIME)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        e.add_field(name="Uptime", value=f"{h}h {m}m {s}s", inline=True)

        # Compteur de profils enregistrés en base : sert de diagnostic rapide de
        # persistance. Si ce nombre retombe à un chiffre anormalement bas juste après un
        # redéploiement Railway (alors qu'il était plus élevé avant), c'est le signe qu'aucun
        # volume persistant n'est monté sur le chemin de la base de données, et que toutes
        # les données (niveaux, économie, avertissements...) repartent de zéro à chaque
        # redéploiement. Un serveur actif ne doit JAMAIS voir ce chiffre baisser tout seul.
        try:
            level_row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM levels")
            e.add_field(
                name="📦 Profils en base (tous serveurs)",
                value=str(level_row["n"] if level_row else 0),
                inline=True,
            )
        except Exception:
            pass
        await ctx.send(embed=e)

    @commands.hybrid_command(name="server-growth", description="Afficher la croissance des membres du serveur.", with_app_command=False)
    async def server_growth(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM growth_snapshots WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 7", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Pas assez de données", description="Pas encore assez de données de croissance."))
        lines = [f"<t:{r['timestamp']}:D> — {r['member_count']} membres" for r in reversed(rows)]
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Croissance du serveur", description="\n".join(lines)))

    @commands.hybrid_command(name="command-stats", description="Afficher les commandes les plus utilisées.", with_app_command=False)
    async def command_stats(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT command_name, COUNT(*) as c FROM command_logs WHERE guild_id = ? GROUP BY command_name ORDER BY c DESC LIMIT 10",
            (ctx.guild.id,),
        )
        if not rows:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Aucune statistique", description="Aucune statistique de commande pour l'instant."))
        lines = [f"`{r['command_name']}` — {r['c']} utilisations" for r in rows]
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Commandes les plus utilisées", description="\n".join(lines)))

    @commands.hybrid_command(name="latency", description="Afficher la latence détaillée du bot.", with_app_command=False)
    async def latency(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        start = time.perf_counter()
        msg = await ctx.send(embed=await self._embed(guild_id, title="Latence", description="Calcul en cours..."))
        elapsed = (time.perf_counter() - start) * 1000
        e = await self._embed(guild_id, title="Latence", description=f"🏓 Latence API : **{round(self.bot.latency * 1000)}ms**\n📨 Latence message : **{round(elapsed)}ms**")
        if ctx.interaction:
            await ctx.edit_original_response(embed=e)
        else:
            await msg.edit(embed=e)

    @commands.hybrid_command(name="changelog", description="Afficher les dernières nouveautés du bot.", with_app_command=False)
    async def changelog(self, ctx: commands.Context):
        e = await self._embed(
            ctx.guild.id if ctx.guild else None,
            title="Changelog",
            description="Dernières nouveautés de SentriX (les plus récentes en premier) :",
        )
        e.add_field(
            name="🆕 Récent",
            value=(
                "• `/invites` (alias `+i`), `/invite-leaderboard`, `/invited-by` : suivi des invitations, "
                "avec alerte si plusieurs comptes très récents sont invités par la même personne en rafale.\n"
                "• Page \"Sécurité\" dans `/setup` : préréglages et filtres AutoMod détaillés.\n"
                "• `+addrole`/`+delrole` : raccourcis pour donner/retirer un rôle.\n"
                "• Outils propriétaire : liste noire globale (`+bl`), statut personnalisé, "
                "identité du bot, alias de commandes.\n"
                "• `/create-server` : génère automatiquement toute une structure de serveur "
                "(rôles, catégories, salons) selon un modèle au choix."
            ),
            inline=False,
        )
        e.add_field(
            name="🛡️ Sécurité",
            value=(
                "• Anti-nuke : détection des renommages massifs et des élévations de permissions "
                "suspectes, en plus des suppressions.\n"
                "• Système de logs automatique (`/create-logs`, 7 salons dédiés)."
            ),
            inline=False,
        )
        e.add_field(
            name="⚙️ Configuration",
            value=(
                "• `/setup` : assistant complet en plusieurs pages (rôles, salons, niveaux, logs, "
                "gestionnaires du bot).\n"
                "• Possibilité d'ajouter des membres autorisés à configurer le bot sans être admin."
            ),
            inline=False,
        )
        e.add_field(
            name="🎫 Tickets & IA",
            value=(
                "• Panneau de tickets avec catégories, priorité et fermeture automatique.\n"
                "• `/sentrix` : répond à n'importe quelle question avec un indice de confiance, "
                "et réagit aussi si on lui parle directement en mentionnant le bot ou en écrivant \"sentrix\"."
            ),
            inline=False,
        )
        await ctx.send(embed=e)

    @commands.hybrid_command(name="feedback", description="Envoyer un retour aux développeurs du bot.", with_app_command=False)
    @app_commands.describe(texte="Votre retour")
    async def feedback(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.execute(
            "INSERT INTO bug_reports (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id if ctx.guild else None, ctx.author.id, f"[FEEDBACK] {texte}", now()),
        )
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Merci !", description="Merci pour votre retour !", kind="success"))

    @commands.hybrid_command(name="botinfo", description="Afficher des informations générales sur le bot.")
    async def botinfo(self, ctx: commands.Context):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title=f"À propos de {self.bot.user.name}")
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        e.add_field(name="Créateur", value="Développé pour ce serveur", inline=True)
        e.add_field(name="Serveurs", value=len(self.bot.guilds), inline=True)
        e.add_field(name="Commandes", value=sum(1 for _ in self.bot.commands), inline=True)
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
