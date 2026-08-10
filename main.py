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
from database.db import Database, PRIMARY_CREATOR_ID
from utils import embeds
from utils.checks import (
    BotPermissionError,
    BotBlacklistedError,
    can_use_embed_builder,
    is_mod_or_permission,
    is_verified_bot_owner,
)
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
    "cogs.notifications",
    "cogs.ai",
    "cogs.economy",
    "cogs.levels",
    "cogs.minigames",
    "cogs.games_economy",
    "cogs.music",
    "cogs.events",
    "cogs.verification",
    "cogs.stats",
    "cogs.owner",
    "cogs.invites",
    "cogs.design",
    "cogs.embed_builder",
]

# Les réglages ci-dessous existent déjà dans les panneaux interactifs. Ils restent
# implémentés dans leurs cogs afin que les boutons et les données historiques continuent
# de fonctionner, mais ne sont plus enregistrés comme commandes publiques.
COMMANDS_REPLACED_BY_SETUP = frozenset({
    "setprefix", "setmodrole", "setlogchannel", "create-logs", "logs",
    "setwelcomechannel", "setgoodbyechannel", "setwelcomemessage",
    "setgoodbyemessage", "setticketlogchannel", "setautorole", "createrole",
    "setlevelchannel", "setsuggestchannel", "setannouncechannel",
    "setgiveawaychannel", "verify-setup", "set-level-role",
    "remove-level-role", "level-roles", "levelroles", "ticketpanel",
    "ticketpanel-toggle", "tickettype", "ticketform", "ticketconfig",
    "ticketlogs", "ticketlimit", "ticketautoclose",
})

# Alias historiques et commandes qui exécutent exactement la même action qu'une commande
# principale conservée. Les fonctionnalités restent accessibles via +ai, +stats, +level,
# +economyleaderboard, +buy, +embed et +ping.
EXACT_DUPLICATE_COMMANDS = frozenset({
    "leaderboard-money", "me", "rank", "buyrole", "ask", "chat",
    "chat-reset", "embed-create", "latency",
})

PRUNED_COMMANDS = COMMANDS_REPLACED_BY_SETUP | EXACT_DUPLICATE_COMMANDS


# Politique de sécurité centrale. Une commande absente de cette liste est considérée
# comme sensible et réservée aux administrateurs par défaut (fail-closed). Les checks
# présents dans les cogs restent actifs : cette politique est un second verrou qui évite
# qu'un oubli de décorateur rende accidentellement une commande administrative publique.
PUBLIC_COMMANDS = frozenset({
    # Aide et utilitaires sans modification du serveur
    "help", "ping", "avatar", "info", "userinfo",
    "channelinfo", "membercount", "emoji-list", "poll", "remind",
    "reminder-list", "reminder-cancel", "translate", "weather", "suggest",
    "report-bug", "afk", "roll", "choose",
    # Intelligence artificielle
    "sentrix", "ask", "chat-reset", "summarize", "image-prompt", "image",
    "explain", "rewrite", "fact-check", "ai", "chat", "improve", "correct",
    "ai-translate", "code",
    # Économie et niveaux
    "balance", "economy", "daily", "weekly", "work", "rob", "pay",
    "economyleaderboard", "leaderboard-money", "shop", "buy", "buyrole",
    "inventory", "sell", "gamble", "deposit", "withdraw", "banque",
    "stats", "me", "level", "rank", "leaderboard-levels", "level-roles",
    "profile", "set-bio", "rep", "reputation", "repleaderboard", "voice-time",
    # Tickets, événements et invitations accessibles aux membres
    "ticket", "giveaway-list", "event-join", "event-leave", "event-list",
    "tournament-join", "tournament-list", "invites", "invite-leaderboard",
    "invited-by",
    # Statistiques publiques
    "bot-status", "server-growth", "command-stats", "latency", "changelog",
    "feedback", "botinfo",
    # Mini-jeux
    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",
    "blackjack", "slots",
    "coinflip", "dice", "luckyroll", "highlow", "memory", "reaction",
    "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype", "duel",
    "connect4", "numberduel", "reactionduel", "quizduel", "triviastart",
    "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage",
    "emoji-race", "adventure", "dungeon", "mining", "fishing", "treasure",
    "hunt", "explore", "gamehistory", "gameprofile", "gamestats", "gametop",
    "dailygames",
    # Musique
    "join", "leave", "play", "pause", "resume", "skip", "stop", "queue",
    "nowplaying", "volume", "loop", "shuffle", "remove-from-queue",
    "clear-queue", "playlist-save", "playlist-load",
})

