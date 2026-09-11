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
from utils import access_matrix
from utils import log_hygiene
from web.dashboard import start_dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
# Compresse les journaux répétitifs SANS jamais toucher aux ERROR/CRITICAL : une
# seule boucle en panne remplissait le journal du même message toutes les 60 s,
# au point de rendre une vraie erreur invisible. Voir utils/log_hygiene.py.
log_hygiene.installer()
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
    "cogs.soundboard_logs",
    "cogs.utility",
    "cogs.guild_arrival",
    "cogs.notifications",
    "cogs.ai",
    "cogs.economy",
    "cogs.levels",
    "cogs.minigames",
    "cogs.games_economy",
    "cogs.music",
    "cogs.events",
    # Rétablit la racine +giveaway que le catalogue annonce depuis toujours. Chargé
    # APRÈS cogs.events, dont il délègue les commandes giveaway-* existantes.
    "cogs.giveaway_center",
    "cogs.verification",
    "cogs.stats",
    # Core V2, Phase 1 (docs/core-v2-plan.md) : écoute passive uniquement, aucun
    # monkeypatch, aucune dépendance à finalize_runtime() — la position dans
    # cette liste n'a pas d'importance particulière pour ce cog.
    "cogs.core_command_observability",
    # Chargé avant cogs.visual_experience_v5 pour que finalize_runtime()
    # (cogs/__init__.py) balaie le @checks.is_bot_owner() local de /corediag,
    # exactement comme pour toute autre commande déjà classée dans
    # utils/access_matrix.py::OWNER_ONLY_COMMANDS.
    "cogs.core_diagnostics",
    # Core V2, Phase 3 (docs/core-v2-plan.md) : /permissions explain, pas de check
    # local (public, restriction "autre membre" gérée dans le corps).
    "cogs.permissions_explain",
    "cogs.owner",
    "cogs.invites",
    "cogs.design",
    "cogs.embed_builder",
    # cogs.visual_experience_v5 declenche finalize_runtime() et doit rester
    # DERNIERE : une extension chargee apres elle echappe a toute la pile de
    # style. C'est ce qui laissait +dmall en dehors du systeme visuel.
    "sentrix_broadcast_dmall_visual",
    "cogs.visual_experience_v5",
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
    "help", "ping", "avatar", "info", "userinfo", "status", "about", "profile-card",
    # +serverinfo est le pont installe par premium_ui_v81 vers « info serveur »,
    # +leaderboard celui vers leaderboard-levels : deux racines en lecture seule
    # dont les cibles sont deja publiques, mais qui n'avaient jamais ete classees.
    "serverinfo",
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
    "stats", "me", "level", "rank", "leaderboard", "leaderboard-levels", "level-roles",
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
    # Musique — "music" est la racine du groupe (join/leave/play/pause/resume/
    # skip/previous/stop/queue/nowplaying/volume/loop/shuffle/remove/clear/
    # seek/autoplay en heritent tous comme sous-commandes publiques, exactement
    # comme "ai" plus haut). "play" reste aussi une commande racine autonome
    # (+play / /play), alias direct de "music play".
    "music", "play",
    # Core V2, Phase 3 (docs/core-v2-plan.md) : /permissions explain montre
    # toujours SA PROPRE décision — pas de fuite d'information. Diagnostiquer un
    # autre membre est restreint aux administrateurs dans le corps de la commande.
    "permissions",
})

