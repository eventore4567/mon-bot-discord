"""
Cog CONFIGURATION.
/setup (assistant complet en un clic) /setprefix /setmodrole /setlogchannel /create-logs
/logs-status /setwelcomechannel /setgoodbyechannel /setwelcomemessage /setgoodbyemessage
/setticketlogchannel /setautorole /disablecommand /enablecommand
/ignorechannel /unignorechannel /config-view /config-reset /setlevelchannel
/setsuggestchannel /setannouncechannel /setgiveawaychannel /setwarnrole /setwarnbanthreshold

Le système de tickets (panels, types, formulaires, boutons staff) se configure entièrement
via +ticketsetup (cogs/tickets.py) — /setticketlogchannel ne reste que comme salon de logs
de repli si un type de ticket n'a pas son propre salon de logs dédié.
"""

import json
import re
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds, checks, helpers
from cogs.automod import AUTOMOD_TOGGLE_LABELS, SECURITY_PRESETS
from database.db import MANAGER_CATEGORIES
# Le système de tickets (panels/types/formulaires) est entièrement géré depuis cogs/tickets.py
# via +ticketsetup — rien à importer ici, /setup se contente d'y rediriger (page 3/9).

ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")

# ---------------------------------------------------------------- PALETTE /setup
# Couleurs dédiées à l'assistant de configuration (distinctes de la couleur de marque
# générale du bot, qui reste inchangée partout ailleurs : /theme, embeds.brand()...).
SETUP_COLOR_MAIN = 0x5865F2
SETUP_COLOR_SECONDARY = 0x7C5CFC
SETUP_COLOR_SUCCESS = 0x23A559
SETUP_COLOR_WARNING = 0xF0B232
SETUP_COLOR_DANGER = 0xF23F43

# (colonne guild_config, nom du salon, description) — utilisé par /create-logs pour
# générer toute la catégorie de logs d'un coup, et par les listeners de logging.py.
LOG_CHANNEL_DEFINITIONS = [
    ("log_server", "logs-serveur", "Création/suppression/modification de salons, catégories et rôles du serveur."),
    ("log_messages", "logs-messages", "Messages modifiés ou supprimés."),
    ("log_members", "logs-membre", "Arrivées et départs de membres."),
    ("log_voice", "logs-vocal", "Connexions, déconnexions et changements de salon vocal."),
    ("log_roles", "logs-roles", "Rôles ajoutés ou retirés à un membre."),
    ("log_moderation", "logs-moderation", "Sanctions : avertissements, mutes, kicks, bans."),
    ("log_automod", "logs-securite", "Actions AutoMod et anti-nuke (spam, liens, protection du serveur)."),
]

# Libellés affichés par /logs-status pour chaque colonne de LOG_CHANNEL_DEFINITIONS.
LOG_KIND_LABELS = {
    "log_server": "Logs serveur",
    "log_messages": "Logs messages",
    "log_members": "Logs membres",
    "log_voice": "Logs vocal",
    "log_roles": "Logs rôles",
    "log_moderation": "Logs modération",
    "log_automod": "Logs sécurité (AutoMod)",
}


