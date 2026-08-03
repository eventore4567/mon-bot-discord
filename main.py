"""
Bot Discord tout-en-un — point d'entrée principal.

Fonctionne avec des commandes slash (/) ET des commandes textuelles avec préfixe (+
par défaut, configurable par serveur via /setprefix).

Pour lancer le bot : python3 main.py
Le token doit être défini dans le fichier .env (variable DISCORD_TOKEN).
"""

import asyncio
import logging
import traceback

import discord
from discord.ext import commands

import config
from database.db import Database
from utils import embeds
from utils.checks import BotPermissionError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bot")

# Liste des modules (cogs) à charger au démarrage.
EXTENSIONS = [
    "cogs.moderation",
    "cogs.automod",
    "cogs.tickets",
    "cogs.configuration",
    "cogs.utility",
    "cogs.ai",
    "cogs.economy",
    "cogs.levels",
    "cogs.minigames",
    "cogs.music",
    "cogs.events",
    "cogs.verification",
    "cogs.stats",
]

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True


async def get_prefix(bot: "BotAllInOne", message: discord.Message):
    default = config.DEFAULT_PREFIX
    if message.guild is None:
        return commands.when_mentioned_or(default)(bot, message)
    try:
        conf = await bot.db.get_guild_config(message.guild.id)
        prefix = conf["prefix"] if conf and conf["prefix"] else default
    except Exception:
        prefix = default
    return commands.when_mentioned_or(prefix)(bot, message)


class BotAllInOne(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=get_prefix,
            intents=INTENTS,
            help_command=None,
            case_insensitive=True,
        )
        self.db = Database(config.DATABASE_PATH)
        self._cooldown_bucket = commands.CooldownMapping.from_cooldown(
            config.GLOBAL_COOLDOWN_RATE, config.GLOBAL_COOLDOWN_PER, commands.BucketType.user
        )

    async def setup_hook(self):
        await self.db.connect()
        logger.info("Base de données connectée.")

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.info(f"Module chargé : {ext}")
            except Exception:
                logger.error(f"Échec du chargement du module {ext} :\n{traceback.format_exc()}")

        # Enregistrement des vues persistantes (boutons qui survivent aux redémarrages).
        try:
            from cogs.tickets import TicketPanelView, TicketControlView
            self.add_view(TicketPanelView())
            self.add_view(TicketControlView())
        except Exception:
            logger.warning("Impossible d'enregistrer les vues de tickets.")

        try:
            from cogs.verification import VerifyView
            self.add_view(VerifyView())
        except Exception:
            logger.warning("Impossible d'enregistrer la vue de vérification.")

        try:
            from cogs.events import GiveawayView
            self.add_view(GiveawayView())
        except Exception:
            logger.warning("Impossible d'enregistrer la vue de giveaway.")

        self.add_check(self.global_cooldown_check)

        try:
            synced = await self.tree.sync()
            logger.info(f"{len(synced)} commandes slash synchronisées globalement.")
        except Exception:
            logger.error(f"Échec de la synchronisation des commandes slash :\n{traceback.format_exc()}")

    async def global_cooldown_check(self, ctx: commands.Context) -> bool:
        if ctx.author.id in config.OWNER_IDS:
            return True
        bucket = self._cooldown_bucket.get_bucket(ctx.message if not ctx.interaction else ctx)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            raise commands.CommandOnCooldown(bucket, retry_after, commands.BucketType.user)
        return True

    async def on_ready(self):
        logger.info(f"Connecté en tant que {self.user} (ID: {self.user.id})")
        logger.info(f"Présent sur {len(self.guilds)} serveur(s).")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=f"{config.DEFAULT_PREFIX}help")
        )
        for guild in self.guilds:
            await self.db.ensure_guild(guild.id)

    async def on_guild_join(self, guild: discord.Guild):
        await self.db.ensure_guild(guild.id)
        logger.info(f"Bot ajouté au serveur : {guild.name} ({guild.id})")

    async def on_member_join(self, member: discord.Member):
        conf = await self.db.get_guild_config(member.guild.id)
        if not conf:
            return
        if conf["autorole"]:
            role = member.guild.get_role(conf["autorole"])
            if role:
                try:
                    await member.add_roles(role, reason="Rôle automatique à l'arrivée")
                except discord.Forbidden:
                    pass
        if conf["welcome_channel"]:
            channel = member.guild.get_channel(conf["welcome_channel"])
            if channel:
                text = conf["welcome_message"] or "Bienvenue {member} sur **{server}** !"
                text = text.replace("{member}", member.mention).replace("{server}", member.guild.name)
                try:
                    await channel.send(embed=embeds.success(text))
                except discord.HTTPException:
                    pass

    async def on_member_remove(self, member: discord.Member):
        conf = await self.db.get_guild_config(member.guild.id)
        if not conf or not conf["goodbye_channel"]:
            return
        channel = member.guild.get_channel(conf["goodbye_channel"])
        if channel:
            text = conf["goodbye_message"] or "{member} a quitté **{server}**."
            text = text.replace("{member}", str(member)).replace("{server}", member.guild.name)
            try:
                await channel.send(embed=embeds.neutral("👋 Départ", text))
            except discord.HTTPException:
                pass

    async def on_command_completion(self, ctx: commands.Context):
        if ctx.guild:
            try:
                await self.db.execute(
                    "INSERT INTO command_logs (guild_id, user_id, command_name, timestamp) VALUES (?, ?, ?, strftime('%s','now'))",
                    (ctx.guild.id, ctx.author.id, ctx.command.qualified_name),
                )
            except Exception:
                pass

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        error = getattr(error, "original", error)

        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, BotPermissionError):
            return await ctx.send(embed=embeds.error(error.message))

        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.send(
                embed=embeds.warning(f"⏳ Doucement ! Réessayez dans **{error.retry_after:.1f}** secondes.")
            )

        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            return await ctx.send(embed=embeds.error(f"Il vous manque les permissions suivantes : `{perms}`"))

        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            return await ctx.send(embed=embeds.error(f"Je n'ai pas les permissions nécessaires : `{perms}`"))

        if isinstance(error, commands.MemberNotFound):
            return await ctx.send(embed=embeds.error("Membre introuvable. Vérifiez le nom ou la mention."))

        if isinstance(error, commands.ChannelNotFound):
            return await ctx.send(embed=embeds.error("Salon introuvable."))

        if isinstance(error, commands.RoleNotFound):
            return await ctx.send(embed=embeds.error("Rôle introuvable."))

        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.send(embed=embeds.error(f"Il manque un argument : `{error.param.name}`"))

        if isinstance(error, commands.BadArgument):
            return await ctx.send(embed=embeds.error("Argument invalide. Vérifiez la syntaxe de la commande."))

        if isinstance(error, discord.Forbidden):
            return await ctx.send(embed=embeds.error("Je n'ai pas la permission d'effectuer cette action."))

        if isinstance(error, commands.CheckFailure):
            return await ctx.send(embed=embeds.error("Vous n'êtes pas autorisé à utiliser cette commande."))

        logger.error(f"Erreur non gérée dans la commande {ctx.command} :\n{traceback.format_exc()}")
        await ctx.send(embed=embeds.error("Une erreur inattendue est survenue. L'équipe a été informée."))


async def main():
    bot = BotAllInOne()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Arrêt du bot.")
