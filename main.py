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
from utils.checks import BotPermissionError, BotBlacklistedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bot")

# Liste des modules (cogs) à charger au démarrage.
EXTENSIONS = [
    "cogs.moderation",
    "cogs.automod",
    "cogs.tickets",
    "cogs.configuration",
    "cogs.server_builder",
    "cogs.utility",
    "cogs.ai",
    "cogs.economy",
    "cogs.levels",
    "cogs.minigames",
    "cogs.music",
    "cogs.events",
    "cogs.verification",
    "cogs.stats",
    "cogs.owner",
    "cogs.invites",
]

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True


async def get_prefix(bot: "BotAllInOne", message: discord.Message):
    default = config.DEFAULT_PREFIX
    if message.guild is None:
        return commands.when_mentioned_or(default)(bot, message)

    # Sur un gros serveur, un message arrive plusieurs fois par seconde : on ne veut
    # surtout pas interroger la base de données à chaque message. On garde donc le
    # préfixe de chaque serveur en mémoire (rafraîchi uniquement par /setprefix).
    cached = bot.prefix_cache.get(message.guild.id)
    if cached is not None:
        return commands.when_mentioned_or(cached)(bot, message)

    try:
        conf = await bot.db.get_guild_config(message.guild.id)
        prefix = conf["prefix"] if conf and conf["prefix"] else default
    except Exception:
        prefix = default
    bot.prefix_cache[message.guild.id] = prefix
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
        # Cache mémoire des préfixes par serveur (voir get_prefix ci-dessus) : évite
        # une requête DB à chaque message sur un serveur actif.
        self.prefix_cache: dict[int, str] = {}

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

        self.add_check(self.global_blacklist_check)
        self.add_check(self.global_cooldown_check)

        try:
            synced = await self.tree.sync()
            logger.info(f"{len(synced)} commandes slash synchronisées globalement.")
        except Exception:
            logger.error(f"Échec de la synchronisation des commandes slash :\n{traceback.format_exc()}")

    async def global_blacklist_check(self, ctx: commands.Context) -> bool:
        """Bloque tout utilisateur inscrit sur la liste noire GLOBALE d'utilisation du bot
        (/bl, cog Owner) — sur n'importe quelle commande, n'importe quel serveur."""
        if ctx.author.id in config.OWNER_IDS:
            return True
        row = await self.db.blacklist_get(ctx.author.id)
        if row:
            raise BotBlacklistedError(row["reason"] or "Aucune raison fournie")
        return True

    async def global_cooldown_check(self, ctx: commands.Context) -> bool:
        if ctx.author.id in config.OWNER_IDS:
            return True
        bucket = self._cooldown_bucket.get_bucket(ctx.message if not ctx.interaction else ctx)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            raise commands.CommandOnCooldown(bucket, retry_after, commands.BucketType.user)
        return True

    async def get_context(self, message, *, cls=commands.Context):
        """Ajoute la résolution des alias de commandes (/alias, cog Owner) : si le mot tapé
        après le préfixe ne correspond à aucune commande connue, on regarde si c'est un alias
        configuré sur ce serveur et, si oui, on redirige vers la vraie commande."""
        ctx = await super().get_context(message, cls=cls)
        if ctx.command is None and ctx.guild is not None and ctx.invoked_with:
            row = await self.db.get_alias(ctx.guild.id, ctx.invoked_with.lower())
            if row:
                real_command = self.get_command(row["command_name"])
                if real_command:
                    ctx.command = real_command
        return ctx

    async def on_ready(self):
        logger.info(f"Connecté en tant que {self.user} (ID: {self.user.id})")
        logger.info(f"Présent sur {len(self.guilds)} serveur(s).")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=f"{config.DEFAULT_PREFIX}help")
        )
        # Identité visuelle : une fois connecté, on affiche l'avatar du bot dans le footer de tous les embeds.
        embeds.set_footer_icon(self.user.display_avatar.url)

        # Recharge les réglages de branding persistés (/footer, /theme) : sans ça, ils
        # reviendraient aux valeurs par défaut à chaque redémarrage/redéploiement Railway.
        saved_footer = await self.db.get_setting("footer_text")
        if saved_footer:
            embeds.set_footer_text(saved_footer)
        saved_color = await self.db.get_setting("brand_color")
        if saved_color:
            try:
                embeds.set_brand_color(int(saved_color))
            except ValueError:
                pass

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
            # Écriture en tâche de fond : la réponse à la commande est déjà partie,
            # pas la peine de faire attendre quoi que ce soit pour un simple journal.
            asyncio.create_task(self._log_command(ctx))

    async def _log_command(self, ctx: commands.Context):
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

        if isinstance(error, BotBlacklistedError):
            return await ctx.send(embed=embeds.error(f"Vous n'êtes pas autorisé à utiliser ce bot.\nRaison : {error.reason}"))

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
