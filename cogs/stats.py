"""
Cog STATISTIQUES / DÉVELOPPEMENT.
/bot-status /server-growth /command-stats /latency /changelog /feedback /botinfo
"""

import time
import platform
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds
from database.db import now

START_TIME = time.time()


class Stats(commands.Cog, name="Stats"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # NOTE : le nom de méthode ne doit JAMAIS commencer par "bot_" ou "cog_"
    # (restriction interne de discord.py sur les Cogs). D'où "system_status"
    # ici, alors que la commande visible reste "/bot-status" et "+bot-status".
    @commands.hybrid_command(name="bot-status", description="Afficher l'état général du bot.")
    async def system_status(self, ctx: commands.Context):
        e = embeds.neutral("🤖 État du bot")
        e.add_field(name="Latence", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        e.add_field(name="Serveurs", value=len(self.bot.guilds), inline=True)
        e.add_field(name="Utilisateurs", value=sum(g.member_count for g in self.bot.guilds), inline=True)
        e.add_field(name="Python", value=platform.python_version(), inline=True)
        e.add_field(name="discord.py", value=discord.__version__, inline=True)
        uptime = int(time.time() - START_TIME)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        e.add_field(name="Uptime", value=f"{h}h {m}m {s}s", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="server-growth", description="Afficher la croissance des membres du serveur.", with_app_command=False)
    async def server_growth(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM growth_snapshots WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 7", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Pas encore assez de données de croissance."))
        lines = [f"<t:{r['timestamp']}:D> — {r['member_count']} membres" for r in reversed(rows)]
        await ctx.send(embed=embeds.neutral("📈 Croissance du serveur", "\n".join(lines)))

    @commands.hybrid_command(name="command-stats", description="Afficher les commandes les plus utilisées.", with_app_command=False)
    async def command_stats(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT command_name, COUNT(*) as c FROM command_logs WHERE guild_id = ? GROUP BY command_name ORDER BY c DESC LIMIT 10",
            (ctx.guild.id,),
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucune statistique de commande pour l'instant."))
        lines = [f"`{r['command_name']}` — {r['c']} utilisations" for r in rows]
        await ctx.send(embed=embeds.neutral("📊 Commandes les plus utilisées", "\n".join(lines)))

    @commands.hybrid_command(name="latency", description="Afficher la latence détaillée du bot.", with_app_command=False)
    async def latency(self, ctx: commands.Context):
        start = time.perf_counter()
        msg = await ctx.send(embed=embeds.info("Calcul en cours..."))
        elapsed = (time.perf_counter() - start) * 1000
        e = embeds.info(f"🏓 Latence API : **{round(self.bot.latency * 1000)}ms**\n📨 Latence message : **{round(elapsed)}ms**")
        if ctx.interaction:
            await ctx.edit_original_response(embed=e)
        else:
            await msg.edit(embed=e)

    @commands.hybrid_command(name="changelog", description="Afficher les dernières nouveautés du bot.", with_app_command=False)
    async def changelog(self, ctx: commands.Context):
        e = embeds.neutral("📋 Changelog", "Version actuelle : **1.1**\n- Assistant de configuration `/setup` en un clic.\n- Optimisations pour les gros serveurs.\n- Support complet slash (/) et préfixe (+).")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="feedback", description="Envoyer un retour aux développeurs du bot.", with_app_command=False)
    @app_commands.describe(texte="Votre retour")
    async def feedback(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.execute(
            "INSERT INTO bug_reports (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id if ctx.guild else None, ctx.author.id, f"[FEEDBACK] {texte}", now()),
        )
        await ctx.send(embed=embeds.success("Merci pour votre retour !"))

    @commands.hybrid_command(name="botinfo", description="Afficher des informations générales sur le bot.")
    async def botinfo(self, ctx: commands.Context):
        e = embeds.neutral(f"ℹ️ À propos de {self.bot.user.name}")
        e.set_thumbnail(url=self.bot.user.display_avatar.url)
        e.add_field(name="Créateur", value="Développé pour ce serveur", inline=True)
        e.add_field(name="Serveurs", value=len(self.bot.guilds), inline=True)
        e.add_field(name="Commandes", value=sum(1 for _ in self.bot.commands), inline=True)
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