OWNER_ONLY_COMMANDS = frozenset({
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
    "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
})

CATEGORY_COMMANDS = {
    "configuration": frozenset({
        "setprefix", "setmodrole", "setlogchannel", "create-logs", "logs-status",
        "logsetup", "logs", "setwelcomechannel", "setgoodbyechannel",
        "setwelcomemessage", "setgoodbyemessage", "setticketlogchannel",
        "setautorole", "createrole", "setwarnrole", "setwarnbanthreshold",
        "disablecommand", "enablecommand", "ignorechannel", "unignorechannel",
        "setlevelchannel", "setsuggestchannel", "setannouncechannel",
        "setgiveawaychannel", "config-view", "config-reset", "setup",
        "create-server", "delete-channel", "verify-setup", "verify-panel",
        "rolepanel", "rolepanel-refresh", "reactionrole-add",
        "reactionrole-remove", "reactionrole-list", "set-level-role",
        "remove-level-role", "set-xp", "add-xp", "reset-levels", "levelcheck",
        "levelrepair", "repconfig", "repadd", "repremove", "represet",
        "rephistory", "statsconfig", "levelroles", "addbonusinvites",
        "removebonusinvites", "invitebonushistory", "designsetup",
        "embedconfig", "giveaway-create", "giveaway-end", "giveaway-reroll",
        "giveaway-cancel", "giveaway-blacklist", "giveaway-unblacklist",
        "event-create", "event-cancel", "tournament-create",
        "tournament-start", "announce", "notifs-ping", "notifs-list",
        "notifs-remove", "welcome-config",
        "set-nickname", "alias", "diagnostic",
    }),
    "tickets": frozenset({
        "ticketsetup", "ticketpanel", "ticketpanel-toggle", "tickettype",
        "ticketform", "ticketconfig", "ticketlogs", "ticketlimit",
        "ticketautoclose",
    }),
    "moderation": frozenset({"sanctiondm"}),
    "securite": frozenset({
        "antispam", "antilink", "antiinvite", "antimention", "anticaps",
        "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam",
        "antinuke", "antinuke-whitelist-add", "antinuke-whitelist-remove",
        "antinuke-whitelist-list", "lockdown-server", "unlock-server",
        "automod-status", "security-check", "automod-escalation",
        "automod-exempt-role-add", "automod-exempt-role-remove",
        "automod-history", "security-level", "blacklist-add",
        "blacklist-remove", "blacklist-list", "blacklist-user",
        "unblacklist-user", "blacklist-users", "whitelist-domain",
        "unwhitelist-domain", "permission-audit", "server-backup",
        "server-restore", "syncbl", "unsyncbl",
    }),
    "economie": frozenset({
        "shopsetup", "shoppanel", "shoprole", "give-money", "reset-economy",
        "gamesetup",
    }),
    "ai": frozenset({"aisetup", "aidiag"}),
    "complete": frozenset({"wipe-server", "roleall", "massrole"}),
}

DISCORD_PERMISSION_COMMANDS = {
    "ban": "ban_members",
    "tempban": "ban_members",
    "unban": "ban_members",
    "kick": "kick_members",
    "mute": "moderate_members",
    "unmute": "moderate_members",
    "warn": "moderate_members",
    "unwarn": "moderate_members",
    "warnings": "moderate_members",
    "clearwarnings": "moderate_members",
    "case": "moderate_members",
    "modhistory": "moderate_members",
    "quarantine": "moderate_members",
    "unquarantine": "moderate_members",
    "clear": "manage_messages",
    "say": "manage_messages",
    "embed-create": "manage_messages",
    "slowmode": "manage_channels",
    "lock": "manage_channels",
    "unlock": "manage_channels",
    "hide": "manage_channels",
    "show": "manage_channels",
    "ticket-reopen": "manage_channels",
    "tickettranscript": "manage_channels",
    "ticketstats": "manage_channels",
    "nickname": "manage_nicknames",
    "resetnick": "manage_nicknames",
    "move": "move_members",
    "disconnect": "move_members",
    "role-snapshot": "manage_roles",
    "role-restore": "manage_roles",
    "giverole": "manage_roles",
    "removerole": "manage_roles",
    "addemoji": "manage_emojis_and_stickers",
    "deleteemoji": "manage_emojis_and_stickers",
}

CUSTOM_PERMISSION_COMMANDS = frozenset({"embed"})
KNOWN_PERMISSION_COMMANDS = (
    PUBLIC_COMMANDS
    | OWNER_ONLY_COMMANDS
    | CUSTOM_PERMISSION_COMMANDS
    | frozenset(DISCORD_PERMISSION_COMMANDS)
    | frozenset().union(*CATEGORY_COMMANDS.values())
)


