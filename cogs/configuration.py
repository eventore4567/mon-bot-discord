"""
Cog CONFIGURATION.
/setprefix /setmodrole /setlogchannel /setwelcomechannel /setgoodbyechannel
/setwelcomemessage /setgoodbyemessage /setticketcategory /setticketlogchannel
/setautorole /disablecommand /enablecommand /ignorechannel /unignorechannel
/setlanguage /config-view /config-reset /setlevelchannel /setsuggestchannel
/setannouncechannel /setgiveawaychannel
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="setprefix", description="Changer le préfixe des commandes textuelles.")
    @app_commands.describe(prefixe="Le nouveau préfixe (ex: !, ?, +)")
    @checks.is_owner_or_admin()
    async def setprefix(self, ctx: commands.Context, prefixe: str):
        if len(prefixe) > 5:
            return await ctx.send(embed=embeds.error("Le préfixe doit faire 5 caractères maximum."))
        await self.bot.db.set_guild_config(ctx.guild.id, "prefix", prefixe)
        await ctx.send(embed=embeds.success(f"Le préfixe a été changé pour `{prefixe}`."))

    @commands.hybrid_command(name="setmodrole", description="Définir le rôle du staff/modération.")
    @app_commands.describe(role="Le rôle à définir comme rôle staff")
    @checks.is_owner_or_admin()
    async def setmodrole(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.set_guild_config(ctx.guild.id, "mod_role", role.id)
        await ctx.send(embed=embeds.success(f"Le rôle staff a été défini sur {role.mention}."))

    @commands.hybrid_command(name="setlogchannel", description="Définir le salon de logs des sanctions.")
    @app_commands.describe(salon="Le salon où seront envoyés les logs")
    @checks.is_owner_or_admin()
    async def setlogchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "log_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Le salon de logs a été défini sur {salon.mention}."))

    @commands.hybrid_command(name="setwelcomechannel", description="Définir le salon de bienvenue.", with_app_command=False)
    @app_commands.describe(salon="Le salon de bienvenue")
    @checks.is_owner_or_admin()
    async def setwelcomechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "welcome_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Le salon de bienvenue a été défini sur {salon.mention}."))

    @commands.hybrid_command(name="setgoodbyechannel", description="Définir le salon des messages de départ.", with_app_command=False)
    @app_commands.describe(salon="Le salon de départ")
    @checks.is_owner_or_admin()
    async def setgoodbyechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "goodbye_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Le salon de départ a été défini sur {salon.mention}."))

    @commands.hybrid_command(name="setwelcomemessage", description="Personnaliser le message de bienvenue ({member}, {server}).", with_app_command=False)
    @app_commands.describe(message="Le message (utilisez {member} et {server})")
    @checks.is_owner_or_admin()
    async def setwelcomemessage(self, ctx: commands.Context, *, message: str):
        await self.bot.db.set_guild_config(ctx.guild.id, "welcome_message", message)
        await ctx.send(embed=embeds.success("Message de bienvenue mis à jour."))

    @commands.hybrid_command(name="setgoodbyemessage", description="Personnaliser le message de départ ({member}, {server}).", with_app_command=False)
    @app_commands.describe(message="Le message (utilisez {member} et {server})")
    @checks.is_owner_or_admin()
    async def setgoodbyemessage(self, ctx: commands.Context, *, message: str):
        await self.bot.db.set_guild_config(ctx.guild.id, "goodbye_message", message)
        await ctx.send(embed=embeds.success("Message de départ mis à jour."))

    @commands.hybrid_command(name="setticketcategory", description="Définir la catégorie où seront créés les tickets.", with_app_command=False)
    @app_commands.describe(categorie="La catégorie Discord pour les tickets")
    @checks.is_owner_or_admin()
    async def setticketcategory(self, ctx: commands.Context, categorie: discord.CategoryChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "ticket_category", categorie.id)
        await ctx.send(embed=embeds.success(f"Catégorie des tickets définie sur **{categorie.name}**."))

    @commands.hybrid_command(name="setticketlogchannel", description="Définir le salon de logs des tickets.", with_app_command=False)
    @app_commands.describe(salon="Le salon de logs des tickets")
    @checks.is_owner_or_admin()
    async def setticketlogchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "ticket_log_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon de logs des tickets défini sur {salon.mention}."))

    @commands.hybrid_command(name="setautorole", description="Définir un rôle attribué automatiquement à l'arrivée.")
    @app_commands.describe(role="Le rôle à attribuer automatiquement")
    @checks.is_owner_or_admin()
    async def setautorole(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.set_guild_config(ctx.guild.id, "autorole", role.id)
        await ctx.send(embed=embeds.success(f"Rôle automatique défini sur {role.mention}."))

    @commands.hybrid_command(name="disablecommand", description="Désactiver une commande sur ce serveur.", with_app_command=False)
    @app_commands.describe(commande="Le nom de la commande à désactiver")
    @checks.is_owner_or_admin()
    async def disablecommand(self, ctx: commands.Context, commande: str):
        cmd = self.bot.get_command(commande)
        if not cmd:
            return await ctx.send(embed=embeds.error(f"Commande `{commande}` introuvable."))
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO disabled_commands (guild_id, command_name) VALUES (?, ?)",
            (ctx.guild.id, commande),
        )
        await ctx.send(embed=embeds.success(f"La commande `{commande}` a été désactivée sur ce serveur."))

    @commands.hybrid_command(name="enablecommand", description="Réactiver une commande précédemment désactivée.", with_app_command=False)
    @app_commands.describe(commande="Le nom de la commande à réactiver")
    @checks.is_owner_or_admin()
    async def enablecommand(self, ctx: commands.Context, commande: str):
        await self.bot.db.execute(
            "DELETE FROM disabled_commands WHERE guild_id = ? AND command_name = ?",
            (ctx.guild.id, commande),
        )
        await ctx.send(embed=embeds.success(f"La commande `{commande}` a été réactivée."))

    @commands.hybrid_command(name="ignorechannel", description="Ignorer un salon (le bot n'y répondra plus).", with_app_command=False)
    @app_commands.describe(salon="Le salon à ignorer")
    @checks.is_owner_or_admin()
    async def ignorechannel(self, ctx: commands.Context, salon: discord.TextChannel = None):
        salon = salon or ctx.channel
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)",
            (ctx.guild.id, salon.id),
        )
        await ctx.send(embed=embeds.success(f"Le salon {salon.mention} est maintenant ignoré."))

    @commands.hybrid_command(name="unignorechannel", description="Ne plus ignorer un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon à ne plus ignorer")
    @checks.is_owner_or_admin()
    async def unignorechannel(self, ctx: commands.Context, salon: discord.TextChannel = None):
        salon = salon or ctx.channel
        await self.bot.db.execute(
            "DELETE FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
            (ctx.guild.id, salon.id),
        )
        await ctx.send(embed=embeds.success(f"Le salon {salon.mention} n'est plus ignoré."))

    @commands.hybrid_command(name="setlevelchannel", description="Définir le salon des annonces de niveau.", with_app_command=False)
    @app_commands.describe(salon="Le salon pour les annonces de niveau")
    @checks.is_owner_or_admin()
    async def setlevelchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "level_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des niveaux défini sur {salon.mention}."))

    @commands.hybrid_command(name="setsuggestchannel", description="Définir le salon des suggestions.", with_app_command=False)
    @app_commands.describe(salon="Le salon des suggestions")
    @checks.is_owner_or_admin()
    async def setsuggestchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "suggest_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des suggestions défini sur {salon.mention}."))

    @commands.hybrid_command(name="setannouncechannel", description="Définir le salon des annonces générales.", with_app_command=False)
    @app_commands.describe(salon="Le salon des annonces")
    @checks.is_owner_or_admin()
    async def setannouncechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "announce_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des annonces défini sur {salon.mention}."))

    @commands.hybrid_command(name="setgiveawaychannel", description="Définir le salon par défaut des giveaways.", with_app_command=False)
    @app_commands.describe(salon="Le salon par défaut des giveaways")
    @checks.is_owner_or_admin()
    async def setgiveawaychannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "giveaway_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des giveaways défini sur {salon.mention}."))

    @commands.hybrid_command(name="config-view", description="Afficher la configuration actuelle du serveur.")
    @checks.is_owner_or_admin()
    async def config_view(self, ctx: commands.Context):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        e = embeds.neutral("⚙️ Configuration du serveur")
        if not conf:
            e.description = "Aucune configuration définie pour l'instant."
            return await ctx.send(embed=e)

        def fmt_channel(cid):
            if not cid:
                return "Non défini"
            ch = ctx.guild.get_channel(cid)
            return ch.mention if ch else "Salon introuvable"

        def fmt_role(rid):
            if not rid:
                return "Non défini"
            r = ctx.guild.get_role(rid)
            return r.mention if r else "Rôle introuvable"

        e.add_field(name="Préfixe", value=f"`{conf['prefix'] or '+'}`", inline=True)
        e.add_field(name="Rôle staff", value=fmt_role(conf["mod_role"]), inline=True)
        e.add_field(name="Salon logs", value=fmt_channel(conf["log_channel"]), inline=True)
        e.add_field(name="Salon bienvenue", value=fmt_channel(conf["welcome_channel"]), inline=True)
        e.add_field(name="Salon départ", value=fmt_channel(conf["goodbye_channel"]), inline=True)
        e.add_field(name="Rôle auto", value=fmt_role(conf["autorole"]), inline=True)
        e.add_field(name="Catégorie tickets", value=fmt_channel(conf["ticket_category"]), inline=True)
        e.add_field(name="Logs tickets", value=fmt_channel(conf["ticket_log_channel"]), inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="config-reset", description="Réinitialiser toute la configuration du serveur.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def config_reset(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM guild_config WHERE guild_id = ?", (ctx.guild.id,))
        await self.bot.db.ensure_guild(ctx.guild.id)
        await ctx.send(embed=embeds.success("La configuration du serveur a été réinitialisée."))

    @commands.hybrid_command(name="setlanguage", description="Définir la langue du bot (actuellement français uniquement).", with_app_command=False)
    @app_commands.describe(langue="Code de langue (fr uniquement pour le moment)")
    @checks.is_owner_or_admin()
    async def setlanguage(self, ctx: commands.Context, langue: str = "fr"):
        await ctx.send(embed=embeds.info("Le bot fonctionne actuellement uniquement en français. 🇫🇷"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Configuration(bot))