def parse_role_input(guild: discord.Guild, value: str):
    """Accepte une mention de rôle (@Role), un ID brut, ou un nom exact."""
    value = value.strip()
    m = ROLE_MENTION_RE.match(value)
    if m:
        return guild.get_role(int(m.group(1)))
    if value.isdigit():
        return guild.get_role(int(value))
    return discord.utils.get(guild.roles, name=value)


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Assistants /setup actuellement ouverts, indexés par ID du message. Permet de
        # retrouver l'instance vivante d'un SetupView quand un bouton est cliqué. Si le
        # bot a redémarré entre-temps (Railway redéploie souvent), l'entrée n'existe plus
        # ici : on reconstruit alors l'assistant depuis la table setup_sessions (voir
        # handle_setup_nav ci-dessous et SetupNavButton, le composant "dynamique" qui
        # survit aux redémarrages).
        self.active_setups: dict[int, "SetupView"] = {}

    @commands.hybrid_command(name="setprefix", description="Changer le préfixe des commandes textuelles.")
    @app_commands.describe(prefixe="Le nouveau préfixe (ex: !, ?, +)")
    @checks.is_owner_or_admin()
    async def setprefix(self, ctx: commands.Context, prefixe: str):
        if len(prefixe) > 5:
            return await ctx.send(embed=embeds.error("Le préfixe doit faire 5 caractères maximum."))
        await self.bot.db.set_guild_config(ctx.guild.id, "prefix", prefixe)
        self.bot.prefix_cache[ctx.guild.id] = prefixe
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

    async def create_log_channels(self, guild: discord.Guild, author: discord.Member) -> list[discord.TextChannel]:
        """Crée (une seule fois) toute la catégorie de logs SentriX : un salon dédié par
        type d'évènement, avec les bonnes permissions. Réutilisé par /create-logs et par
        la page "Logs" de /setup. Ne recrée jamais un salon déjà configuré et toujours valide."""
        conf = await self.bot.db.get_guild_config(guild.id)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if conf and conf["mod_role"]:
            role = guild.get_role(conf["mod_role"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if author.guild_permissions.administrator:
            overwrites[author] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        missing = [d for d in LOG_CHANNEL_DEFINITIONS if not (conf and conf[d[0]] and guild.get_channel(conf[d[0]]))]
        if not missing:
            return []

        category = await guild.create_category("📡 SentriX — Logs", overwrites=overwrites, reason=f"Système de logs créé par {author}")

        created = []
        for db_column, channel_name, topic in missing:
            channel = await guild.create_text_channel(
                channel_name, category=category, overwrites=overwrites, topic=topic,
                reason=f"Système de logs créé par {author}",
            )
            await self.bot.db.set_guild_config(guild.id, db_column, channel.id)
            created.append(channel)
            await channel.send(embed=embeds.brand("📡 Journal SentriX", topic))
        return created

    @commands.hybrid_command(
        name="create-logs",
        description="Créer automatiquement toute une catégorie de salons de logs (messages, membres, vocal, rôles, serveur, modération, sécurité).",
    )
    @checks.is_owner_or_admin()
    async def create_logs(self, ctx: commands.Context):
        await ctx.defer() if ctx.interaction else None
        created = await self.create_log_channels(ctx.guild, ctx.author)

        if not created:
            return await ctx.send(embed=embeds.warning("Tous les salons de logs étaient déjà configurés. Utilisez `/setup` pour les changer un par un."))

        e = embeds.brand(
            "📡 Système de logs créé",
            f"**{len(created)}** salon(s) de logs ont été créés et configurés automatiquement — "
            "rien d'autre à faire, le bot y écrit tout seul à partir de maintenant.",
        )
        e.add_field(name="Salons créés", value="\n".join(c.mention for c in created), inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(
        name="logs-status",
        description="Diagnostiquer le système de logs : quel salon reçoit quoi, et ce qui ne fonctionne pas.",
    )
    @checks.is_owner_or_admin()
    async def logs_status(self, ctx: commands.Context):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        e = embeds.neutral("📡 Diagnostic des logs")
        if not conf:
            e.description = "Aucune configuration définie pour l'instant. Utilisez `/create-logs` ou `/setup`."
            return await ctx.send(embed=e)

        def check_channel(channel_id: int):
            """Retourne (emoji, texte) pour un salon donné : introuvable, permissions
            manquantes, ou OK. C'est exactement la même logique que helpers.send_log,
            pour que ce diagnostic reflète fidèlement ce qui se passe réellement."""
            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                return "❌", "salon introuvable (a probablement été supprimé)"
            perms = channel.permissions_for(ctx.guild.me)
            if not (perms.view_channel and perms.send_messages):
                return "⚠️", f"{channel.mention} — le bot n'a pas la permission de voir/écrire ici"
            return "✅", channel.mention

        general_id = conf["log_channel"]
        lines = []
        any_problem = False

        if general_id:
            status, detail = check_channel(general_id)
            any_problem = any_problem or status != "✅"
            lines.append(f"{status} **Salon général** (`/setlogchannel`) — {detail}")
        else:
            lines.append("⚪ **Salon général** (`/setlogchannel`) — non défini (sert de repli si un salon dédié manque)")

        for column, _slug, _desc in LOG_CHANNEL_DEFINITIONS:
            label = LOG_KIND_LABELS.get(column, column)
            dedicated_id = conf[column]
            if dedicated_id:
                status, detail = check_channel(dedicated_id)
            elif general_id:
                status, detail = check_channel(general_id)
                detail = f"{detail} (via le repli sur le salon général)"
            else:
                status, detail = "❌", "aucun salon configuré (ni dédié, ni général)"
            any_problem = any_problem or status != "✅"
            lines.append(f"{status} **{label}** — {detail}")

        e.description = "\n".join(lines)
        if any_problem:
            e.add_field(
                name="Comment corriger",
                value=(
                    "Lancez `/create-logs` pour créer automatiquement les salons manquants, "
                    "ou `/setup` (page Logs) pour les redéfinir un par un. Si un ❌ ou ⚠️ persiste "
                    "après ça, vérifiez que le rôle du bot a bien la permission **Voir le salon** "
                    "et **Envoyer des messages** dans le salon concerné."
                ),
                inline=False,
            )
        else:
            e.add_field(name="Résultat", value="Tous les logs configurés fonctionnent correctement. ✅", inline=False)
        await ctx.send(embed=e)

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

    @commands.hybrid_command(
        name="setticketlogchannel",
        description="Définir le salon de logs de repli des tickets (utilisé si un type de ticket n'a pas son propre salon de logs).",
        with_app_command=False,
    )
    @app_commands.describe(salon="Le salon de logs de repli pour les tickets")
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

    @commands.hybrid_command(
        name="setwarnrole",
        description="Définir un rôle attribué automatiquement à chaque avertissement (/warn).",
        with_app_command=False,
    )
    @app_commands.describe(role="Le rôle à attribuer à chaque /warn (laisser vide pour désactiver)")
    @checks.is_owner_or_admin()
    async def setwarnrole(self, ctx: commands.Context, role: discord.Role = None):
        await self.bot.db.set_guild_config(ctx.guild.id, "warn_role", role.id if role else None)
        if role:
            await ctx.send(embed=embeds.success(f"Le rôle {role.mention} sera désormais attribué automatiquement à chaque `/warn`."))
        else:
            await ctx.send(embed=embeds.success("Le rôle automatique d'avertissement a été désactivé."))

    @commands.hybrid_command(
        name="setwarnbanthreshold",
        description="Définir le nombre d'avertissements avant bannissement automatique (0 = désactivé).",
        with_app_command=False,
    )
    @app_commands.describe(nombre="Nombre d'avertissements avant bannissement automatique (0 pour désactiver)")
    @checks.is_owner_or_admin()
    async def setwarnbanthreshold(self, ctx: commands.Context, nombre: int):
        if nombre < 0:
            return await ctx.send(embed=embeds.error("Le nombre doit être positif (0 pour désactiver)."))
        await self.bot.db.set_guild_config(ctx.guild.id, "warn_ban_threshold", nombre)
        if nombre == 0:
            await ctx.send(embed=embeds.success("Le bannissement automatique après avertissements a été désactivé."))
        else:
            await ctx.send(embed=embeds.success(f"Un membre sera désormais banni automatiquement au **{nombre}ᵉ** avertissement."))

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
        automod_cog = self.bot.get_cog("Automod")
        if automod_cog:
            automod_cog.ignored_channels_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le salon {salon.mention} est maintenant ignoré (y compris par AutoMod)."))

    @commands.hybrid_command(name="unignorechannel", description="Ne plus ignorer un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon à ne plus ignorer")
    @checks.is_owner_or_admin()
    async def unignorechannel(self, ctx: commands.Context, salon: discord.TextChannel = None):
        salon = salon or ctx.channel
        await self.bot.db.execute(
            "DELETE FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
            (ctx.guild.id, salon.id),
        )
        automod_cog = self.bot.get_cog("Automod")
        if automod_cog:
            automod_cog.ignored_channels_cache.pop(ctx.guild.id, None)
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
        e.add_field(name="Logs tickets (repli)", value=fmt_channel(conf["ticket_log_channel"]), inline=True)
        e.add_field(name="Rôle d'avertissement", value=fmt_role(conf["warn_role"]), inline=True)
        e.add_field(
            name="Ban auto après N warns",
            value=f"{conf['warn_ban_threshold']} avertissement(s)" if conf["warn_ban_threshold"] else "Désactivé",
            inline=True,
        )

        managers = await self.bot.db.list_bot_managers(ctx.guild.id)
        if managers:
            mentions = []
            for row in managers:
                member = ctx.guild.get_member(row["user_id"])
                mentions.append(member.mention if member else f"<@{row['user_id']}>")
            e.add_field(name="Gestionnaires du bot", value=", ".join(mentions), inline=False)
        else:
            e.add_field(name="Gestionnaires du bot", value="Aucun (seuls les administrateurs peuvent configurer le bot).", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="config-reset", description="Réinitialiser toute la configuration du serveur.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def config_reset(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM guild_config WHERE guild_id = ?", (ctx.guild.id,))
        await self.bot.db.ensure_guild(ctx.guild.id)
        self.bot.db.invalidate_guild_config(ctx.guild.id)
        self.bot.prefix_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success("La configuration du serveur a été réinitialisée."))

    @commands.hybrid_command(
        name="setup",
        description="Assistant de configuration complet du bot (tous les réglages, en plusieurs pages).",
    )
    @checks.is_owner_or_admin()
    async def setup_wizard(self, ctx: commands.Context):
        """
        Fonctionnalité phare : configure absolument tout le bot (rôles, salons,
        préfixe, messages de bienvenue/départ...) via des menus déroulants et
        un formulaire, sans jamais avoir à taper une commande. Découpé en 9 pages
        pour rester lisible (Discord limite un message à 5 lignes de composants).
        """
        rows = await self.bot.db.list_bot_managers(ctx.guild.id)
        existing_managers = {}
        for row in rows:
            member = ctx.guild.get_member(row["user_id"])
            existing_managers[row["user_id"]] = member.display_name if member else f"Membre {row['user_id']}"

        automod_conf = await self.bot.db.get_automod(ctx.guild.id)
        existing_security = {field: (automod_conf[field] if automod_conf else 0) for field in AUTOMOD_TOGGLE_LABELS}
        exempt_rows = await self.bot.db.list_automod_exempt_roles(ctx.guild.id)
        existing_exempt = [r["role_id"] for r in exempt_rows]

        # Envoi en deux temps : on a besoin de l'ID du message AVANT de construire les
        # boutons de navigation (ils encodent cet ID dans leur custom_id pour pouvoir
        # être retrouvés après un redémarrage — voir SetupNavButton plus bas).
        placeholder = embeds.neutral("🛠️ Configuration SentriX", "Chargement de l'assistant...", color=SETUP_COLOR_MAIN)
        message = await ctx.send(embed=placeholder)

        view = SetupView(
            self.bot, ctx.guild.id, ctx.author.id, message.id, ctx.channel.id,
            existing_managers=existing_managers, existing_security=existing_security,
            existing_exempt_roles=existing_exempt,
        )
        self.active_setups[message.id] = view
        await view.persist_session()
        await message.edit(embed=await view.build_embed(), view=view)

    async def _can_use_setup(self, interaction: discord.Interaction, author_id: int, guild_id: int) -> bool:
        """Autorise la personne qui a lancé /setup, OU un gestionnaire du bot / admin /
        propriétaire du bot — exactement la règle demandée pour la nouvelle version de
        l'assistant. Envoie le message d'erreur exact demandé si refusé."""
        if interaction.user.id == author_id:
            return True
        if interaction.user.id in config.OWNER_IDS:
            return True
        member = interaction.user
        if isinstance(member, discord.Member) and member.guild_permissions.administrator:
            return True
        if await self.bot.db.is_bot_manager(guild_id, interaction.user.id):
            return True
        await interaction.response.send_message("❌ Vous n'êtes pas autorisé à utiliser cette configuration.", ephemeral=True)
        return False

    async def handle_setup_nav(self, interaction: discord.Interaction, action: str, message_id: int):
        """Point d'entrée UNIQUE des boutons de navigation du /setup (◀ 💾 ▶ 👁️ ❌ et les
        boutons équivalents de la page 9). Fonctionne que le bot ait redémarré entre-temps
        ou non : si l'assistant n'est plus en mémoire, on le reconstruit depuis la table
        setup_sessions (c'est ce qui permet aux boutons de survivre à un redémarrage)."""
        view = self.active_setups.get(message_id)
        if view is None:
            session = await self.bot.db.get_setup_session(message_id)
            if not session or session["guild_id"] != interaction.guild.id:
                return await interaction.response.send_message(
                    "❌ Cette session de configuration a expiré ou est introuvable. Relancez `/setup`.", ephemeral=True
                )
            if not await self._can_use_setup(interaction, session["author_id"], session["guild_id"]):
                return
            rows = await self.bot.db.list_bot_managers(session["guild_id"])
            existing_managers = {}
            for row in rows:
                member = interaction.guild.get_member(row["user_id"])
                existing_managers[row["user_id"]] = member.display_name if member else f"Membre {row['user_id']}"
            automod_conf = await self.bot.db.get_automod(session["guild_id"])
            existing_security = {field: (automod_conf[field] if automod_conf else 0) for field in AUTOMOD_TOGGLE_LABELS}
            exempt_rows = await self.bot.db.list_automod_exempt_roles(session["guild_id"])
            existing_exempt = [r["role_id"] for r in exempt_rows]
            view = SetupView(
                self.bot, session["guild_id"], session["author_id"], message_id, session["channel_id"],
                existing_managers=existing_managers, existing_security=existing_security,
                existing_exempt_roles=existing_exempt,
            )
            try:
                view.choices = json.loads(session["choices_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                view.choices = {}
            view.page = max(0, min(len(SETUP_STEPS) - 1, session["page"] or 0))
            view.render_page()
            self.active_setups[message_id] = view
        else:
            if not await self._can_use_setup(interaction, view.author_id, view.guild_id):
                return

        await view.handle_nav_action(interaction, action)

    # ---------------------------------------------------------------- LOGS AUTOMATIQUES
    # Une fois /create-logs (ou la page "Logs" de /setup) utilisé, le bot alimente ces
    # salons tout seul, sans plus jamais rien demander à l'utilisateur.

    async def _get_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None):
        """Retrouve l'auteur d'une action via l'Audit Log (réutilise le helper du cog Automod).
        Réservé aux événements peu fréquents (salons/rôles/kicks) — jamais utilisé sur les
        messages, trop nombreux, pour ne pas multiplier les appels à l'API."""
        automod_cog = self.bot.get_cog("Automod")
        if not automod_cog:
            return None
        return await automod_cog.get_audit_actor(guild, action, target_id)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        e = embeds.log_entry(
            "🗑️ Message supprimé",
            config.COLOR_ERROR,
            cible=message.author,
            cible_label="👤 Auteur",
            extra={
                "📍 Salon": f"{message.channel.mention}\n`ID: {message.channel.id}`",
                "💬 Contenu": message.content[:1000] or "*(vide)*",
                "🔗 ID du message": f"`{message.id}`",
            },
        )
        await helpers.send_log(self.bot, message.guild, "messages", e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        e = embeds.log_entry(
            "✏️ Message modifié",
            config.COLOR_INFO,
            cible=before.author,
            cible_label="👤 Auteur",
            extra={
                "📍 Salon": f"{before.channel.mention}\n`ID: {before.channel.id}`",
                "⬅️ Avant": before.content[:500] or "*(vide)*",
                "➡️ Après": after.content[:500] or "*(vide)*",
                "🔗 ID du message": f"`{before.id}`",
            },
        )
        await helpers.send_log(self.bot, before.guild, "messages", e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        age_days = (discord.utils.utcnow() - member.created_at).days
        warning_note = " ⚠️ **Compte très récent**" if age_days < 7 else ""
        e = embeds.log_entry(
            "📥 Arrivée d'un membre",
            config.COLOR_SUCCESS,
            cible=member,
            cible_label="👤 Membre",
            extra={
                "📅 Compte créé": f"<t:{int(member.created_at.timestamp())}:D> (il y a {age_days} jour(s)){warning_note}",
                "📊 Membres du serveur": str(member.guild.member_count),
            },
        )
        await helpers.send_log(self.bot, member.guild, "members", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        roles = [r.mention for r in member.roles if not r.is_default()]
        actor = await self._get_actor(member.guild, discord.AuditLogAction.kick, member.id)
        e = embeds.log_entry(
            "📤 Départ d'un membre" if not actor else "👢 Membre expulsé",
            config.COLOR_ERROR,
            cible=member,
            cible_label="👤 Membre",
            acteur=actor,
            acteur_label="🛠️ Expulsé par",
            extra={"🎭 Rôles qu'il avait": ", ".join(roles) if roles else "Aucun"},
        )
        await helpers.send_log(self.bot, member.guild, "members", e)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        if before.channel == after.channel:
            return  # simple mute/deafen/stream toggle : pas assez pertinent pour un log
        if before.channel is None:
            title, extra = "🔊 Connexion vocale", {"📍 Salon": f"{after.channel.mention}\n`ID: {after.channel.id}`"}
        elif after.channel is None:
            title, extra = "🔇 Déconnexion vocale", {"📍 Salon": f"{before.channel.mention}\n`ID: {before.channel.id}`"}
        else:
            title = "🔀 Changement de salon vocal"
            extra = {
                "⬅️ Depuis": f"{before.channel.mention}\n`ID: {before.channel.id}`",
                "➡️ Vers": f"{after.channel.mention}\n`ID: {after.channel.id}`",
            }
        e = embeds.log_entry(title, config.COLOR_NEUTRAL, cible=member, cible_label="👤 Membre", extra=extra)
        await helpers.send_log(self.bot, member.guild, "voice", e)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        actor = await self._get_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        e = embeds.log_entry(
            "📁 Salon créé",
            config.COLOR_SUCCESS,
            cible=channel,
            cible_label="📍 Salon",
            acteur=actor,
            acteur_label="🛠️ Créé par",
            extra={"🗂️ Catégorie": channel.category.name if getattr(channel, "category", None) else "Aucune", "🏷️ Type": str(channel.type).replace("_", " ").capitalize()},
        )
        await helpers.send_log(self.bot, channel.guild, "server", e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        actor = await self._get_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        e = embeds.log_entry(
            "📁 Salon supprimé",
            config.COLOR_ERROR,
            acteur=actor,
            acteur_label="🛠️ Supprimé par",
            extra={"📍 Nom du salon": f"#{channel.name}", "🔗 ID": f"`{channel.id}`", "🏷️ Type": str(channel.type).replace("_", " ").capitalize()},
        )
        await helpers.send_log(self.bot, channel.guild, "server", e)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        actor = await self._get_actor(role.guild, discord.AuditLogAction.role_create, role.id)
        e = embeds.log_entry(
            "🎭 Rôle créé",
            config.COLOR_SUCCESS,
            cible=role,
            cible_label="🎭 Rôle",
            acteur=actor,
            acteur_label="🛠️ Créé par",
            extra={"🎨 Couleur": str(role.color)},
        )
        await helpers.send_log(self.bot, role.guild, "roles", e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        actor = await self._get_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        e = embeds.log_entry(
            "🎭 Rôle supprimé",
            config.COLOR_ERROR,
            acteur=actor,
            acteur_label="🛠️ Supprimé par",
            extra={"🎭 Nom du rôle": role.name, "🔗 ID": f"`{role.id}`"},
        )
        await helpers.send_log(self.bot, role.guild, "roles", e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        extra = {}
        if added:
            extra["✅ Rôles ajoutés"] = ", ".join(r.mention for r in added)
        if removed:
            extra["❌ Rôles retirés"] = ", ".join(r.mention for r in removed)
        if not extra:
            return
        actor = await self._get_actor(after.guild, discord.AuditLogAction.member_role_update, after.id)
        e = embeds.log_entry(
            "🎭 Rôles modifiés",
            config.COLOR_NEUTRAL,
            cible=after,
            cible_label="👤 Membre",
            acteur=actor,
            acteur_label="🛠️ Modifié par",
            extra=extra,
        )
        await helpers.send_log(self.bot, after.guild, "roles", e)


# Chaque "étape" = une page de l'assistant. "role"/"channel" = type de menu déroulant.
# Pour "channel", on peut préciser les types de salons acceptés (texte, catégorie...).
SETUP_STEPS = [
    {"key": "general", "icon": "⚙️", "title": "Général", "fields": [
        ("mod_role", "role", "🛡️ Rôle staff (modération)"),
        ("log_channel", "channel", "📝 Salon de logs (sanctions)"),
        ("welcome_channel", "channel", "👋 Salon de bienvenue"),
        ("goodbye_channel", "channel", "🚪 Salon de départ"),
    ]},
    {"key": "roles", "icon": "🎭", "title": "Rôles", "fields": [], "custom": "picker"},
    {"key": "tickets", "icon": "🎫", "title": "Tickets", "fields": [], "custom": "tickets"},
    {"key": "channels", "icon": "📢", "title": "Salons annexes", "fields": [], "custom": "picker"},
    {"key": "levels", "icon": "🏆", "title": "Rôles de niveau", "fields": [], "custom": "level_roles"},
    {"key": "logs", "icon": "📡", "title": "Système de logs", "fields": [], "custom": "logs_setup"},
    {"key": "managers", "icon": "👥", "title": "Gestionnaires du bot", "fields": [], "custom": "managers"},
    {"key": "security", "icon": "🛡️", "title": "Sécurité (AutoMod)", "fields": [], "custom": "security"},
    {"key": "summary", "icon": "✅", "title": "Résumé et confirmation", "fields": [], "custom": "summary"},
]

# Pages "Rôles" et "Salons annexes" (Phase 2) : trop de champs pour tenir en menus
# déroulants directs sur une seule page (Discord limite un message à 5 lignes de
# composants, et il faut garder de la place pour la navigation). On affiche donc un
# premier menu "quel réglage voulez-vous changer ?", puis un second menu (rôle ou salon)
# apparaît juste en dessous une fois le premier choisi. Voir SetupView._render_picker().
PICKER_FIELDS = {
    "roles": [
        ("autorole", "role", "🎭 Rôle automatique à l'arrivée"),
        ("verify_role", "role", "✅ Rôle donné après vérification"),
        ("member_role", "role", "👤 Rôle membre"),
        ("booster_role", "role", "🚀 Rôle booster"),
        ("mute_role", "role", "🔇 Rôle mute / quarantaine"),
    ],
    "channels": [
        ("level_channel", "channel", "📈 Annonces de passage de niveau"),
        ("suggest_channel", "channel", "💡 Suggestions"),
        ("announce_channel", "channel", "📢 Annonces générales"),
        ("giveaway_channel", "channel", "🎉 Giveaways par défaut"),
        ("bot_commands_channel", "channel", "🤖 Commandes du bot"),
        ("report_channel", "channel", "🚨 Rapports"),
        ("partner_channel", "channel", "🤝 Partenariats"),
        ("stats_channel", "channel", "📊 Statistiques"),
        ("afk_channel", "channel", "💤 Salon AFK"),
        ("error_channel", "channel", "🐛 Erreurs du bot"),
    ],
}

FIELD_LABELS = {
    "mod_role": "🛡️ Rôle staff", "log_channel": "📝 Salon de logs", "welcome_channel": "👋 Salon de bienvenue",
    "goodbye_channel": "🚪 Salon de départ", "autorole": "🎭 Rôle automatique", "verify_role": "✅ Rôle de vérification",
    "member_role": "👤 Rôle membre", "booster_role": "🚀 Rôle booster", "mute_role": "🔇 Rôle mute/quarantaine",
    "level_channel": "📈 Annonces de niveau", "suggest_channel": "💡 Suggestions",
    "announce_channel": "📢 Annonces", "giveaway_channel": "🎉 Giveaways",
    "bot_commands_channel": "🤖 Commandes du bot", "report_channel": "🚨 Rapports",
    "partner_channel": "🤝 Partenariats", "stats_channel": "📊 Statistiques",
    "afk_channel": "💤 Salon AFK", "error_channel": "🐛 Erreurs du bot",
    "prefix": "⌨️ Préfixe", "welcome_message": "👋 Message de bienvenue", "goodbye_message": "🚪 Message de départ",
}

ROLE_FIELDS = {"mod_role", "autorole", "verify_role", "member_role", "booster_role", "mute_role"}


def _progress_bar(page: int, total: int, length: int = 9) -> str:
    """Barre ▓▓░░░░░░░ NN % — une case par page, comme demandé."""
    filled = round((page + 1) / total * length)
    filled = max(1, min(length, filled))
    percent = round((page + 1) / total * 100)
    return f"{'▓' * filled}{'░' * (length - filled)}  **{percent}%**"


class SetupTextModal(discord.ui.Modal, title="Préfixe & messages"):
    """Formulaire pour les réglages texte (pas possible avec des menus déroulants)."""

    prefixe = discord.ui.TextInput(label="Préfixe des commandes (ex: +)", required=False, max_length=5)
    bienvenue = discord.ui.TextInput(
        label="Message de bienvenue ({member}, {server})", required=False,
        style=discord.TextStyle.paragraph, max_length=300,
    )
    depart = discord.ui.TextInput(
        label="Message de départ ({member}, {server})", required=False,
        style=discord.TextStyle.paragraph, max_length=300,
    )

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if self.prefixe.value:
            self.view_ref.choices["prefix"] = self.prefixe.value
        if self.bienvenue.value:
            self.view_ref.choices["welcome_message"] = self.bienvenue.value
        if self.depart.value:
            self.view_ref.choices["goodbye_message"] = self.depart.value
        self.view_ref.dirty = True
        await self.view_ref.persist_session()
        await interaction.response.edit_message(embed=await self.view_ref.build_embed(), view=self.view_ref)


class LevelRoleModal(discord.ui.Modal, title="Ajouter un rôle de niveau"):
    """Formulaire pour associer un rôle récompense à un niveau atteint."""

    niveau = discord.ui.TextInput(label="Niveau requis (ex: 5)", required=True, max_length=5)
    role = discord.ui.TextInput(
        label="Rôle (mentionnez-le avec @, ou collez son ID/nom)", required=True, max_length=100
    )

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(self.niveau.value.strip())
        except ValueError:
            return await interaction.response.send_message("Niveau invalide : entrez un nombre entier.", ephemeral=True)
        role = parse_role_input(interaction.guild, self.role.value)
        if not role:
            return await interaction.response.send_message("Rôle introuvable. Essayez de le mentionner avec @.", ephemeral=True)

        existing = await self.view_ref.bot.db.fetchone(
            "SELECT * FROM level_roles WHERE guild_id = ? AND level = ?", (self.view_ref.guild_id, level)
        )
        if existing and existing["role_id"] != role.id:
            old_role = interaction.guild.get_role(existing["role_id"])
            confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
            await interaction.response.send_message(
                embed=embeds.warning(
                    f"Le niveau **{level}** est déjà associé à {old_role.mention if old_role else 'un rôle supprimé'}. "
                    f"Voulez-vous le remplacer par {role.mention} ?"
                ),
                view=confirm, ephemeral=True,
            )
            await confirm.wait()
            if not confirm.value:
                return

        await self.view_ref.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (self.view_ref.guild_id, level, role.id),
        )
        self.view_ref.level_role_additions.append((level, role))
        await self.view_ref.persist_session()
        # _refresh_message gère le cas où la boîte de confirmation ci-dessus a déjà
        # utilisé la réponse de cette interaction (elle irait alors éditer le message
        # éphémère de confirmation par erreur, au lieu du vrai message de l'assistant).
        await self.view_ref._refresh_message(interaction)


class DeleteLevelRoleModal(discord.ui.Modal, title="Supprimer un palier de niveau"):
    """Formulaire minimal pour retirer un palier existant (page Rôles de niveau)."""

    niveau = discord.ui.TextInput(label="Niveau à supprimer (ex: 5)", required=True, max_length=5)

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(self.niveau.value.strip())
        except ValueError:
            return await interaction.response.send_message("Niveau invalide : entrez un nombre entier.", ephemeral=True)
        existing = await self.view_ref.bot.db.fetchone(
            "SELECT * FROM level_roles WHERE guild_id = ? AND level = ?", (self.view_ref.guild_id, level)
        )
        if not existing:
            return await interaction.response.send_message(f"Aucun palier trouvé au niveau **{level}**.", ephemeral=True)
        await self.view_ref.bot.db.execute(
            "DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (self.view_ref.guild_id, level)
        )
        await interaction.response.edit_message(embed=await self.view_ref.build_embed(), view=self.view_ref)


class SetupNavButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"setup:(?P<action>prev|save|next|preview|cancel|summary|finish|restart):(?P<message_id>[0-9]+)",
):
    """Bouton de navigation du /setup. Son custom_id encode l'action ET l'ID du message,
    ce qui permet à Discord de le retrouver et de le faire fonctionner même si le bot a
    redémarré entre-temps (voir Configuration.handle_setup_nav, qui reconstruit alors
    l'assistant depuis la table setup_sessions). C'est ce qui rend le /setup persistant."""

    def __init__(self, action: str, message_id: int, *, label: str, style: discord.ButtonStyle, disabled: bool = False, row: int = 4):
        super().__init__(
            discord.ui.Button(label=label, style=style, disabled=disabled, row=row, custom_id=f"setup:{action}:{message_id}")
        )
        self.action = action
        self.message_id = message_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match, /):
        return cls(match["action"], int(match["message_id"]), label=item.label or "…", style=item.style, disabled=item.disabled)

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Configuration")
        if cog is None:
            return await interaction.response.send_message("❌ Le module de configuration n'est pas chargé.", ephemeral=True)
        await cog.handle_setup_nav(interaction, self.action, self.message_id)


class SetupView(discord.ui.View):
    """
    Assistant /setup complet, en 9 pages. Les réglages "simples" (rôles/salons choisis
    par menu déroulant) restent en attente dans self.choices jusqu'à un clic sur
    💾 Enregistrer (ou la page 9) ; les actions plus lourdes (rôles de niveau, logs,
    gestionnaires, sécurité) restent enregistrées immédiatement comme avant, car elles
    créent ou modifient des choses côté Discord (salons, rôles) qu'on ne veut pas
    "annuler" facilement une fois faites.
    """

    def __init__(
        self, bot: commands.Bot, guild_id: int, author_id: int, message_id: int, channel_id: int,
        existing_managers: dict | None = None, existing_security: dict | None = None,
        existing_exempt_roles: list[int] | None = None,
    ):
        super().__init__(timeout=None)  # timeout=None : géré manuellement, survit aux redémarrages
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.message_id = message_id
        self.channel_id = channel_id
        self.choices: dict = {}
        self.dirty = False
        self.level_role_additions: list[tuple[int, discord.Role]] = []
        self.logs_created: list[discord.TextChannel] = []
        self.managers: dict[int, str] = dict(existing_managers or {})
        self.security_choices: dict[str, int] = dict(existing_security or {field: 0 for field in AUTOMOD_TOGGLE_LABELS})
        self.security_touched = False  # True dès qu'on clique un préréglage ou qu'on change le menu de filtres
        self.exempt_role_ids: set[int] = set(existing_exempt_roles or [])
        self.picker_selected: str | None = None  # champ en cours de réglage sur la page "picker" (Rôles / Salons)
        self.level_action: str | None = None  # "edit" ou "delete" en attente d'un niveau choisi (page Rôles de niveau)
        self.selected_level: int | None = None
        self.manager_being_edited: int | None = None  # gestionnaire dont on édite les catégories (page Gestionnaires)
        self.manager_categories_cache: dict[int, list[str]] = {}
        self.page = 0
        self.render_page()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cog = self.bot.get_cog("Configuration")
        if cog is None:
            await interaction.response.send_message("❌ Le module de configuration n'est pas chargé.", ephemeral=True)
            return False
        return await cog._can_use_setup(interaction, self.author_id, self.guild_id)

    async def persist_session(self):
        try:
            await self.bot.db.save_setup_session(
                self.message_id, self.guild_id, self.channel_id, self.author_id,
                self.page, json.dumps(self.choices),
            )
        except Exception:
            pass  # la persistance ne doit jamais faire planter l'assistant

    def _guild(self) -> discord.Guild | None:
        return self.bot.get_guild(self.guild_id)

    def _mention_current(self, field: str, conf) -> str:
        """Formate la valeur actuelle d'un champ (choix en attente, sinon valeur déjà
        enregistrée en base) sous forme de mention @rôle / #salon, pour l'afficher
        immédiatement dans l'embed comme demandé."""
        value = self.choices.get(field, conf[field] if conf and field in conf.keys() else None)
        if not value:
            return "*Non défini*"
        guild = self._guild()
        if not guild:
            return f"`{value}`"
        obj = guild.get_role(value) if field in ROLE_FIELDS else guild.get_channel(value)
        return obj.mention if obj else "*Introuvable (supprimé ?)*"

    def _status_indicator(self) -> str:
        if self.dirty:
            return "🟠 Modifications non enregistrées"
        if self.choices or self.level_role_additions or self.logs_created or self.managers or self.security_touched:
            return "🟢 Configuration enregistrée"
        return "⚪ Rien configuré pour l'instant"

    async def build_embed(self) -> discord.Embed:
        step = SETUP_STEPS[self.page]
        total = len(SETUP_STEPS)
        header = f"🛠️ **Configuration SentriX**\nPage {self.page + 1} sur {total} — {step['icon']} {step['title']}"
        bar_line = _progress_bar(self.page, total)
        conf = await self.bot.db.get_guild_config(self.guild_id)

        if step["key"] in ("roles", "channels"):
            fields = PICKER_FIELDS[step["key"]]
            noun = "rôle" if step["key"] == "roles" else "salon"
            desc = (
                f"Choisissez d'abord **quel réglage** vous voulez changer dans le premier menu, "
                f"puis le {noun} correspondant apparaît juste en dessous.\n\n"
                "Valeurs actuelles :"
            )
            e = embeds.neutral(header, f"{bar_line}\n\n{desc}", color=SETUP_COLOR_MAIN)
            lines = [f"{label} : {self._mention_current(field, conf)}" for field, kind, label in fields]
            e.add_field(name="📋 État actuel", value="\n".join(lines)[:1024], inline=False)
            if step["key"] == "roles":
                exempt_text = ", ".join(f"<@&{rid}>" for rid in self.exempt_role_ids) if self.exempt_role_ids else "Aucun"
                e.add_field(name="🚫 Rôles exemptés de l'AutoMod", value=exempt_text[:1024], inline=False)
            if self.picker_selected:
                picked_label = next((label for f, k, label in fields if f == self.picker_selected), self.picker_selected)
                e.add_field(name="👉 En cours de réglage", value=picked_label, inline=False)

        elif step["key"] == "levels":
            rows = await self.bot.db.fetchall(
                "SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (self.guild_id,)
            )
            desc = (
                "Attribuez automatiquement un rôle quand un membre atteint un certain niveau. "
                "Cliquez sur **➕ Ajouter un rôle de niveau** pour chaque palier souhaité.\n\n"
                "⚠️ Chaque ajout ici est enregistré **immédiatement** (pas besoin de 💾 Enregistrer)."
            )
            e = embeds.neutral(header, f"{bar_line}\n\n{desc}", color=SETUP_COLOR_MAIN)
            guild = self._guild()
            if rows:
                lines = []
                for r in rows:
                    role = guild.get_role(r["role_id"]) if guild else None
                    lines.append(f"Niveau **{r['level']}** → {role.mention if role else '*rôle supprimé*'}")
                e.add_field(name=f"🏆 Paliers actuels ({len(rows)})", value="\n".join(lines)[:1024], inline=False)
            else:
                e.add_field(name="🏆 Paliers actuels", value="Aucun pour l'instant.", inline=False)

        elif step["key"] == "tickets":
            panels = await self.bot.db.fetchall("SELECT * FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,))
            types = await self.bot.db.fetchall(
                "SELECT tt.* FROM ticket_types tt JOIN ticket_panels_v2 p ON p.id = tt.panel_id WHERE p.guild_id = ?",
                (self.guild_id,),
            )
            desc = (
                "Le système de tickets a sa propre configuration complète (plusieurs panels, types, "
                "formulaires, boutons staff...), bien plus riche que ce que cette page pourrait afficher.\n\n"
                "👉 Utilisez **`+ticketsetup`** pour tout configurer, ou les boutons ci-dessous pour un accès rapide."
            )
            e = embeds.neutral(header, f"{bar_line}\n\n{desc}", color=SETUP_COLOR_MAIN)
            e.add_field(name="📋 Panels", value=str(len(panels)), inline=True)
            e.add_field(name="🎫 Types de tickets", value=str(len(types)), inline=True)
            ticket_log = f"<#{conf['ticket_log_channel']}>" if conf and conf["ticket_log_channel"] else "*Non défini*"
            e.add_field(name="📝 Salon de logs (repli)", value=ticket_log, inline=True)
            e.add_field(name="⏱️ Suppression après fermeture", value=f"{(conf['ticket_delete_delay'] if conf else 30) or 30}s", inline=True)
            e.add_field(name="📄 Transcript par DM", value="✅ Activé" if (not conf or conf["ticket_transcript_dm"]) else "❌ Désactivé", inline=True)
            e.add_field(name="⭐ Notation du support", value="✅ Activée" if (not conf or conf["ticket_rating_enabled"]) else "❌ Désactivée", inline=True)

        elif step["key"] == "logs":
            desc = (
                "Créez en un clic toute une catégorie de salons de logs privés — le bot y écrit tout seul "
                "ensuite. Les salons déjà configurés ne sont jamais dupliqués.\n\n"
                "Cliquez sur **📡 Créer le système de logs** ci-dessous."
            )
            e = embeds.neutral(header, f"{bar_line}\n\n{desc}", color=SETUP_COLOR_MAIN)
            general = f"<#{conf['log_channel']}>" if conf and conf["log_channel"] else "*Non défini*"
            e.add_field(name="📝 Salon général de repli", value=general, inline=False)
            if self.logs_created:
                e.add_field(name=f"✅ Créés dans cette session ({len(self.logs_created)})", value="\n".join(c.mention for c in self.logs_created)[:1024], inline=False)

        elif step["key"] == "managers":
            desc = (
                "Ajoutez des membres de confiance qui pourront configurer le bot sans avoir besoin d'être "
                "administrateur du serveur.\n\nAjout/retrait immédiat. Utilisez **🔑 Définir les permissions** "
                "pour limiter un gestionnaire à certaines catégories seulement (sinon, accès complet par défaut)."
            )
            e = embeds.neutral(header, f"{bar_line}\n\n{desc}", color=SETUP_COLOR_MAIN)
            if self.managers:
                lines = []
                for uid in self.managers:
                    cats = self.manager_categories_cache.get(uid)
                    if cats is None:
                        cats = await self.bot.db.get_manager_categories(self.guild_id, uid)
                        self.manager_categories_cache[uid] = cats or ["complete"]
                        cats = self.manager_categories_cache[uid]
                    labels = ", ".join(MANAGER_CATEGORIES.get(c, c) for c in cats)
                    lines.append(f"<@{uid}> — {labels}")
                e.add_field(name=f"👥 Gestionnaires actuels ({len(self.managers)})", value="\n".join(lines)[:1024], inline=False)
            else:
                e.add_field(name="👥 Gestionnaires actuels", value="Aucun pour l'instant.", inline=False)

        elif step["key"] == "security":
            desc = (
                "Cliquez sur un **préréglage** (🟢 Faible / 🟡 Moyen / 🔴 Élevé) pour tout régler en un clic, "
                "ou choisissez précisément les filtres actifs dans le menu.\n\n"
                "⚠️ Chaque changement ici est enregistré **immédiatement**."
            )
            e = embeds.neutral(header, f"{bar_line}\n\n{desc}", color=SETUP_COLOR_MAIN)
            active = sum(1 for v in self.security_choices.values() if v)
            score = round(active / len(AUTOMOD_TOGGLE_LABELS) * 100)
            e.add_field(name="📊 Score de sécurité", value=f"**{score}/100** ({active}/{len(AUTOMOD_TOGGLE_LABELS)} filtres actifs)", inline=False)
            lines = [f"{'✅' if self.security_choices.get(field) else '❌'} {label}" for field, label in AUTOMOD_TOGGLE_LABELS.items()]
            e.add_field(name="État des filtres", value="\n".join(lines), inline=False)

        elif step["key"] == "summary":
            e = await self._build_summary_embed()

        else:
            desc = "Choisissez vos options avec les menus ci-dessous. Laissez vide ce que vous ne voulez pas changer."
            if step["key"] == "general":
                desc += "\nUtilisez **✏️ Préfixe & messages** pour le préfixe et les messages de bienvenue/départ."
            e = embeds.neutral(header, f"{bar_line}\n\n{desc}", color=SETUP_COLOR_MAIN)
            for field, kind, label in step["fields"]:
                e.add_field(name=label, value=self._mention_current(field, conf), inline=True)

        e.add_field(name="​", value=self._status_indicator(), inline=False)
        return e

    async def _build_summary_embed(self) -> discord.Embed:
        conf = await self.bot.db.get_guild_config(self.guild_id)
        guild = self._guild()
        total = len(SETUP_STEPS)
        header = f"🛠️ **Configuration SentriX**\nPage {self.page + 1} sur {total} — ✅ Résumé et confirmation"
        e = embeds.neutral(header, f"{_progress_bar(self.page, total)}\n\nVoici l'état actuel de chaque catégorie.", color=SETUP_COLOR_MAIN)

        rows_levels = await self.bot.db.fetchall("SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (self.guild_id,))
        rows_panels = await self.bot.db.fetchall("SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,))
        n_levels = rows_levels[0]["n"] if rows_levels else 0
        n_panels = rows_panels[0]["n"] if rows_panels else 0
        active_security = sum(1 for v in self.security_choices.values() if v)

        def cur(field):
            return self.choices.get(field, conf[field] if conf and field in conf.keys() else None)

        categories = [
            ("⚙️ Général", "✅" if cur("mod_role") and cur("log_channel") else ("⚠️" if cur("mod_role") or cur("log_channel") else "❌")),
            ("🎭 Rôles", "✅" if cur("autorole") or cur("verify_role") else "⚠️"),
            ("🎫 Tickets", "✅" if n_panels else "⚠️"),
            ("📢 Salons annexes", "✅" if any(cur(f) for f in ("level_channel", "suggest_channel", "announce_channel", "giveaway_channel")) else "⚠️"),
            ("🏆 Rôles de niveau", "✅" if n_levels else "⚠️"),
            ("📡 Logs", "✅" if cur("log_channel") else "❌"),
            ("👥 Gestionnaires", "✅" if self.managers else "⚠️"),
            ("🛡️ Sécurité", "✅" if active_security >= 6 else ("⚠️" if active_security > 0 else "❌")),
        ]
        e.add_field(name="État par catégorie", value="\n".join(f"{status} {name}" for name, status in categories), inline=False)

        checks_lines = await self._run_final_checks(guild, conf)
        e.add_field(name="🔎 Vérifications finales", value="\n".join(checks_lines)[:1024], inline=False)
        return e

    async def _run_final_checks(self, guild: discord.Guild | None, conf) -> list[str]:
        lines = []
        if not guild:
            return ["❌ Serveur introuvable (le bot n'y est peut-être plus)."]
        me = guild.me
        perms = me.guild_permissions if me else None
        lines.append("✅ Permissions de base du bot" if perms and perms.manage_roles and perms.manage_channels else "⚠️ Il manque des permissions au bot (Gérer les rôles / salons)")
        lines.append("✅ Rôle staff configuré" if conf and conf["mod_role"] else "⚠️ Aucun rôle staff configuré (page Général)")
        lines.append("✅ Salon de logs configuré" if conf and conf["log_channel"] else "⚠️ Aucun salon de logs configuré (page Logs)")
        active_security = sum(1 for v in self.security_choices.values() if v)
        lines.append("✅ Sécurité active" if active_security > 0 else "❌ Aucune protection AutoMod active — le serveur n'est pas protégé")
        if conf and conf["autorole"]:
            role = guild.get_role(conf["autorole"])
            lines.append("✅ Rôle automatique valide" if role else "⚠️ Le rôle automatique configuré n'existe plus")
        return lines

    def render_page(self):
        self.clear_items()
        step = SETUP_STEPS[self.page]

        if step["key"] in ("roles", "channels"):
            fields = PICKER_FIELDS[step["key"]]
            noun = "rôle" if step["key"] == "roles" else "salon"
            cat_select = discord.ui.Select(
                placeholder=f"Choisissez un {noun} à régler",
                options=[discord.SelectOption(label=label, value=field) for field, kind, label in fields],
                row=0,
            )
            cat_select.callback = self._make_picker_category_callback(cat_select)
            self.add_item(cat_select)
            if self.picker_selected:
                kind = next((k for f, k, l in fields if f == self.picker_selected), "role")
                picked_label = next((l for f, k, l in fields if f == self.picker_selected), self.picker_selected)
                if kind == "role":
                    value_select = discord.ui.RoleSelect(placeholder=f"Choisir : {picked_label}"[:100], row=1)
                    value_select.callback = self._make_picker_role_value_callback(self.picker_selected, value_select)
                else:
                    value_select = discord.ui.ChannelSelect(
                        placeholder=f"Choisir : {picked_label}"[:100], channel_types=[discord.ChannelType.text], row=1
                    )
                    value_select.callback = self._make_picker_channel_value_callback(self.picker_selected, value_select)
                self.add_item(value_select)
            if step["key"] == "roles":
                exempt_select = discord.ui.RoleSelect(
                    placeholder="🚫 Rôles exemptés de l'AutoMod (multi-sélection)",
                    min_values=0, max_values=25, row=2,
                    default_values=[discord.Object(id=rid) for rid in self.exempt_role_ids],
                )
                exempt_select.callback = self._make_exempt_roles_callback(exempt_select)
                self.add_item(exempt_select)
            else:
                clear_btn = discord.ui.Button(label="🧹 Effacer les salons configurés", style=discord.ButtonStyle.secondary, row=2)
                clear_btn.callback = self._clear_channels_clicked
                self.add_item(clear_btn)
        elif step["key"] == "levels":
            add_btn = discord.ui.Button(label="➕ Ajouter un rôle de niveau", style=discord.ButtonStyle.primary, row=0)
            add_btn.callback = self._open_level_role_modal
            self.add_item(add_btn)
            edit_btn = discord.ui.Button(label="✏️ Modifier un palier", style=discord.ButtonStyle.secondary, row=0)
            edit_btn.callback = self._open_level_role_modal
            self.add_item(edit_btn)
            delete_btn = discord.ui.Button(label="🗑️ Supprimer un palier", style=discord.ButtonStyle.danger, row=0)
            delete_btn.callback = self._open_delete_level_role_modal
            self.add_item(delete_btn)
            list_btn = discord.ui.Button(label="📋 Voir tous les paliers", style=discord.ButtonStyle.secondary, row=0)
            list_btn.callback = self._list_level_roles_clicked
            self.add_item(list_btn)
        elif step["key"] == "tickets":
            open_btn = discord.ui.Button(label="🛠️ Configurer les tickets (+ticketsetup)", style=discord.ButtonStyle.primary, row=0)
            open_btn.callback = self._tickets_hint
            self.add_item(open_btn)
        elif step["key"] == "logs":
            logs_btn = discord.ui.Button(label="📡 Créer le système de logs", style=discord.ButtonStyle.primary, row=0)
            logs_btn.callback = self._create_logs_clicked
            self.add_item(logs_btn)
        elif step["key"] == "managers":
            add_select = discord.ui.UserSelect(placeholder="➕ Ajouter des gestionnaires", min_values=0, max_values=10, row=0)
            add_select.callback = self._make_manager_add_callback(add_select)
            self.add_item(add_select)
            if self.managers:
                remove_select = discord.ui.Select(
                    placeholder="🗑️ Retirer un gestionnaire",
                    options=[discord.SelectOption(label=name[:100], value=str(uid)) for uid, name in list(self.managers.items())[:25]],
                    row=1,
                )
                remove_select.callback = self._make_manager_remove_callback(remove_select)
                self.add_item(remove_select)

                perm_select = discord.ui.Select(
                    placeholder="🔑 Définir les permissions d'un gestionnaire",
                    options=[
                        discord.SelectOption(label=name[:100], value=str(uid), default=(uid == self.manager_being_edited))
                        for uid, name in list(self.managers.items())[:25]
                    ],
                    row=2,
                )
                perm_select.callback = self._make_manager_permedit_callback(perm_select)
                self.add_item(perm_select)

                if self.manager_being_edited is not None and self.manager_being_edited in self.managers:
                    current_cats = self.manager_categories_cache.get(self.manager_being_edited, ["complete"])
                    target_name = self.managers.get(self.manager_being_edited, "ce gestionnaire")
                    cat_select = discord.ui.Select(
                        placeholder=f"Catégories pour {target_name}"[:100],
                        min_values=0, max_values=len(MANAGER_CATEGORIES),
                        options=[
                            discord.SelectOption(label=label, value=cat, default=(cat in current_cats))
                            for cat, label in MANAGER_CATEGORIES.items()
                        ],
                        row=3,
                    )
                    cat_select.callback = self._make_manager_categories_callback(cat_select)
                    self.add_item(cat_select)
        elif step["key"] == "security":
            presets = [
                ("🟢 Faible", "faible", discord.ButtonStyle.success),
                ("🟡 Moyen", "moyen", discord.ButtonStyle.primary),
                ("🔴 Élevé", "eleve", discord.ButtonStyle.danger),
            ]
            for label, level, style in presets:
                btn = discord.ui.Button(label=label, style=style, row=0)
                btn.callback = self._make_security_preset_callback(level)
                self.add_item(btn)
            select = discord.ui.Select(
                placeholder="🎚️ Choisir précisément les filtres actifs",
                min_values=0, max_values=len(AUTOMOD_TOGGLE_LABELS),
                options=[
                    discord.SelectOption(label=label, value=field, default=bool(self.security_choices.get(field)))
                    for field, label in AUTOMOD_TOGGLE_LABELS.items()
                ],
                row=1,
            )
            select.callback = self._make_security_select_callback(select)
            self.add_item(select)
        elif step["key"] == "summary":
            prev_btn = SetupNavButton("prev", self.message_id, label="◀ Précédent", style=discord.ButtonStyle.secondary, row=0)
            summary_btn = SetupNavButton("summary", self.message_id, label="👁️ Voir le résumé complet", style=discord.ButtonStyle.secondary, row=0)
            save_btn = SetupNavButton("save", self.message_id, label="💾 Enregistrer définitivement", style=discord.ButtonStyle.success, row=0)
            restart_btn = SetupNavButton("restart", self.message_id, label="🔄 Recommencer", style=discord.ButtonStyle.secondary, row=0)
            finish_btn = SetupNavButton("finish", self.message_id, label="✅ Terminer", style=discord.ButtonStyle.success, row=0)
            for item in (prev_btn, summary_btn, save_btn, restart_btn, finish_btn):
                self.add_item(item)
        else:
            for i, field in enumerate(step["fields"]):
                key, kind, label = field[0], field[1], field[2]
                if kind == "role":
                    select = discord.ui.RoleSelect(placeholder=label, row=i)
                    select.callback = self._make_role_callback(key, select)
                else:
                    channel_types = field[3] if len(field) > 3 else [discord.ChannelType.text]
                    select = discord.ui.ChannelSelect(placeholder=label, channel_types=channel_types, row=i)
                    select.callback = self._make_channel_callback(key, select)
                self.add_item(select)

        if step["key"] != "summary":
            # Discord limite chaque message à 5 lignes de composants. Les pages "Général" et
            # "Salons annexes" utilisent déjà leurs 4 premières lignes (0-3) pour les menus
            # déroulants : il ne reste qu'UNE ligne (la 4ᵉ) pour les boutons, qui accepte au
            # maximum 5 boutons. Les 4 boutons de navigation essentiels (◀ 💾 ▶ ❌) sont donc
            # toujours présents, et le 5ᵉ bouton change selon la page : "✏️ Préfixe & messages"
            # sur la page Général (qui en a besoin), "👁️ Aperçu" partout ailleurs (l'aperçu
            # reste de toute façon accessible depuis n'importe quelle autre page).
            self.add_item(SetupNavButton("prev", self.message_id, label="◀ Précédent", style=discord.ButtonStyle.secondary, disabled=(self.page == 0)))
            self.add_item(SetupNavButton("save", self.message_id, label="💾 Enregistrer", style=discord.ButtonStyle.success))
            self.add_item(SetupNavButton("next", self.message_id, label="Suivant ▶", style=discord.ButtonStyle.primary))
            if step["key"] == "general":
                text_btn = discord.ui.Button(label="✏️ Préfixe & messages", style=discord.ButtonStyle.secondary, row=4)
                text_btn.callback = self._open_text_modal
                self.add_item(text_btn)
            else:
                self.add_item(SetupNavButton("preview", self.message_id, label="👁️ Aperçu", style=discord.ButtonStyle.secondary))
            self.add_item(SetupNavButton("cancel", self.message_id, label="❌ Annuler", style=discord.ButtonStyle.danger))

    # ---------------------------------------------------------------- ACTIONS SPÉCIFIQUES AUX PAGES

    async def _open_level_role_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LevelRoleModal(self))

    async def _open_delete_level_role_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DeleteLevelRoleModal(self))

    async def _list_level_roles_clicked(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (self.guild_id,)
        )
        if not rows:
            return await interaction.response.send_message("Aucun rôle de niveau configuré pour l'instant.", ephemeral=True)
        guild = self._guild()
        lines = []
        for r in rows:
            role = guild.get_role(r["role_id"]) if guild else None
            lines.append(f"Niveau **{r['level']}** → {role.mention if role else '*rôle supprimé*'}")
        e = embeds.neutral("🏆 Tous les paliers de niveau", "\n".join(lines)[:4000], color=SETUP_COLOR_MAIN)
        await interaction.response.send_message(embed=e, ephemeral=True)

    async def _tickets_hint(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Tapez `+ticketsetup` (ou `/ticketsetup`) dans ce salon pour ouvrir le menu complet de "
            "configuration des tickets (panels, types, formulaires, boutons staff...).",
            ephemeral=True,
        )

    async def _create_logs_clicked(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cog: "Configuration" = self.bot.get_cog("Configuration")
        created = await cog.create_log_channels(interaction.guild, interaction.user)
        self.logs_created.extend(created)
        await self.persist_session()
        await interaction.edit_original_response(embed=await self.build_embed(), view=self)

    @staticmethod
    async def _warn_ephemeral(interaction: discord.Interaction, text: str):
        """Envoie un avertissement éphémère, que la réponse initiale de l'interaction ait
        déjà été utilisée (ex: par une boîte de confirmation Administrateur) ou non."""
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    async def _refresh_message(self, interaction: discord.Interaction):
        """Met à jour le VRAI message de l'assistant avec l'état actuel.

        BUG ÉVITÉ ICI : si la réponse de cette interaction a déjà été utilisée pour
        envoyer un message éphémère (ex: la boîte de confirmation "rôle Administrateur,
        continuer ?"), interaction.edit_original_response() éditerait ce message
        éphémère — visible seulement par la personne qui a cliqué — au lieu du VRAI
        message de l'assistant, visible par tout le monde. On va donc chercher le vrai
        message directement via son salon et son ID dans ce cas précis."""
        embed = await self.build_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
            return
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.channel_id)
            message = await channel.fetch_message(self.message_id)
            await message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    async def _validate_role_selection(self, interaction: discord.Interaction, role: discord.Role) -> bool:
        """Les 4 vérifications demandées avant d'accepter un rôle "sensible" choisi dans
        /setup : jamais @everyone, confirmation si Administrateur, hiérarchie du bot,
        permission Gérer les rôles. Retourne True si le rôle peut être utilisé."""
        if role.id == interaction.guild.default_role.id:
            await interaction.response.send_message("❌ `@everyone` ne peut pas être choisi ici.", ephemeral=True)
            return False
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "⚠️ SentriX n'a pas la permission **Gérer les rôles** sur ce serveur — ce réglage ne pourra pas "
                "fonctionner tant que cette permission n'est pas accordée au bot.", ephemeral=True,
            )
            return False
        if role.permissions.administrator:
            confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
            await interaction.response.send_message(
                embed=embeds.warning(f"{role.mention} a la permission **Administrateur**. Continuer quand même ?"),
                view=confirm, ephemeral=True,
            )
            await confirm.wait()
            if not confirm.value:
                return False
        if interaction.guild.me.top_role <= role:
            await self._warn_ephemeral(
                interaction, f"⚠️ Le rôle du bot doit être placé **au-dessus** de {role.mention} pour pouvoir l'utiliser."
            )
            return False
        return True

    def _make_role_callback(self, field: str, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                role = select.values[0]
                if not await self._validate_role_selection(interaction, role):
                    return
                self.choices[field] = role.id
                self.dirty = True
            await self.persist_session()
            await self._refresh_message(interaction)
        return callback

    def _make_channel_callback(self, field: str, select: discord.ui.ChannelSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
                self.dirty = True
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    # ---------------------------------------------------------------- PICKER (pages Rôles / Salons)

    def _make_picker_category_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.picker_selected = select.values[0]
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_picker_role_value_callback(self, field: str, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                role = select.values[0]
                if not await self._validate_role_selection(interaction, role):
                    return
                self.choices[field] = role.id
                self.dirty = True
            self.picker_selected = None
            await self.persist_session()
            self.render_page()
            await self._refresh_message(interaction)
        return callback

    def _make_picker_channel_value_callback(self, field: str, select: discord.ui.ChannelSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
                self.dirty = True
            self.picker_selected = None
            await self.persist_session()
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_exempt_roles_callback(self, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            new_ids = {role.id for role in select.values}
            added = new_ids - self.exempt_role_ids
            removed = self.exempt_role_ids - new_ids
            for rid in added:
                await self.bot.db.add_automod_exempt_role(self.guild_id, rid)
            for rid in removed:
                await self.bot.db.remove_automod_exempt_role(self.guild_id, rid)
            self.exempt_role_ids = new_ids
            automod_cog = self.bot.get_cog("Automod")
            if automod_cog:
                automod_cog.exempt_roles_cache.pop(self.guild_id, None)
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    async def _clear_channels_clicked(self, interaction: discord.Interaction):
        confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
        await interaction.response.send_message(
            embed=embeds.warning(
                "Voulez-vous vraiment retirer TOUS les salons configurés sur cette page ? "
                "Les salons Discord eux-mêmes ne seront **pas** supprimés — seul le lien avec SentriX le sera.",
                title="🧹 Effacer les salons configurés ?",
            ),
            view=confirm, ephemeral=True,
        )
        await confirm.wait()
        if not confirm.value:
            return
        for field, kind, label in PICKER_FIELDS["channels"]:
            await self.bot.db.set_guild_config(self.guild_id, field, None)
            self.choices.pop(field, None)
        self.picker_selected = None
        await self.persist_session()
        self.render_page()
        await interaction.followup.send(embed=embeds.success("Tous les salons annexes ont été retirés de la configuration."), ephemeral=True)
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                message = await channel.fetch_message(self.message_id)
                await message.edit(embed=await self.build_embed(), view=self)
        except discord.HTTPException:
            pass

    def _make_manager_add_callback(self, select: discord.ui.UserSelect):
        async def callback(interaction: discord.Interaction):
            for user in select.values:
                if user.bot:
                    continue
                await self.bot.db.add_bot_manager(self.guild_id, user.id, self.author_id)
                self.managers[user.id] = user.display_name
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_manager_remove_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                user_id = int(select.values[0])
                await self.bot.db.remove_bot_manager(self.guild_id, user_id)
                self.managers.pop(user_id, None)
                self.manager_categories_cache.pop(user_id, None)
                if self.manager_being_edited == user_id:
                    self.manager_being_edited = None
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_manager_permedit_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                user_id = int(select.values[0])
                self.manager_being_edited = user_id
                if user_id not in self.manager_categories_cache:
                    cats = await self.bot.db.get_manager_categories(self.guild_id, user_id)
                    self.manager_categories_cache[user_id] = cats or ["complete"]
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_manager_categories_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            user_id = self.manager_being_edited
            if user_id is None:
                return await interaction.response.defer()
            # Un gestionnaire ne doit JAMAIS pouvoir s'accorder lui-même plus de
            # permissions — seuls le propriétaire du serveur, un administrateur, ou le
            # propriétaire du bot peuvent modifier les catégories d'un gestionnaire.
            is_privileged = (
                interaction.user.id in config.OWNER_IDS
                or interaction.user.id == interaction.guild.owner_id
                or (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
            )
            if interaction.user.id == user_id and not is_privileged:
                return await interaction.response.send_message(
                    "❌ Vous ne pouvez pas modifier vos propres permissions de gestionnaire.", ephemeral=True
                )
            categories = list(select.values)
            await self.bot.db.set_manager_categories(self.guild_id, user_id, categories, interaction.user.id)
            self.manager_categories_cache[user_id] = categories or ["complete"]
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_security_preset_callback(self, level: str):
        async def callback(interaction: discord.Interaction):
            for field, value in SECURITY_PRESETS.get(level, {}).items():
                await self.bot.db.set_automod(self.guild_id, field, value)
                self.security_choices[field] = value
            await self.bot.db.set_guild_config(self.guild_id, "security_level", level)
            automod_cog = self.bot.get_cog("Automod")
            if automod_cog:
                automod_cog.automod_cache.pop(self.guild_id, None)
            self.security_touched = True
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_security_select_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            chosen = set(select.values)
            for field in AUTOMOD_TOGGLE_LABELS:
                value = 1 if field in chosen else 0
                await self.bot.db.set_automod(self.guild_id, field, value)
                self.security_choices[field] = value
            automod_cog = self.bot.get_cog("Automod")
            if automod_cog:
                automod_cog.automod_cache.pop(self.guild_id, None)
            self.security_touched = True
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    async def _open_text_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SetupTextModal(self))

    # ---------------------------------------------------------------- NAVIGATION STANDARD

    async def handle_nav_action(self, interaction: discord.Interaction, action: str):
        if action == "prev":
            self.page = max(0, self.page - 1)
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        elif action == "next":
            self.page = min(len(SETUP_STEPS) - 1, self.page + 1)
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        elif action == "save":
            await self._save_pending(interaction)
        elif action in ("preview", "summary"):
            await self._show_preview(interaction)
        elif action == "cancel":
            await self._ask_cancel(interaction)
        elif action == "finish":
            await self._finish(interaction)
        elif action == "restart":
            await self._restart(interaction)

    async def _save_pending(self, interaction: discord.Interaction):
        if not self.choices:
            self.dirty = False
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
            return
        for field, value in self.choices.items():
            await self.bot.db.set_guild_config(self.guild_id, field, value)
        if "prefix" in self.choices:
            self.bot.prefix_cache[self.guild_id] = self.choices["prefix"]
        self.dirty = False
        await self.persist_session()
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    async def _show_preview(self, interaction: discord.Interaction):
        e = await self._build_summary_embed()
        e.title = "👁️ Aperçu de la configuration"
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=e, ephemeral=True)
        else:
            await interaction.followup.send(embed=e, ephemeral=True)

    async def _ask_cancel(self, interaction: discord.Interaction):
        confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
        await interaction.response.send_message(
            embed=embeds.warning(
                "Voulez-vous vraiment annuler ? Les choix **non enregistrés** (rôles/salons pas encore "
                "sauvegardés avec 💾) seront perdus. Ce qui est déjà enregistré (rôles de niveau, logs, "
                "gestionnaires, sécurité) ne sera **pas** supprimé.",
                title="❌ Annuler la configuration ?",
            ),
            view=confirm, ephemeral=True,
        )
        await confirm.wait()
        if not confirm.value:
            return
        await self.bot.db.delete_setup_session(self.message_id)
        cog = self.bot.get_cog("Configuration")
        if cog:
            cog.active_setups.pop(self.message_id, None)
        for child in self.children:
            child.disabled = True
        self.stop()
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                message = await channel.fetch_message(self.message_id)
                await message.edit(embed=embeds.neutral("❌ Configuration annulée", "Rien de ce qui était déjà enregistré n'a été supprimé.", color=SETUP_COLOR_DANGER), view=self)
        except discord.HTTPException:
            pass

    async def _restart(self, interaction: discord.Interaction):
        self.choices = {}
        self.dirty = False
        self.page = 0
        self.render_page()
        await self.persist_session()
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    async def _finish(self, interaction: discord.Interaction):
        if self.choices:
            for field, value in self.choices.items():
                await self.bot.db.set_guild_config(self.guild_id, field, value)
            if "prefix" in self.choices:
                self.bot.prefix_cache[self.guild_id] = self.choices["prefix"]
        lines = [f"✅ {FIELD_LABELS.get(k, k)}" for k in self.choices]
        if self.level_role_additions:
            lines.append(f"✅ {len(self.level_role_additions)} rôle(s) de niveau")
        if self.logs_created:
            lines.append(f"✅ {len(self.logs_created)} salon(s) de logs créés")
        if self.managers:
            lines.append(f"✅ {len(self.managers)} gestionnaire(s) du bot")
        if self.security_touched:
            active_filters = sum(1 for v in self.security_choices.values() if v)
            lines.append(f"✅ Sécurité : {active_filters}/{len(AUTOMOD_TOGGLE_LABELS)} filtre(s) actif(s)")
        if not lines:
            lines.append("Aucun changement — la configuration existante a été conservée telle quelle.")

        # Vérifications finales demandées avant de clore l'assistant : permissions du bot,
        # rôle staff, salon de logs, sécurité, rôles automatiques. Purement informatif —
        # ça n'empêche jamais de terminer, ça prévient juste d'un oubli éventuel.
        conf = await self.bot.db.get_guild_config(self.guild_id)
        checks_lines = await self._run_final_checks(self._guild(), conf)

        self.dirty = False
        await self.bot.db.delete_setup_session(self.message_id)
        cog = self.bot.get_cog("Configuration")
        if cog:
            cog.active_setups.pop(self.message_id, None)
        for child in self.children:
            child.disabled = True
        final_embed = embeds.neutral("✅ Configuration enregistrée !", "\n".join(lines), color=SETUP_COLOR_SUCCESS)
        final_embed.add_field(name="🔎 Vérifications finales", value="\n".join(checks_lines)[:1024], inline=False)
        await interaction.response.edit_message(embed=final_embed, view=self)
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(Configuration(bot))