PERMISSION_LABELS = {
    "administrator": "Administrateur",
    "manage_guild": "Gérer le serveur",
    "manage_channels": "Gérer les salons",
    "manage_roles": "Gérer les rôles",
    "manage_messages": "Gérer les messages",
    "manage_nicknames": "Gérer les pseudos",
    "moderate_members": "Exclure temporairement des membres",
    "kick_members": "Expulser des membres",
    "ban_members": "Bannir des membres",
    "move_members": "Déplacer des membres",
    "manage_emojis_and_stickers": "Gérer les expressions",
}


def format_permissions(permission_names) -> str:
    return ", ".join(PERMISSION_LABELS.get(name, name.replace("_", " ").capitalize()) for name in permission_names)


def command_usage(ctx: commands.Context) -> str | None:
    """Construit une syntaxe directement réutilisable dans les messages d'erreur."""
    command = ctx.command
    if command is None:
        return None
    prefix = getattr(ctx, "clean_prefix", None) or "+"
    signature = getattr(command, "signature", "") or ""
    return f"{prefix}{command.qualified_name} {signature}".strip()


def cooldown_text(seconds: float) -> str:
    total = max(1, round(seconds))
    minutes, remaining = divmod(total, 60)
    if minutes:
        return f"{minutes} min {remaining:02d} s"
    return f"{remaining} s"


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
        self.expected_extension_count = len(EXTENSIONS)
        # Un gestionnaire unique garantit des réponses françaises et utiles aussi pour les commandes slash.
        self.tree.on_error = self.on_app_command_error
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

    def _prune_redundant_commands(self) -> list[str]:
        """Retire les anciennes entrées de commande sans supprimer leurs implémentations.

        Les panneaux setup appellent directement leurs services et la base de données :
        conserver les méthodes internes permet donc aux boutons persistants et aux anciens
        panneaux de continuer à fonctionner, tout en allégeant +help et les commandes slash.
        """
        removed_names: list[str] = []
        for requested_name in sorted(PRUNED_COMMANDS):
            command = self.get_command(requested_name)
            if command is None:
                continue

            root_name = command.root_parent.name if command.root_parent else command.name
            removed = self.remove_command(root_name)
            if removed is None:
                continue
            removed_names.append(root_name)

            app_command = getattr(removed, "app_command", None)
            app_name = getattr(app_command, "name", None)
            if app_name and self.tree.get_command(app_name):
                self.tree.remove_command(app_name)

        logger.info(
            "Nettoyage des commandes : %s commande(s) redondante(s) retirée(s) — %s",
            len(removed_names),
            ", ".join(sorted(removed_names)) or "aucune",
        )
        return removed_names

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

        # Le nettoyage se fait après le chargement des cogs et avant tree.sync() : les
        # commandes disparaissent donc à la fois du préfixe, de +help et des slash Discord.
        self._prune_redundant_commands()
        self._audit_command_permissions()

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
        self.add_check(self.global_permission_check)

        try:
            synced = await self.tree.sync()
            logger.info(f"{len(synced)} commandes slash synchronisées globalement.")
        except Exception:
            logger.error(f"Échec de la synchronisation des commandes slash :\n{traceback.format_exc()}")

        # Dashboard web (voir web/dashboard.py) : tourne dans le même processus, sur le
        # port fourni par Railway (variable PORT). Ne bloque jamais le démarrage du bot
        # si ça échoue (ex: port déjà utilisé en local).
        asyncio.create_task(start_dashboard(self))

    def _audit_command_permissions(self) -> None:
        """Signale au démarrage toute nouvelle commande non classée.

        Une commande non classée reste bloquée pour les membres ordinaires par
        global_permission_check(). Ce diagnostic empêche qu'une future commande sensible
        soit ajoutée silencieusement sans décision explicite sur son niveau d'accès.
        """
        registered = {command.name.lower() for command in self.commands}
        unknown = sorted(registered - KNOWN_PERMISSION_COMMANDS)
        if unknown:
            logger.warning(
                "Sécurité : %s commande(s) non classée(s), accès administrateur appliqué "
                "par défaut — %s",
                len(unknown),
                ", ".join(unknown),
            )
        else:
            logger.info(
                "Sécurité : %s commande(s) classée(s), aucune commande sans politique d'accès.",
                len(registered),
            )

    async def _has_manager_access(self, ctx: commands.Context, category: str) -> bool:
        """Vérifie propriétaire, administrateur ou gestionnaire autorisé pour une catégorie."""
        if await is_verified_bot_owner(ctx):
            return True
        if not isinstance(ctx.author, discord.Member) or ctx.guild is None:
            return False
        if ctx.author.guild_permissions.administrator:
            return True
        if not await self.db.is_bot_manager(ctx.guild.id, ctx.author.id):
            return False
        return await self.db.has_manager_permission(ctx.guild.id, ctx.author.id, category)

    async def global_permission_check(self, ctx: commands.Context) -> bool:
        """Second verrou obligatoire pour toutes les commandes, préfixées et slash.

        Les checks locaux des cogs continuent de contrôler la hiérarchie et les détails.
        Ici, une commande inconnue est refusée aux membres par défaut : la sécurité ne
        dépend donc plus d'un décorateur qui pourrait être oublié.
        """
        command = ctx.command
        if command is None:
            return True
        root = command.root_parent or command
        name = root.name.lower()

        if name in PUBLIC_COMMANDS:
            return True

        if name in OWNER_ONLY_COMMANDS:
            if await is_verified_bot_owner(ctx):
                return True
            raise BotPermissionError(
                "Cette commande est réservée au propriétaire vérifié du bot."
            )

        if name in CUSTOM_PERMISSION_COMMANDS:
            if await can_use_embed_builder(ctx):
                return True
            raise BotPermissionError(
                "Cette commande est réservée au staff autorisé à créer des embeds."
            )

        required_permission = DISCORD_PERMISSION_COMMANDS.get(name)
        if required_permission is not None:
            if await is_mod_or_permission(ctx, required_permission):
                return True
            raise BotPermissionError(
                "Cette commande est réservée au staff autorisé. "
                f"Permission requise : `{required_permission}` ou rôle de modération configuré."
            )

        for category, names in CATEGORY_COMMANDS.items():
            if name not in names:
                continue
            if await self._has_manager_access(ctx, category):
                return True
            raise BotPermissionError(
                "Cette commande de gestion est réservée aux administrateurs ou à un "
                f"gestionnaire autorisé pour la catégorie `{category}`."
            )

        # Fail-closed : toute future commande oubliée dans la politique est protégée.
        if await self._has_manager_access(ctx, "complete"):
            return True
        raise BotPermissionError(
            "Cette commande n'a pas encore de niveau d'accès public validé. "
            "Elle est réservée aux administrateurs par sécurité."
        )

    async def global_blacklist_check(self, ctx: commands.Context) -> bool:
        """Bloque tout utilisateur inscrit sur la liste noire GLOBALE d'utilisation du bot
        (/bl, cog Owner) — sur n'importe quelle commande, n'importe quel serveur."""
        # Le créateur principal doit rester reconnu même si SQLite est verrouillée :
        # sinon le check global plante AVANT la commande et produit une erreur générique.
        if ctx.author.id == PRIMARY_CREATOR_ID or ctx.author.id in config.OWNER_IDS:
            return True
        if await self.db.is_bot_creator(ctx.author.id):
            return True
        reason = self.blacklist_cache.get(ctx.author.id)
        if reason is not None:
            raise BotBlacklistedError(reason)
        return True

    async def global_cooldown_check(self, ctx: commands.Context) -> bool:
        if ctx.author.id == PRIMARY_CREATOR_ID or ctx.author.id in config.OWNER_IDS:
            return True
        if await self.db.is_bot_creator(ctx.author.id):
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
                text = (
                    text.replace("{member}", member.mention)
                    .replace("{server}", member.guild.name)
                    .replace("{username}", member.display_name)
                    .replace("{member_count}", str(member.guild.member_count or 0))
                )
                try:
                    welcome_embed = embeds.success(text, title=f"Bienvenue {member.display_name}")
                    welcome_embed.set_thumbnail(url=member.display_avatar.url)
                    if conf["welcome_image_url"]:
                        welcome_embed.set_image(url=conf["welcome_image_url"])
                    await channel.send(embed=welcome_embed)
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
                embed=embeds.warning(
                    f"Cette commande est temporairement en recharge. Vous pourrez la réutiliser dans "
                    f"**{cooldown_text(error.retry_after)}**."
                )
            )

        if isinstance(error, commands.MissingPermissions):
            perms = format_permissions(error.missing_permissions)
            return await ctx.send(embed=embeds.error(
                f"Votre rôle ne possède pas les autorisations nécessaires pour cette action.\n"
                f"Permission(s) requise(s) : **{perms}**."
            ))

        if isinstance(error, commands.BotMissingPermissions):
            perms = format_permissions(error.missing_permissions)
            return await ctx.send(embed=embeds.error(
                f"Le bot ne peut pas terminer cette action car il lui manque : **{perms}**.\n"
                "Un administrateur doit corriger les permissions du rôle SentriX et vérifier qu’il est placé assez haut."
            ))

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
            usage = command_usage(ctx)
            detail = f"\nSyntaxe correcte : `{usage}`" if usage else ""
            return await ctx.send(embed=embeds.error(
                f"L’argument **{error.param.name}** est obligatoire.{detail}\n"
                f"Consultez `{ctx.clean_prefix}help {ctx.command.qualified_name}` pour le détail des paramètres."
            ))

        if isinstance(error, commands.BadArgument):
            usage = command_usage(ctx)
            detail = f"\nSyntaxe correcte : `{usage}`" if usage else ""
            return await ctx.send(embed=embeds.error(
                "Une valeur fournie n’est pas reconnue. Vérifiez les mentions, nombres et noms indiqués."
                + detail
            ))

        if isinstance(error, discord.Forbidden):
            return await ctx.send(embed=embeds.error(
                "Discord a refusé cette action. Vérifiez les permissions du bot et placez le rôle SentriX "
                "au-dessus du membre ou du rôle concerné."
            ))

        if isinstance(error, commands.CheckFailure):
            return await ctx.send(embed=embeds.error(
                "Vous n’avez pas accès à cette commande. Elle est réservée au staff ou nécessite une permission "
                "qui n’est pas présente sur votre rôle."
            ))

        logger.error(f"Erreur non gérée dans la commande {ctx.command} :\n{traceback.format_exc()}")
        if ctx.author.id == PRIMARY_CREATOR_ID:
            detail = str(error).strip() or "aucun détail"
            return await ctx.send(
                embed=embeds.error(
                    f"Erreur technique : {type(error).__name__}\n{detail[:700]}"
                )
            )
        reference = str(getattr(getattr(ctx, "message", None), "id", "indisponible"))
        await ctx.send(embed=embeds.error(
            "Une erreur technique inattendue a interrompu la commande. Aucun changement supplémentaire "
            f"n’a été appliqué. Référence : `{reference}`."
        ))

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        """Affiche les erreurs slash au membre au lieu du vague « interaction échouée »."""
        original = getattr(error, "original", error)

        if isinstance(original, BotPermissionError):
            embed = embeds.error(original.message)
        elif isinstance(original, BotBlacklistedError):
            embed = embeds.error(f"Vous n’êtes pas autorisé à utiliser ce bot.\nRaison : {original.reason}")
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            embed = embeds.warning(
                f"Cette commande est temporairement en recharge. Vous pourrez la réutiliser dans "
                f"**{cooldown_text(error.retry_after)}**."
            )
        elif isinstance(error, discord.app_commands.MissingPermissions):
            embed = embeds.error(
                "Votre rôle ne possède pas les autorisations nécessaires.\n"
                f"Permission(s) requise(s) : **{format_permissions(error.missing_permissions)}**."
            )
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            embed = embeds.error(
                "Le bot ne peut pas terminer cette action. Permission(s) manquante(s) : "
                f"**{format_permissions(error.missing_permissions)}**."
            )
        elif isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
            embed = embeds.error(
                "Une valeur fournie n’est pas valide pour cette commande. Vérifiez les membres, rôles, salons "
                "et nombres sélectionnés, puis réessayez."
            )
        elif isinstance(original, discord.Forbidden):
            embed = embeds.error(
                "Discord a refusé cette action. Vérifiez les permissions et la position du rôle SentriX."
            )
        elif isinstance(error, discord.app_commands.CheckFailure):
            embed = embeds.error(
                "Vous n’avez pas accès à cette commande. Elle est réservée au staff ou nécessite une permission "
                "supplémentaire."
            )
        else:
            command_name = interaction.command.qualified_name if interaction.command else "inconnue"
            logger.error(
                "Erreur non gérée dans la commande slash %s :\n%s",
                command_name,
                "".join(traceback.format_exception(type(error), error, error.__traceback__)),
            )
            if interaction.user.id == PRIMARY_CREATOR_ID:
                detail = str(original).strip() or "aucun détail"
                embed = embeds.error(f"Erreur technique : {type(original).__name__}\n{detail[:700]}")
            else:
                embed = embeds.error(
                    "Une erreur technique inattendue a interrompu la commande. Aucun changement supplémentaire "
                    f"n’a été appliqué. Référence : `{interaction.id}`."
                )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            logger.warning("Impossible d’envoyer la réponse d’erreur de l’interaction %s.", interaction.id)


async def main():
    bot = BotAllInOne()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Arrêt du bot.")
