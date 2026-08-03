"""
Cog CONFIGURATION.
/setup (assistant complet en un clic) /setprefix /setmodrole /setlogchannel /create-logs
/setwelcomechannel /setgoodbyechannel /setwelcomemessage /setgoodbyemessage
/setticketcategory /setticketlogchannel /setautorole /disablecommand /enablecommand
/ignorechannel /unignorechannel /config-view /config-reset /setlevelchannel
/setsuggestchannel /setannouncechannel /setgiveawaychannel
"""

import re
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds, checks, helpers

ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")

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
        un formulaire, sans jamais avoir à taper une commande. Découpé en pages
        pour rester lisible (Discord limite un message à 5 lignes de menus).
        """
        rows = await self.bot.db.list_bot_managers(ctx.guild.id)
        existing_managers = {}
        for row in rows:
            member = ctx.guild.get_member(row["user_id"])
            existing_managers[row["user_id"]] = member.display_name if member else f"Membre {row['user_id']}"

        view = SetupView(self.bot, ctx.guild.id, ctx.author.id, existing_managers=existing_managers)
        await ctx.send(embed=view.build_embed(), view=view)

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
    {
        "title": "1/6 — Général",
        "fields": [
            ("mod_role", "role", "🛡️ Rôle staff (modération)"),
            ("log_channel", "channel", "📝 Salon de logs (sanctions)"),
            ("welcome_channel", "channel", "👋 Salon de bienvenue"),
            ("goodbye_channel", "channel", "🚪 Salon de départ"),
        ],
    },
    {
        "title": "2/6 — Rôles & Tickets",
        "fields": [
            ("autorole", "role", "🎭 Rôle automatique à l'arrivée"),
            ("verify_role", "role", "✅ Rôle donné après vérification"),
            ("ticket_category", "channel", "🎫 Catégorie des tickets", [discord.ChannelType.category]),
            ("ticket_log_channel", "channel", "🎫 Salon de logs des tickets"),
        ],
    },
    {
        "title": "3/6 — Salons annexes",
        "fields": [
            ("level_channel", "channel", "📈 Annonces de passage de niveau"),
            ("suggest_channel", "channel", "💡 Suggestions"),
            ("announce_channel", "channel", "📢 Annonces générales"),
            ("giveaway_channel", "channel", "🎉 Giveaways par défaut"),
        ],
    },
    {
        "title": "4/6 — Rôles de niveau",
        "fields": [],
        "custom": "level_roles",
    },
    {
        "title": "5/6 — Système de logs",
        "fields": [],
        "custom": "logs_setup",
    },
    {
        "title": "6/6 — Gestionnaires du bot",
        "fields": [],
        "custom": "managers",
    },
]

FIELD_LABELS = {
    "mod_role": "Rôle staff", "log_channel": "Salon de logs", "welcome_channel": "Salon de bienvenue",
    "goodbye_channel": "Salon de départ", "autorole": "Rôle automatique", "verify_role": "Rôle de vérification",
    "ticket_category": "Catégorie tickets", "ticket_log_channel": "Logs tickets",
    "level_channel": "Annonces de niveau", "suggest_channel": "Suggestions",
    "announce_channel": "Annonces", "giveaway_channel": "Giveaways",
    "prefix": "Préfixe", "welcome_message": "Message de bienvenue", "goodbye_message": "Message de départ",
}


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
        await interaction.response.edit_message(embed=self.view_ref.build_embed(), view=self.view_ref)


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

        await self.view_ref.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (self.view_ref.guild_id, level, role.id),
        )
        self.view_ref.level_role_additions.append((level, role))
        await interaction.response.edit_message(embed=self.view_ref.build_embed(), view=self.view_ref)


class SetupView(discord.ui.View):
    """
    Assistant /setup complet : parcourt toutes les pages de SETUP_STEPS (menus
    déroulants rôles/salons) + un formulaire dédié au préfixe et aux messages
    texte. Rien n'est écrit en base tant qu'on n'a pas cliqué sur "Terminer".
    """

    def __init__(self, bot: commands.Bot, guild_id: int, author_id: int, existing_managers: dict | None = None):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.choices: dict = {}
        self.level_role_additions: list[tuple[int, discord.Role]] = []
        self.logs_created: list[discord.TextChannel] = []
        self.managers: dict[int, str] = dict(existing_managers or {})
        self.page = 0
        self.render_page()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seule la personne ayant lancé `/setup` peut l'utiliser.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        step = SETUP_STEPS[self.page]
        if step.get("custom") == "level_roles":
            e = embeds.neutral(
                f"🧙 Assistant de configuration — {step['title']}",
                "Attribuez automatiquement un rôle personnalisé quand un membre atteint un certain niveau. "
                "Cliquez sur **➕ Ajouter un rôle de niveau** pour chaque palier souhaité "
                "(vous pouvez en ajouter autant que vous voulez).\n\n"
                "⚠️ Contrairement aux autres pages, chaque ajout ici est enregistré **immédiatement**.",
            )
            if self.level_role_additions:
                lines = [f"Niveau **{lvl}** → {role.mention}" for lvl, role in self.level_role_additions]
                e.add_field(name=f"✅ Ajoutés dans cette session ({len(self.level_role_additions)})", value="\n".join(lines), inline=False)
            return e

        if step.get("custom") == "logs_setup":
            e = embeds.neutral(
                f"🧙 Assistant de configuration — {step['title']}",
                "Créez en un clic toute une catégorie de salons de logs privés (serveur, messages, membres, "
                "vocal, rôles, modération, sécurité) — le bot y écrit tout seul ensuite, rien d'autre à faire.\n\n"
                "Cliquez sur **📡 Créer le système de logs** ci-dessous. Les salons déjà configurés ne sont "
                "jamais dupliqués.",
            )
            if self.logs_created:
                lines = "\n".join(c.mention for c in self.logs_created)
                e.add_field(name=f"✅ Créés dans cette session ({len(self.logs_created)})", value=lines, inline=False)
            return e

        if step.get("custom") == "managers":
            e = embeds.neutral(
                f"🧙 Assistant de configuration — {step['title']}",
                "Ajoutez des membres de confiance qui pourront configurer le bot (utiliser `/setup`, "
                "changer les rôles/salons, l'anti-nuke, etc.) **sans avoir besoin d'être administrateur** "
                "du serveur.\n\n"
                "Utilisez le menu **➕ Ajouter des gestionnaires** ci-dessous, ou **🗑️ Retirer un gestionnaire** "
                "pour en enlever un. Chaque changement est enregistré immédiatement.",
            )
            if self.managers:
                lines = "\n".join(f"<@{uid}>" for uid in self.managers)
                e.add_field(name=f"✅ Gestionnaires actuels ({len(self.managers)})", value=lines, inline=False)
            else:
                e.add_field(name="Gestionnaires actuels", value="Aucun pour l'instant.", inline=False)
            return e

        e = embeds.neutral(
            f"🧙 Assistant de configuration — {step['title']}",
            "Choisissez vos options avec les menus ci-dessous. Laissez vide ce que vous ne voulez pas configurer.\n"
            "Utilisez **✏️ Préfixe & messages** pour le préfixe et les messages de bienvenue/départ.",
        )
        if self.choices:
            summary = ", ".join(FIELD_LABELS.get(k, k) for k in self.choices)
            e.add_field(name=f"✅ Déjà configuré ({len(self.choices)})", value=summary, inline=False)
        return e

    def render_page(self):
        self.clear_items()
        step = SETUP_STEPS[self.page]

        if step.get("custom") == "level_roles":
            add_btn = discord.ui.Button(label="➕ Ajouter un rôle de niveau", style=discord.ButtonStyle.primary, row=0)
            add_btn.callback = self._open_level_role_modal
            self.add_item(add_btn)
        elif step.get("custom") == "logs_setup":
            logs_btn = discord.ui.Button(label="📡 Créer le système de logs", style=discord.ButtonStyle.primary, row=0)
            logs_btn.callback = self._create_logs_clicked
            self.add_item(logs_btn)
        elif step.get("custom") == "managers":
            add_select = discord.ui.UserSelect(
                placeholder="➕ Ajouter des gestionnaires", min_values=0, max_values=10, row=0
            )
            add_select.callback = self._make_manager_add_callback(add_select)
            self.add_item(add_select)
            if self.managers:
                remove_select = discord.ui.Select(
                    placeholder="🗑️ Retirer un gestionnaire",
                    options=[
                        discord.SelectOption(label=name[:100], value=str(uid))
                        for uid, name in list(self.managers.items())[:25]
                    ],
                    row=1,
                )
                remove_select.callback = self._make_manager_remove_callback(remove_select)
                self.add_item(remove_select)
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

        prev_btn = discord.ui.Button(
            label="◀ Précédent", style=discord.ButtonStyle.secondary, row=4, disabled=(self.page == 0)
        )
        prev_btn.callback = self._go_prev
        self.add_item(prev_btn)

        text_btn = discord.ui.Button(label="✏️ Préfixe & messages", style=discord.ButtonStyle.secondary, row=4)
        text_btn.callback = self._open_text_modal
        self.add_item(text_btn)

        if self.page < len(SETUP_STEPS) - 1:
            next_btn = discord.ui.Button(label="Suivant ▶", style=discord.ButtonStyle.primary, row=4)
            next_btn.callback = self._go_next
            self.add_item(next_btn)
        else:
            finish_btn = discord.ui.Button(label="✅ Terminer", style=discord.ButtonStyle.success, row=4)
            finish_btn.callback = self._finish
            self.add_item(finish_btn)

    async def _open_level_role_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LevelRoleModal(self))

    async def _create_logs_clicked(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cog: "Configuration" = self.bot.get_cog("Configuration")
        created = await cog.create_log_channels(interaction.guild, interaction.user)
        self.logs_created.extend(created)
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    def _make_role_callback(self, field: str, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    def _make_channel_callback(self, field: str, select: discord.ui.ChannelSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    def _make_manager_add_callback(self, select: discord.ui.UserSelect):
        async def callback(interaction: discord.Interaction):
            for user in select.values:
                if user.bot:
                    continue
                await self.bot.db.add_bot_manager(self.guild_id, user.id, self.author_id)
                self.managers[user.id] = user.display_name
            self.render_page()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    def _make_manager_remove_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                user_id = int(select.values[0])
                await self.bot.db.remove_bot_manager(self.guild_id, user_id)
                self.managers.pop(user_id, None)
            self.render_page()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    async def _go_prev(self, interaction: discord.Interaction):
        self.page -= 1
        self.render_page()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _go_next(self, interaction: discord.Interaction):
        self.page += 1
        self.render_page()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _open_text_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SetupTextModal(self))

    async def _finish(self, interaction: discord.Interaction):
        if not self.choices and not self.level_role_additions and not self.logs_created and not self.managers:
            return await interaction.response.send_message("Vous n'avez rien configuré pour l'instant.", ephemeral=True)
        for field, value in self.choices.items():
            await self.bot.db.set_guild_config(self.guild_id, field, value)
        if "prefix" in self.choices:
            self.bot.prefix_cache[self.guild_id] = self.choices["prefix"]
        lines = [f"✅ {FIELD_LABELS.get(k, k)}" for k in self.choices]
        if self.level_role_additions:
            lines.append(f"✅ {len(self.level_role_additions)} rôle(s) de niveau (déjà enregistrés)")
        if self.logs_created:
            lines.append(f"✅ {len(self.logs_created)} salon(s) de logs (déjà créés)")
        if self.managers:
            lines.append(f"✅ {len(self.managers)} gestionnaire(s) du bot (déjà enregistrés)")
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=embeds.success("Configuration enregistrée !\n\n" + "\n".join(lines)), view=self
        )
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(Configuration(bot))