OWNER_ONLY_COMMANDS = frozenset({
    "bl", "blinfo", "unbl", "editbl", "sync", "syncguild", "setstatus",
    "status-rotate", "footer", "theme", "set-bot", "bot-servers", "bot-leave",
    # Core V2, Phase 1 (docs/core-v2-plan.md) : panneau d'observabilité globale
    # au processus, jamais scopé par serveur — pas adapté à un accès admin.
    "corediag",
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
        "removebonusinvites", "invitebonushistory", "designsetup", "design-theme", "iconsetup",
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
        "unblacklist-user", "blacklist-users", "panic", "whitelist-domain",
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
    "nick": "manage_nicknames",
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
            kwargs.pop("reference", None)
            kwargs.pop("mention_author", None)
            return await super().send(*args, **kwargs)


async def get_prefix(bot: "BotAllInOne", message: discord.Message):
    default = config.DEFAULT_PREFIX
    if message.guild is None:
        return commands.when_mentioned_or(default)(bot, message)

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
        self.tree.on_error = self.on_app_command_error
        self._cooldown_bucket = commands.CooldownMapping.from_cooldown(
            config.GLOBAL_COOLDOWN_RATE, config.GLOBAL_COOLDOWN_PER, commands.BucketType.user
        )
        self.prefix_cache: dict[int, str] = {}
        self.blacklist_cache: dict[int, str] = {}

    def _prune_redundant_commands(self) -> list[str]:
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

        from cogs.slash_command_budget import install as _install_slash_command_budget

        _install_slash_command_budget(self)

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.info(f"Module chargé : {ext}")
            except Exception:
                logger.error(f"Échec du chargement du module {ext} :\n{traceback.format_exc()}")

        self._prune_redundant_commands()
        self._audit_command_permissions()

        try:
            from cogs.tickets import TicketControlView
            self.add_view(TicketControlView())
            tickets_cog = self.get_cog("Tickets")
            if tickets_cog:
                panels_restored = await tickets_cog.restore_panel_views()
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

        try:
            from cogs.configuration import SetupNavButton
            self.add_dynamic_items(SetupNavButton)
        except Exception:
            logger.warning("Impossible d'enregistrer les boutons de /setup :\n" + traceback.format_exc())

        # Étoiles de notation envoyées en DM après la fermeture d'un ticket (RatingView) :
        # même mécanisme que SetupNavButton, custom_id encodant la note ET l'ID du ticket.
        try:
            from cogs.tickets import TicketRatingButton
            self.add_dynamic_items(TicketRatingButton)
        except Exception:
            logger.warning("Impossible d'enregistrer les boutons de notation tickets :\n" + traceback.format_exc())

        # Boutons "Copier l'ID" des logs (utils/log_service.py::RevealIdButton) : même
        # mécanisme, custom_id encodant l'ID à réafficher.
        try:
            from utils.log_service import RevealIdButton
            self.add_dynamic_items(RevealIdButton)
        except Exception:
            logger.warning("Impossible d'enregistrer les boutons de logs :\n" + traceback.format_exc())

        self.add_check(self.global_blacklist_check)
        self.add_check(self.global_cooldown_check)
        # cogs/permission_guard.py::install() s'enregistre désormais lui-même dès
        # qu'il réaffecte self.global_permission_check (docs/core-v2-audit-
        # technical-debt.md, §6) — ne l'ajouter ici qu'en repli, si cette extension
        # n'a jamais chargé, pour ne jamais laisser aucune commande préfixée sans
        # aucun garde de permission.
        if not getattr(self.global_permission_check, "_sentrix_permission_guard", False):
            self.add_check(self.global_permission_check)


        # Corrige la cause structurelle commune : quand un wrapper remplace
        # command.callback après la construction d'une HybridCommand, discord.py garde
        # une ancienne référence dans app_command._callback. On réaligne tout juste
        # avant le sync global afin que / et + exécutent exactement le même callback.
        try:
            from cogs.hybrid_callback_resync import resync as _resync_hybrid_callbacks

            _resync_hybrid_callbacks(self)
        except Exception:
            logger.warning(
                "Resynchronisation callback slash/préfixe impossible :\n" + traceback.format_exc()
            )

        # Core V2, Phase 3 (docs/core-v2-plan.md) : deuxième passage du nettoyeur de
        # décorateurs d'autorisation redondants, APRÈS que les 48 extensions (main.py
        # + railway_boot.py) soient toutes chargées. Le premier passage
        # (cogs/permission_guard.py::install(), déclenché par finalize_runtime() au
        # chargement de cogs.visual_experience_v5) ne voit que les commandes déjà
        # enregistrées à CE moment-là — toute extension ajoutée après par
        # railway_boot.py (cogs.sentrix_plus, cogs.sentrix_ultimate, etc.) n'était
        # donc jamais balayée. C'est la cause racine confirmée d'un vrai bug
        # (docs/core-v2-audit-technical-debt.md §1) : un décorateur local
        # @has_guild_permissions oublié sur /sentrixpro empêchait un rôle
        # explicitement autorisé via Setup d'accéder à la commande, malgré la
        # décision correcte d'utils/access_matrix.py. La fonction est idempotente
        # (ne retire que ce qui reste réellement présent) : ce second appel ne
        # change rien pour tout ce que le premier passage a déjà nettoyé.
        try:
            from cogs.permission_guard import _strip_redundant_local_checks

            removed_late = _strip_redundant_local_checks(self)
            if removed_late:
                logger.warning(
                    "Second balayage des décorateurs redondants (post-boot complet) : "
                    "%s check(s) retiré(s) sur des extensions chargées tardivement.",
                    removed_late,
                )
        except Exception:
            logger.warning(
                "Second balayage des décorateurs redondants impossible :\n" + traceback.format_exc()
            )

        # docs/core-v2-audit-technical-debt.md §5 : le second passage ci-dessus ne
        # couvre que permission_guard. cogs/command_hardening_v41.py::_audit_registry
        # (détection "dangerous_public" / "unknown_policy", consommée par
        # web/health_runtime_v45.py pour le diagnostic santé) n'a, elle, jamais reçu
        # de second passage : elle ne tournait qu'une fois, via finalize_runtime() au
        # chargement de cogs.visual_experience_v5, donc AVANT les 21 extensions
        # tardives de railway_boot.py — exactement le même trou temporel qui causait
        # le Bug #1 (§1) sur /sentrixpro. Un futur bug de même forme (une commande
        # destructive déclarée publique) dans l'une de ces 21 extensions restait donc
        # invisible à ce diagnostic. _audit_registry ne fait que recalculer et
        # journaliser un rapport (aucune mutation de commande) : un second appel est
        # sans risque et ne fait que rafraîchir bot._sentrix_command_audit avec la
        # liste complète des 51 extensions.
        try:
            from cogs.command_hardening_v41 import _audit_registry as _audit_command_registry_v41

            _audit_command_registry_v41(self)
        except Exception:
            logger.warning(
                "Second audit du registre de commandes (V41, post-boot complet) impossible :\n"
                + traceback.format_exc()
            )

        try:
            from cogs.permission_guard import apply_slash_default_permissions

            poses = apply_slash_default_permissions(self)
            if poses:
                logger.info(
                    "Affichage slash complete avant synchronisation : %s commande(s).",
                    poses,
                )
        except Exception:
            logger.warning(
                "Alignement final de l'affichage slash impossible :\n" + traceback.format_exc()
            )

        try:
            synced = await self.tree.sync()
            logger.info(f"{len(synced)} commandes slash synchronisées globalement.")
        except Exception:
            logger.error(f"Échec de la synchronisation des commandes slash :\n{traceback.format_exc()}")

        asyncio.create_task(start_dashboard(self))

    def _audit_command_permissions(self) -> None:
        registered = {command.name.lower() for command in self.commands}
        unknown = sorted(registered - access_matrix.KNOWN_COMMANDS)
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
        command = ctx.command
        if command is None:
            return True
        root = command.root_parent or command
        decision = await access_matrix.evaluate(
            self,
            command_name=root.name,
            author=ctx.author,
            guild=ctx.guild,
        )
        if decision.allowed:
            return True
        raise BotPermissionError(decision.message)

    async def _is_extra_bot_creator(self, user_id: int) -> bool:
        try:
            return await self.db.is_bot_creator(user_id)
        except Exception:
            logger.exception("is_bot_creator indisponible pour user=%s ; traité comme non-créateur.", user_id)
            return False

    async def global_blacklist_check(self, ctx: commands.Context) -> bool:
        if ctx.author.id == PRIMARY_CREATOR_ID or ctx.author.id in config.OWNER_IDS:
            return True
        if await self._is_extra_bot_creator(ctx.author.id):
            return True
        reason = self.blacklist_cache.get(ctx.author.id)
        if reason is not None:
            raise BotBlacklistedError(reason)
        return True

    async def global_cooldown_check(self, ctx: commands.Context) -> bool:
        if ctx.author.id == PRIMARY_CREATOR_ID or ctx.author.id in config.OWNER_IDS:
            return True
        if await self._is_extra_bot_creator(ctx.author.id):
            return True
        bucket = self._cooldown_bucket.get_bucket(ctx.message if not ctx.interaction else ctx)
        if bucket is None:
            return True
        retry_after = bucket.update_rate_limit()
        if retry_after:
            raise commands.CommandOnCooldown(bucket, retry_after, commands.BucketType.user)
        return True

    async def get_context(self, message, *, cls=SentriXContext):
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
        embeds.set_footer_icon(self.user.display_avatar.url)

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

    async def on_command_completion(self, ctx: commands.Context):
        if ctx.guild:
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
