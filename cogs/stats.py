"""
Cog STATISTIQUES / DÉVELOPPEMENT.
/bot-status /uptime /server-growth /command-stats /latency /shard-info
/eval-safe /reload-cog /list-cogs /changelog /feedback /botinfo
"""

import time
import platform
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds, checks
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

    @commands.hybrid_command(name="uptime", description="Afficher depuis combien de temps le bot est en ligne.")
    async def uptime(self, ctx: commands.Context):
        uptime = int(time.time() - START_TIME)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        await ctx.send(embed=embeds.info(f"⏱️ Le bot est en ligne depuis **{h}h {m}m {s}s**."))

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

    @commands.hybrid_command(name="shard-info", description="Afficher les informations de sharding.", with_app_command=False)
    async def shard_info(self, ctx: commands.Context):
        shard_count = self.bot.shard_count or 1
        e = embeds.neutral("🧩 Informations de sharding")
        e.add_field(name="Nombre de shards", value=shard_count, inline=True)
        e.add_field(name="Shard actuel", value=(ctx.guild.shard_id if ctx.guild else 0), inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="eval-safe", description="[Owner] Exécuter une expression Python simple (lecture seule).", with_app_command=False)
    @app_commands.describe(expression="Expression Python à évaluer")
    @checks.is_owner_or_admin()
    async def eval_safe(self, ctx: commands.Context, *, expression: str):
        if ctx.author.id not in config.OWNER_IDS:
            return await ctx.send(embed=embeds.error("Seul le propriétaire du bot peut utiliser cette commande."))
        allowed_names = {"bot": self.bot, "guild": ctx.guild, "len": len}
        try:
            result = eval(expression, {"__builtins__": {}}, allowed_names)
        except Exception as exc:
            return await ctx.send(embed=embeds.error(f"Erreur : `{exc}`"))
        await ctx.send(embed=embeds.info(f"```py\n{result}\n```"))

    @commands.hybrid_command(name="reload-cog", description="[Owner] Recharger un module (cog) du bot.", with_app_command=False)
    @app_commands.describe(nom="Le nom du module (ex: cogs.moderation)")
    @checks.is_owner_or_admin()
    async def reload_cog(self, ctx: commands.Context, nom: str):
        if ctx.author.id not in config.OWNER_IDS:
            return await ctx.send(embed=embeds.error("Seul le propriétaire du bot peut utiliser cette commande."))
        try:
            await self.bot.reload_extension(nom)
        except Exception as exc:
            return await ctx.send(embed=embeds.error(f"Échec du rechargement : `{exc}`"))
        await ctx.send(embed=embeds.success(f"Module `{nom}` rechargé avec succès."))

    @commands.hybrid_command(name="list-cogs", description="Lister les modules (cogs) chargés.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def list_cogs(self, ctx: commands.Context):
        names = ", ".join(f"`{name}`" for name in self.bot.cogs.keys())
        await ctx.send(embed=embeds.neutral("🧩 Modules chargés", names or "Aucun"))

    @commands.hybrid_command(name="changelog", description="Afficher les dernières nouveautés du bot.", with_app_command=False)
    async def changelog(self, ctx: commands.Context):
        e = embeds.neutral("📋 Changelog", "Version actuelle : **1.0**\n- Lancement initial du bot avec ~260 commandes.\n- Support complet slash (/) et préfixe (+).")
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
