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
from web.dashboard import start_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bot")

# Liste des modules (cogs) à charger au démarrage.
EXTENSIONS = [
    "cogs.moderation",
    "cogs.automod",
    "cogs.security_tools",
    "cogs.tickets",
    "cogs.configuration",
    "cogs.server_builder",
    "cogs.logs",
    "cogs.utility",
    "cogs.ai",
    "cogs.economy",
    "cogs.levels",
    "cogs.minigames",
    "cogs.games_economy",  # +gamesetup (GamesSetup) est chargé automatiquement par son setup()
    "cogs.music",
    "cogs.events",
    "cogs.verification",
    "cogs.stats",
    "cogs.owner",
    "cogs.invites",
    "cogs.design",
    "cogs.embed_builder",
]

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True


class SentriXContext(commands.Context):
    """Context personnalisé utilisé pour TOUTES les commandes texte (préfixe +) du bot.

    Demande explicite : quand quelqu'un tape une commande texte, la réponse du bot doit
    être visiblement liée à son message (comme une "réponse" Discord, avec la petite
    flèche), et pinguer la personne SANS avoir besoin d'un @mention écrit dans le texte —
    sinon, sur un salon actif, on ne sait plus à quel message le bot répond.

    Les commandes SLASH (interaction) ne sont pas concernées : Discord affiche déjà
    nativement "SentriX a utilisé /commande" au-dessus de la réponse, donc le lien est
    déjà visible sans rien faire de plus — voir la condition `self.interaction is None`
    ci-dessous, qui limite ce comportement aux commandes préfixées uniquement."""

    async def send(self, *args, **kwargs):
        if self.interaction is None and self.message is not None and "reference" not in kwargs:
            kwargs["reference"] = discord.MessageReference(
                message_id=self.message.id,
                channel_id=self.channel.id,
                guild_id=self.guild.id if self.guild else None,
                fail_if_not_exists=False,
            )
            kwargs.setdefault("mention_author", True)
        try:
            return await super().send(*args, **kwargs)
        except discord.HTTPException:
            # Filet de sécurité : si la réponse en tant que "réponse à un message" échoue
            # pour une raison quelconque (message d'origine supprimé entre-temps, par
            # exemple par +clear, permissions insuffisantes...), on retombe sur un envoi
            # normal plutôt que de faire planter la commande.
            kwargs.pop("reference", None)
            kwargs.pop("mention_author", None)
            return await super().send(*args, **kwargs)


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
        # Cache mémoire de la liste noire GLOBALE d'utilisation du bot (/bl) : ce check
        # tourne sur QUASIMENT CHAQUE commande, tous serveurs confondus. Sur un gros
        # serveur très actif, interroger la base à chaque fois serait inutilement lourd
        # pour une liste qui change rarement (owner.py tient ce cache à jour).
        self.blacklist_cache: dict[int, str] = {}

    async def setup_hook(self):
        await self.db.connect()
        logger.info("Base de données connectée.")

        # DIAGNOSTIC DE PERSISTANCE — Railway (et la plupart des hébergeurs par conteneurs)
        # utilisent un disque JETABLE par défaut : si aucun volume persistant n'est monté
        # au bon endroit, le fichier SQLite repart de zéro à CHAQUE redémarrage/redéploiement,
        # et TOUTES les données (niveaux, économie, avertissements, tickets...) sont perdues
        # sans aucune erreur visible — ça ressemble juste à "les niveaux ne montent jamais".
        # Ce log permet de vérifier en un coup d'œil dans les logs Railway si la base est
        # bien conservée d'un déploiement à l'autre (le nombre de profils ne doit PAS
        # retomber à 0 après un redéploiement si un volume persistant est correctement monté).
        try:
            level_count = await self.db.fetchone("SELECT COUNT(*) AS n FROM levels")
            economy_count = await self.db.fetchone("SELECT COUNT(*) AS n FROM economy")
            logger.info(
                "Diagnostic de la base de données (chemin : %s) — %s profil(s) de niveau, "
                "%s compte(s) d'économie déjà enregistrés. Si ce nombre retombe à 0 après "
                "chaque redéploiement Railway, c'est qu'AUCUN volume persistant n'est monté "
                "sur le chemin de la base : voir Settings du service -> Volumes sur Railway.",
                config.DATABASE_PATH,
                level_count["n"] if level_count else 0,
                economy_count["n"] if economy_count else 0,
            )
        except Exception:
            logger.warning("Diagnostic de persistance de la base impossible :\n" + traceback.format_exc())

        rows = await self.db.blacklist_list()
        self.blacklist_cache = {r["user_id"]: (r["reason"] or "Aucune raison fournie") for r in rows}

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.info(f"Module chargé : {ext}")
            except Exception:
                logger.error(f"Échec du chargement du module {ext} :\n{traceback.format_exc()}")

        # Enregistrement des vues persistantes (boutons qui survivent aux redémarrages).
        # Le panel d'ouverture est propre à chaque panel configuré (options dynamiques) :
        # on le reconstruit avec ses VRAIES données depuis la base (restore_panel_views).
        # La vue de contrôle est générique (custom_id fixes) : un seul enregistrement suffit.
        try:
            from cogs.tickets import TicketControlView
            self.add_view(TicketControlView())
            tickets_cog = self.get_cog("Tickets")
            if tickets_cog:
                panels_restored = await tickets_cog.restore_panel_views()
                # Diagnostic demandé : confirmer en un coup d'œil, à chaque démarrage, que le
                # module tickets est bien chargé et que ses panels/vues survivent au redémarrage
                # (utile pour retrouver la cause d'un "L'application ne répond plus" — si ce
                # log manque ou affiche 0 alors qu'il devrait y avoir des panels, le problème
                # vient du chargement, pas d'une commande précise).
                ticket_cmd_count = len([c for c in self.commands if c.cog_name == "Tickets"])
                logger.info(
                    "Cog Tickets : chargé — %s commande(s) tickets, %s panel(s) actif(s) restauré(s) en vue persistante.",
                    ticket_cmd_count, panels_restored,
                )
            else:
                logger.error("Cog Tickets introuvable après le chargement des extensions — les commandes de tickets ne fonctionneront pas.")
        except Exception:
            logger.warning("Impossible d'enregistrer les vues de tickets :\n" + traceback.format_exc())

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

        # Boutons de navigation du /setup (◀ 💾 ▶ 👁️ ○) : contrairement aux vues ci-dessus,
        # ce sont des "dynamic items" (discord.py >= 2.4) dont le custom_id encode l'ID du
        # message. add_dynamic_items() permet à Discord de les faire fonctionner même après
        # un redémarrage, en reconstruisant l'assistant depuis la table setup_sessions
        # (voir Configuration.handle_setup_nav) — c'est ce qui rend /setup persistant.
        try:
            from cogs.configuration import SetupNavButton
            self.add_dynamic_items(SetupNavButton)
        except Exception:
            logger.warning("Impossible d'enregistrer les boutons de /setup :\n" + traceback.format_exc())

        self.add_check(self.global_blacklist_check)
        self.add_check(self.global_cooldown_check)

        try:
            synced = await self.tree.sync()
            logger.info(f"{len(synced)} commandes slash synchronisées globalement.")
        except Exception:
            logger.error(f"Échec de la synchronisation des commandes slash :\n{traceback.format_exc()}")

        # Dashboard web (voir web/dashboard.py) : tourne dans le même processus, sur le
        # port fourni par Railway (variable PORT). Ne bloque jamais le démarrage du bot
        # si ça échoue (ex: port déjà utilisé en local).
        asyncio.create_task(start_dashboard(self))

    async def global_blacklist_check(self, ctx: commands.Context) -> bool:
        """Bloque tout utilisateur inscrit sur la liste noire GLOBALE d'utilisation du bot
        (/bl, cog Owner) — sur n'importe quelle commande, n'importe quel serveur."""
        if ctx.author.id in config.OWNER_IDS or await self.db.is_bot_creator(ctx.author.id):
            return True
        reason = self.blacklist_cache.get(ctx.author.id)
        if reason is not None:
            raise BotBlacklistedError(reason)
        return True

    async def global_cooldown_check(self, ctx: commands.Context) -> bool:
        if ctx.author.id in config.OWNER_IDS or await self.db.is_bot_creator(ctx.author.id):
            return True
        bucket = self._cooldown_bucket.get_bucket(ctx.message if not ctx.interaction else ctx)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            raise commands.CommandOnCooldown(bucket, retry_after, commands.BucketType.user)
        return True

    async def get_context(self, message, *, cls=SentriXContext):
        """Ajoute la résolution des alias de commandes (/alias, cog Owner) : si le mot tapé
        après le préfixe ne correspond à aucune commande connue, on regarde si c'est un alias
        configuré sur ce serveur et, si oui, on redirige vers la vraie commande.

        cls=SentriXContext par défaut (au lieu de commands.Context) : voir la classe
        SentriXContext plus haut — fait que chaque réponse à une commande texte soit
        visuellement liée au message qui l'a déclenchée (réponse Discord + ping)."""
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

        # Vérification de persistance (complète le diagnostic de setup_hook, ici self.guilds
        # est enfin peuplé) : si le bot est réellement présent sur des serveurs mais qu'AUCUNE
        # configuration ni donnée n'existe en base, c'est le signe très probable d'un disque
        # Railway non persistant qui vient de repartir de zéro (perte niveaux/économie/etc.).
        # Ne se déclenche qu'une fois par processus pour ne pas spammer en cas de reconnexion.
        if not getattr(self, "_persistence_check_done", False):
            self._persistence_check_done = True
            try:
                if self.guilds:
                    guild_config_count = await self.db.fetchone("SELECT COUNT(*) AS n FROM guild_config")
                    known_guilds = guild_config_count["n"] if guild_config_count else 0
                    if known_guilds == 0:
                        warning_text = (
                            f"⚠️ SentriX est présent sur {len(self.guilds)} serveur(s) mais AUCUNE "
                            "configuration n'existe en base (table guild_config vide). C'est le signe "
                            "typique d'un redéploiement Railway SANS volume persistant : le fichier "
                            f"SQLite ({config.DATABASE_PATH}) repart de zéro à chaque redémarrage, et "
                            "toutes les données (niveaux, économie, avertissements, logs configurés...) "
                            "sont perdues silencieusement. Pour corriger définitivement : dans Railway, "
                            "Settings du service → Volumes → ajouter un volume monté sur le dossier "
                            "contenant la base, puis vérifier que DATABASE_PATH pointe bien dedans."
                        )
                        logger.warning(warning_text)
                        owner_ids = set(getattr(config, "OWNER_IDS", []))
                        owner_ids.update(await self.db.list_bot_creator_ids())
                        for owner_id in owner_ids:
                            try:
                                owner = await self.fetch_user(owner_id)
                                await owner.send(embed=embeds.warning(warning_text))
                            except (discord.HTTPException, discord.Forbidden):
                                pass
            except Exception:
                logger.warning("Vérification de persistance (on_ready) impossible :\n" + traceback.format_exc())

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

        if isinstance(error, commands.UserNotFound):
            # /bl (et blinfo/unbl/editbl) attendent un UTILISATEUR (mention ou ID) : ce n'est pas
            # la même chose que la liste de mots interdits, qui est une commande différente.
            # Erreur fréquente si on essaie de blacklister un mot avec /bl : on redirige clairement.
            if ctx.command and ctx.command.qualified_name in {"bl", "blinfo", "unbl", "editbl"}:
                return await ctx.send(embed=embeds.error(
                    f"`{error.argument}` n'est pas un membre valide (mention `@membre` ou ID attendu).\n\n"
                    "**`/bl`** bloque un **utilisateur** sur tout le bot (aucune commande nulle part).\n"
                    "Pour interdire un **mot** (ex: une insulte) dans les messages de ce serveur, utilisez "
                    "**`/blacklist-add <mot>`** à la place — c'est une fonction différente."
                ))
            return await ctx.send(embed=embeds.error("Utilisateur introuvable. Vérifiez la mention ou l'ID."))

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
