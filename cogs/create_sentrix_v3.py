"""Serveur officiel SentriX V3 — +create sentrix.

Cette version remplace l'ancien template générique par un espace officiel SentriX :
- rôles professionnels spécialisés, sans liste interminable ;
- salons avec emoji et identité SentriX ;
- un message d'orientation dans chaque salon créé/géré ;
- règlement complet en embed ;
- vrais logs automatiques séparés ;
- vrai panel Tickets V2 ;
- #🤖・sentrix-chat répond sans préfixe.

Une installation V2 peut être mise à niveau une fois vers V3. Les salons principaux sont
recherchés aussi sous leurs anciens noms afin d'être renommés au lieu d'être dupliqués.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

import config
from utils import checks, log_service

logger = logging.getLogger("bot.create-sentrix-v3")
TEMPLATE_KEY = "sentrix-official-v3"
CORE_AUTOMOD = ("antispam", "antiinvite", "antimention", "antiraid", "antiscam")

INSTALL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sentrix_server_installations (
    guild_id INTEGER PRIMARY KEY,
    installed_at INTEGER NOT NULL,
    installed_by INTEGER NOT NULL,
    template_key TEXT NOT NULL DEFAULT 'sentrix-official-v3'
)
"""


ROLE_SPECS = (
    ("Owner SentriX", 0x5C4CD2, discord.Permissions(administrator=True)),
    ("Lead Developer", 0x6D5DE7, discord.Permissions(
        view_audit_log=True, manage_guild=True, manage_roles=True, manage_channels=True,
        manage_webhooks=True, manage_messages=True, manage_threads=True,
    )),
    ("Developer SentriX", 0x667085, discord.Permissions(
        manage_webhooks=True, manage_messages=True, manage_threads=True,
    )),
    ("Security Engineer", 0xD9534F, discord.Permissions(
        view_audit_log=True, kick_members=True, ban_members=True, moderate_members=True,
        manage_messages=True, manage_threads=True,
    )),
    ("Support Lead", 0x2E8B8B, discord.Permissions(
        moderate_members=True, manage_messages=True, manage_threads=True,
        manage_nicknames=True, move_members=True,
    )),
    ("Support Specialist", 0x4BA3A3, discord.Permissions(
        manage_messages=True, manage_threads=True, move_members=True,
    )),
    ("Community Manager", 0xB15AC7, discord.Permissions(
        manage_messages=True, manage_threads=True, manage_events=True,
    )),
    ("QA Tester", 0x7D8799, discord.Permissions.none()),
    ("Staff SentriX", 0x596579, discord.Permissions(
        manage_messages=True, manage_threads=True,
    )),
)


class CreateSentriXV3(commands.Cog, name="CreateSentrix"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def _ensure_table(self) -> None:
        await self.bot.db.execute(INSTALL_TABLE_SQL)

    async def _installation(self, guild_id: int):
        await self._ensure_table()
        return await self.bot.db.fetchone(
            "SELECT guild_id,installed_at,installed_by,template_key "
            "FROM sentrix_server_installations WHERE guild_id=?",
            (guild_id,),
        )

    async def _mark_installed(self, guild_id: int, user_id: int) -> None:
        await self.bot.db.execute(
            "INSERT INTO sentrix_server_installations "
            "(guild_id,installed_at,installed_by,template_key) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET installed_at=excluded.installed_at,"
            "installed_by=excluded.installed_by,template_key=excluded.template_key",
            (guild_id, int(time.time()), user_id, TEMPLATE_KEY),
        )

    async def _role(self, guild: discord.Guild, name: str, colour: int, permissions: discord.Permissions):
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            role = await guild.create_role(
                name=name,
                colour=discord.Colour(colour),
                permissions=permissions,
                hoist=True,
                mentionable=False,
                reason="Installation SentriX V3",
            )
            return role, True
        try:
            await role.edit(
                colour=discord.Colour(colour), permissions=permissions, hoist=True,
                reason="Mise à niveau SentriX V3",
            )
        except discord.HTTPException:
            pass
        return role, False

    @staticmethod
    def _find_category(guild: discord.Guild, names: set[str]):
        folded = {name.casefold() for name in names}
        return next((c for c in guild.categories if c.name.casefold() in folded), None)

    async def _category(self, guild: discord.Guild, desired: str, aliases: set[str], overwrites=None):
        category = self._find_category(guild, {desired, *aliases})
        if category is None:
            category = await guild.create_category(
                desired, overwrites=overwrites or {}, reason="Installation SentriX V3"
            )
            return category, True
        changes = {}
        if category.name != desired:
            changes["name"] = desired
        if overwrites is not None:
            changes["overwrites"] = overwrites
        if changes:
            try:
                await category.edit(reason="Mise à niveau SentriX V3", **changes)
            except discord.HTTPException:
                pass
        return category, False

    @staticmethod
    def _find_text(guild: discord.Guild, names: set[str]):
        folded = {name.casefold() for name in names}
        return next((c for c in guild.text_channels if c.name.casefold() in folded), None)

    async def _text(self, guild, category, desired, aliases, topic, overwrites):
        channel = self._find_text(guild, {desired, *aliases})
        if channel is None:
            channel = await guild.create_text_channel(
                desired, category=category, topic=topic[:1024], overwrites=overwrites,
                reason="Installation SentriX V3",
            )
            return channel, True
        try:
            await channel.edit(
                name=desired, category=category, topic=topic[:1024], overwrites=overwrites,
                reason="Mise à niveau SentriX V3",
            )
        except discord.HTTPException:
            pass
        return channel, False

    async def _voice(self, guild, category, desired, aliases, overwrites):
        folded = {desired.casefold(), *(name.casefold() for name in aliases)}
        channel = next((c for c in guild.voice_channels if c.name.casefold() in folded), None)
        if channel is None:
            channel = await guild.create_voice_channel(
                desired, category=category, overwrites=overwrites,
                reason="Installation SentriX V3",
            )
            return channel, True
        try:
            await channel.edit(
                name=desired, category=category, overwrites=overwrites,
                reason="Mise à niveau SentriX V3",
            )
        except discord.HTTPException:
            pass
        return channel, False

    async def _seed_text(self, channel: discord.TextChannel, text: str) -> None:
        signature = text[:60]
        try:
            async for message in channel.history(limit=35):
                if self.bot.user and message.author.id == self.bot.user.id and signature in (message.content or ""):
                    return
        except discord.HTTPException:
            pass
        await channel.send(text)

    async def _seed_embed(self, channel: discord.TextChannel, marker: str, embed: discord.Embed) -> None:
        try:
            async for message in channel.history(limit=35):
                if not self.bot.user or message.author.id != self.bot.user.id:
                    continue
                for current in message.embeds:
                    footer = getattr(current.footer, "text", None) or ""
                    if marker in footer:
                        return
        except discord.HTTPException:
            pass
        await channel.send(embed=embed)

    def _rules_embed(self, guild: discord.Guild) -> discord.Embed:
        embed = discord.Embed(
            title="Règlement officiel SentriX",
            description=(
                f"Bienvenue sur **{guild.name}**. Cet espace est consacré à SentriX, son support, "
                "son développement et sa communauté. En restant sur le serveur, tu acceptes les règles ci-dessous."
            ),
            colour=0x17181C,
        )
        embed.add_field(
            name="1. Respect et comportement",
            value="Respecte les membres et l'équipe. Harcèlement, insultes répétées, menaces, discrimination et provocation volontaire sont interdits.",
            inline=False,
        )
        embed.add_field(
            name="2. Spam et publicité",
            value="Pas de spam, flood, mass-mentions, chaînes de messages, publicité sauvage ou invitations Discord sans autorisation.",
            inline=False,
        )
        embed.add_field(
            name="3. Sécurité",
            value="Scam, phishing, liens malveillants, raids, tentatives de vol de compte, malware et contournement des protections SentriX entraînent une sanction immédiate.",
            inline=False,
        )
        embed.add_field(
            name="4. Contenu",
            value="Aucun contenu illégal, choquant, NSFW, haineux ou destiné à mettre les autres membres en danger. Garde les salons lisibles et adaptés à leur sujet.",
            inline=False,
        )
        embed.add_field(
            name="5. Utilisation de SentriX",
            value="N'abuse pas de l'IA, des mini-jeux, tickets ou commandes. N'essaie pas de provoquer volontairement des erreurs, de contourner les limites ou d'exploiter le bot.",
            inline=False,
        )
        embed.add_field(
            name="6. Support et tickets",
            value="Un ticket = une demande claire. Donne les informations utiles, évite les pings répétés et respecte le membre du support qui prend ta demande en charge.",
            inline=False,
        )
        embed.add_field(
            name="7. Vie privée",
            value="Ne publie pas de mots de passe, tokens, clés API, adresses privées ou informations personnelles sensibles. Le staff ne te demandera jamais ton mot de passe.",
            inline=False,
        )
        embed.add_field(
            name="8. Staff et décisions",
            value="Les décisions du staff doivent être respectées. En cas de désaccord, utilise le support plutôt que de créer un conflit dans les salons publics.",
            inline=False,
        )
        embed.add_field(
            name="9. Sanctions",
            value="Selon la gravité : rappel, avertissement, timeout, exclusion, bannissement ou blacklist de certaines fonctions SentriX. Les récidives aggravent la sanction.",
            inline=False,
        )
        embed.add_field(
            name="10. Bon sens",
            value="Une situation non écrite ici peut quand même être modérée si elle nuit clairement à la sécurité, au fonctionnement du serveur ou aux autres membres.",
            inline=False,
        )
        embed.set_footer(text="[SENTRIX-RULES-V3] • SentriX • Règlement officiel")
        return embed

    async def _configure_logs(self, guild: discord.Guild, channels: dict[str, discord.TextChannel]) -> None:
        for log_type, channel in channels.items():
            try:
                await log_service.set_log_channel(self.bot, guild.id, log_type, channel.id)
                await log_service.set_log_enabled(self.bot, guild.id, log_type, True)
            except Exception:
                logger.exception("Activation du log %s impossible guild=%s", log_type, guild.id)

    async def _configure_database(
        self,
        guild: discord.Guild,
        roles: dict[str, discord.Role],
        channels: dict[str, discord.TextChannel],
        tickets_category: discord.CategoryChannel,
    ) -> None:
        await self.bot.db.ensure_guild(guild.id)
        await self.bot.db.execute(
            "UPDATE guild_config SET welcome_channel=?,welcome_message=?,goodbye_channel=?,"
            "goodbye_message=?,rules_channel=?,announce_channel=?,suggest_channel=?,"
            "bot_commands_channel=?,ticket_category=?,ticket_log_channel=?,log_channel=?,"
            "log_messages=?,log_members=?,log_voice=?,log_roles=?,log_server=?,"
            "log_automod=?,log_moderation=?,error_channel=?,report_channel=?,mod_role=?,"
            "admin_role=?,security_level=? WHERE guild_id=?",
            (
                channels["welcome"].id,
                "Bienvenue {member} sur {server}. Lis le règlement puis viens découvrir SentriX dans le salon IA.",
                channels["goodbye"].id,
                "{member} a quitté {server}.",
                channels["rules"].id,
                channels["announcements"].id,
                channels["suggestions"].id,
                channels["sentrix_chat"].id,
                tickets_category.id,
                channels["log_tickets"].id,
                channels["log_server"].id,
                channels["log_messages"].id,
                channels["log_members"].id,
                channels["log_voice"].id,
                channels["log_roles"].id,
                channels["log_server"].id,
                channels["log_security"].id,
                channels["log_moderation"].id,
                channels["log_security"].id,
                channels["reports"].id,
                roles["Staff SentriX"].id,
                roles["Owner SentriX"].id,
                "moyen",
                guild.id,
            ),
        )
        for field in CORE_AUTOMOD:
            try:
                await self.bot.db.set_automod(guild.id, field, 1)
            except Exception:
                logger.warning("AutoMod %s non activé", field, exc_info=True)

        await self._configure_logs(guild, {
            "messages": channels["log_messages"],
            "members": channels["log_members"],
            "roles": channels["log_roles"],
            "server": channels["log_server"],
            "voice": channels["log_voice"],
            "moderation": channels["log_moderation"],
            "tickets": channels["log_tickets"],
            "automod": channels["log_security"],
        })

    async def _ticket_panel(
        self, guild, panel_channel, tickets_category, staff_role, logs_channel
    ) -> bool:
        cog = self.bot.get_cog("Tickets")
        if cog is None:
            return False
        try:
            panel = await cog.get_panel_by_name(guild.id, "Support SentriX")
            panel_id = int(panel["id"]) if panel else await cog.create_panel(guild.id, "Support SentriX")
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET title=?,description=?,channel_id=?,style=?,"
                "max_per_member=?,enabled=1 WHERE id=?",
                (
                    "Support SentriX",
                    "Besoin d'aide, un bug à signaler ou une question ? Choisis le bouton ci-dessous.",
                    panel_channel.id,
                    "button",
                    1,
                    panel_id,
                ),
            )
            ticket_type = await cog.get_type_by_name(guild.id, "Support SentriX")
            type_id = int(ticket_type["id"]) if ticket_type else await cog.add_type(
                guild.id, panel_id, "Support SentriX"
            )
            await self.bot.db.execute(
                "UPDATE ticket_types SET panel_id=?,description=?,emoji=NULL,button_label=?,"
                "staff_role_id=?,category_id=?,log_channel_id=?,mention_staff=1,max_per_member=1,"
                "name_format=?,open_message=? WHERE id=?",
                (
                    panel_id,
                    "Support, bug, question ou problème lié à SentriX.",
                    "Ouvrir un ticket",
                    staff_role.id,
                    tickets_category.id,
                    logs_channel.id,
                    "ticket-{pseudo}",
                    "Explique clairement ta demande. Un membre du support SentriX prendra le relais.",
                    type_id,
                ),
            )
            panel = await cog.get_panel(panel_id)
            types = await cog.get_panel_types(panel_id)
            if not panel or not types:
                return False
            if panel["message_id"]:
                try:
                    old = await panel_channel.fetch_message(int(panel["message_id"]))
                    await old.delete()
                except discord.HTTPException:
                    pass
            from .tickets import TicketPanelView
            message = await panel_channel.send(
                embed=cog.build_panel_embed(panel), view=TicketPanelView(panel, types)
            )
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET message_id=?,channel_id=? WHERE id=?",
                (message.id, panel_channel.id, panel_id),
            )
            return True
        except Exception:
            logger.exception("Panel Tickets V3 impossible guild=%s", guild.id)
            return False

    async def _build(self, guild: discord.Guild):
        me = guild.me
        if me is None:
            raise RuntimeError("SentriX n'est pas présent comme membre du serveur.")

        roles: dict[str, discord.Role] = {}
        roles_created = 0
        for name, colour, permissions in ROLE_SPECS:
            role, created = await self._role(guild, name, colour, permissions)
            roles[name] = role
            roles_created += int(created)

        if guild.owner and roles["Owner SentriX"] not in guild.owner.roles:
            try:
                await guild.owner.add_roles(roles["Owner SentriX"], reason="Owner SentriX V3")
            except discord.HTTPException:
                pass

        default = guild.default_role
        bot_full = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_messages=True,
            read_message_history=True, connect=True, speak=True,
        )
        public = {
            default: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            me: bot_full,
        }
        readonly = {
            default: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            me: bot_full,
        }
        for role in roles.values():
            readonly[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        team_roles = [
            roles["Owner SentriX"], roles["Lead Developer"], roles["Developer SentriX"],
            roles["Security Engineer"], roles["Support Lead"], roles["Support Specialist"],
            roles["Community Manager"], roles["QA Tester"], roles["Staff SentriX"],
        ]
        staff_only = {default: discord.PermissionOverwrite(view_channel=False), me: bot_full}
        for role in team_roles:
            staff_only[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
            )
        logs_only = dict(staff_only)
        ticket_private = {default: discord.PermissionOverwrite(view_channel=False), me: bot_full}
        for role_name in ("Owner SentriX", "Support Lead", "Support Specialist", "Staff SentriX"):
            ticket_private[roles[role_name]] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
            )

        official, c1 = await self._category(
            guild, "📌・SENTRIX OFFICIEL", {"SENTRIX — OFFICIEL", "SENTRIX OFFICIEL"}
        )
        community, c2 = await self._category(
            guild, "💬・SENTRIX COMMUNAUTÉ", {"SENTRIX — COMMUNAUTÉ", "SENTRIX COMMUNAUTÉ"}
        )
        support, c3 = await self._category(
            guild, "🧩・SENTRIX SUPPORT", {"SENTRIX — SUPPORT", "SENTRIX SUPPORT"}
        )
        team, c4 = await self._category(
            guild, "🔒・SENTRIX ÉQUIPE", {"SENTRIX — STAFF", "SENTRIX STAFF"}, staff_only
        )
        logs_category, c5 = await self._category(
            guild, "📊・SENTRIX LOGS", {"SENTRIX LOGS"}, logs_only
        )
        tickets_category, c6 = await self._category(
            guild, "🎫・SENTRIX TICKETS", {"SENTRIX — TICKETS", "SENTRIX TICKETS"}, ticket_private
        )

        channels_created = 0
        channels: dict[str, discord.TextChannel] = {}

        async def text(key, category, desired, aliases, topic, perms):
            nonlocal channels_created
            channel, created = await self._text(guild, category, desired, set(aliases), topic, perms)
            channels[key] = channel
            channels_created += int(created)
            return channel

        await text("welcome", official, "👋・bienvenue", ["bienvenue"], "Accueil officiel SentriX.", readonly)
        await text("rules", official, "📜・reglement", ["règlement", "reglement"], "Règlement officiel SentriX.", readonly)
        await text("announcements", official, "📢・annonces-sentrix", ["annonces-sentrix"], "Annonces et nouveautés officielles.", readonly)
        await text("status", official, "🟢・statut-sentrix", ["statut-sentrix"], "État de SentriX, incidents et maintenances.", readonly)
        await text("goodbye", official, "🚪・departs", ["départs", "departs"], "Journal public des départs.", readonly)

        await text("general", community, "💬・general", ["général", "general"], "Discussion principale de la communauté SentriX.", public)
        await text("sentrix_chat", community, "🤖・sentrix-chat", ["sentrix-chat"], "Parle directement avec SentriX sans commande.", public)
        await text("suggestions", community, "💡・suggestions", ["suggestions"], "Idées et retours pour améliorer SentriX.", public)
        await text("animations", community, "🎉・animations", ["animations"], "Animations, jeux et rendez-vous communautaires.", public)
        await text("beta", community, "🧪・beta-feedback", ["beta-feedback"], "Retours sur les nouvelles fonctions SentriX.", public)

        await text("faq", support, "📚・faq", ["faq"], "Réponses aux questions fréquentes.", readonly)
        await text("ticket_panel", support, "🎫・ouvrir-un-ticket", ["ouvrir-un-ticket"], "Ouvre une demande privée auprès du support SentriX.", readonly)
        await text("bug_reports", support, "🐛・signaler-un-bug", ["signaler-un-bug"], "Informations à fournir avant de signaler un bug.", readonly)

        await text("team_hq", team, "🧭・staff-hq", ["staff"], "Coordination de l'équipe SentriX.", staff_only)
        await text("dev", team, "💻・dev-sentrix", ["dev-sentrix"], "Développement, architecture et versions.", staff_only)
        await text("security", team, "🛡️・security-sentrix", ["security-sentrix"], "Incidents, sécurité et protections.", staff_only)
        await text("support_staff", team, "🎫・support-staff", ["support-staff"], "Coordination support et tickets.", staff_only)
        await text("qa", team, "🧪・qa-tests", ["qa-tests"], "Tests et validation avant production.", staff_only)
        await text("reports", team, "📋・reports", ["reports"], "Signalements à examiner par l'équipe.", staff_only)

        for key, desired, aliases, topic in (
            ("log_messages", "💬・logs-messages", ["logs-messages"], "Messages supprimés et modifiés."),
            ("log_members", "👥・logs-membres", ["logs-membres", "logs-members"], "Arrivées, départs et changements membres."),
            ("log_roles", "🎭・logs-roles", ["logs-roles"], "Création, suppression et modification des rôles."),
            ("log_server", "🧱・logs-serveur", ["logs-serveur", "logs-server"], "Salons, catégories et changements serveur."),
            ("log_voice", "🔊・logs-vocal", ["logs-vocal", "logs-voice"], "Connexions et mouvements vocaux."),
            ("log_moderation", "🛡️・logs-moderation", ["logs-moderation"], "Warns, mutes, kicks, bans et actions staff."),
            ("log_tickets", "🎫・logs-tickets", ["logs-tickets", "logs-sentrix"], "Ouvertures, fermetures et actions tickets."),
            ("log_security", "🔐・logs-securite", ["logs-securite", "logs-security"], "AutoMod, anti-raid, anti-scam et incidents sécurité."),
        ):
            await text(key, logs_category, desired, aliases, topic, logs_only)

        voice_created = 0
        for desired, aliases, category, perms in (
            ("🔊 Communauté SentriX", {"Communauté SentriX"}, community, public),
            ("🎙️ Animation SentriX", {"Animation SentriX"}, community, public),
            ("🔒 Réunion Équipe", {"Staff SentriX"}, team, staff_only),
        ):
            _, created = await self._voice(guild, category, desired, aliases, perms)
            voice_created += int(created)

        # Petit message d'orientation dans tous les salons non-log.
        guides = {
            "welcome": "Bienvenue dans l'espace officiel SentriX. Commence par lire le règlement, puis découvre le salon IA et la communauté.",
            "announcements": "Toutes les nouveautés importantes de SentriX seront publiées ici : fonctions, changements et annonces officielles.",
            "status": "Ce salon indique l'état de SentriX, les maintenances prévues et les incidents importants.",
            "goodbye": "Les messages de départ automatiques de la communauté apparaissent ici.",
            "general": "Salon principal de la communauté SentriX. Discute librement tout en respectant le règlement.",
            "sentrix_chat": "Écris simplement ton message ici : SentriX te répond directement, sans `+ai` et sans devoir le mentionner.",
            "suggestions": "Propose une idée précise pour améliorer SentriX. Les meilleures suggestions peuvent être reprises par l'équipe.",
            "animations": "Les animations, jeux communautaires et rendez-vous SentriX seront organisés ici.",
            "beta": "Teste les nouveautés et explique clairement ce qui fonctionne, ce qui bug et ce qui pourrait être amélioré.",
            "faq": "Avant d'ouvrir un ticket, vérifie ici les réponses aux problèmes et questions les plus courants.",
            "bug_reports": "Pour un bug : indique la commande utilisée, le résultat obtenu, le résultat attendu et ajoute une capture si possible.",
            "team_hq": "Coordination générale de l'équipe SentriX : priorités, décisions et suivi interne.",
            "dev": "Espace technique réservé au développement SentriX, aux versions et à l'architecture.",
            "security": "Incidents de sécurité, protections AutoMod, anti-raid et analyses sensibles.",
            "support_staff": "Organisation du support, suivi des tickets difficiles et procédures d'assistance.",
            "qa": "Validation des changements avant production : tests, régressions et comptes rendus QA.",
            "reports": "Les signalements nécessitant une vérification du staff sont centralisés ici.",
        }
        for key, text_value in guides.items():
            await self._seed_text(channels[key], text_value)

        await self._seed_embed(channels["rules"], "[SENTRIX-RULES-V3]", self._rules_embed(guild))

        log_descriptions = {
            "log_messages": "Ce salon reçoit automatiquement les logs de messages supprimés ou modifiés.",
            "log_members": "Ce salon reçoit automatiquement les arrivées, départs et changements importants des membres.",
            "log_roles": "Ce salon reçoit automatiquement les créations, suppressions et modifications de rôles.",
            "log_server": "Ce salon reçoit automatiquement les changements de salons et de structure du serveur.",
            "log_voice": "Ce salon reçoit automatiquement les événements vocaux suivis par SentriX.",
            "log_moderation": "Ce salon reçoit automatiquement les sanctions et actions de modération.",
            "log_tickets": "Ce salon reçoit automatiquement l'activité importante des tickets SentriX.",
            "log_security": "Ce salon reçoit automatiquement les événements AutoMod et les alertes de sécurité suivies par SentriX.",
        }
        for key, text_value in log_descriptions.items():
            await self._seed_text(channels[key], text_value)

        await self._configure_database(guild, roles, channels, tickets_category)
        ticket_ready = await self._ticket_panel(
            guild,
            channels["ticket_panel"],
            tickets_category,
            roles["Support Specialist"],
            channels["log_tickets"],
        )

        return {
            "roles_created": roles_created,
            "categories_created": sum(int(x) for x in (c1, c2, c3, c4, c5, c6)),
            "channels_created": channels_created + voice_created,
            "ticket_ready": ticket_ready,
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        name = getattr(message.channel, "name", "").casefold()
        if not name.endswith("sentrix-chat"):
            return
        content = (message.content or "").strip()
        if not content:
            return
        prefix = self.bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX) \
            if hasattr(self.bot, "prefix_cache") else config.DEFAULT_PREFIX
        if content.startswith(prefix):
            return
        if self.bot.user and self.bot.user in message.mentions:
            return
        lowered = content.casefold().lstrip()
        if lowered.startswith(("sentrix ", "sentrix,", "sentrix:", "sentri ", "snetri ")):
            return

        ai_cog = next((c for c in self.bot.cogs.values() if hasattr(c, "send_sentrix_reply")), None)
        if ai_cog is None:
            return
        try:
            async with message.channel.typing():
                await ai_cog.send_sentrix_reply(
                    message.channel, message.author, content, reply_to=message
                )
        except Exception:
            logger.exception("Réponse automatique sentrix-chat impossible guild=%s", message.guild.id)

    @commands.group(name="create", invoke_without_command=True)
    @checks.is_owner_or_admin_for("configuration")
    async def create(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send("Utilise `+create sentrix` pour installer l'espace officiel SentriX.")

    @create.command(name="sentrix")
    @checks.is_owner_or_admin_for("configuration")
    async def create_sentrix(self, ctx: commands.Context):
        guild = ctx.guild
        if guild is None:
            return await ctx.send("Cette commande doit être utilisée dans un serveur Discord.")
        if guild.me is None or not guild.me.guild_permissions.administrator:
            return await ctx.send("SentriX doit avoir Administrateur pendant l'installation.")

        lock = self._lock_for(guild.id)
        if lock.locked():
            return await ctx.send("Une installation SentriX est déjà en cours.")

        async with lock:
            previous = await self._installation(guild.id)
            if previous and str(previous["template_key"] or "") == TEMPLATE_KEY:
                return await ctx.send("Le serveur SentriX V3 est déjà installé ici.")

            progress = await ctx.send("Mise en place du serveur officiel SentriX V3 en cours…")
            try:
                result = await self._build(guild)
                await self._mark_installed(guild.id, ctx.author.id)
                ticket_text = "prêt" if result["ticket_ready"] else "à vérifier avec +ticketsetup"
                await progress.edit(
                    content=(
                        "SentriX V3 installé : identité professionnelle, rôles spécialisés, "
                        "salons avec emojis, règlement complet, logs automatiques séparés et "
                        f"support {ticket_text}. Nouveaux éléments sur cette exécution : "
                        f"{result['roles_created']} rôle(s), {result['categories_created']} catégorie(s), "
                        f"{result['channels_created']} salon(s)."
                    ),
                    embed=None,
                    view=None,
                )
            except discord.Forbidden:
                logger.warning("+create sentrix V3 refusé guild=%s", guild.id, exc_info=True)
                await progress.edit(
                    content="Installation arrêtée : une permission Discord manque. Tu peux relancer la commande après correction.",
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                logger.warning("+create sentrix V3 HTTP guild=%s", guild.id, exc_info=True)
                await progress.edit(
                    content="Discord a interrompu l'installation. Les éléments déjà créés seront réutilisés au prochain essai.",
                    embed=None,
                    view=None,
                )
            except Exception:
                logger.exception("Erreur +create sentrix V3 guild=%s", guild.id)
                try:
                    await progress.edit(
                        content="Installation interrompue par une erreur technique. Aucun verrou V3 définitif n'a été posé.",
                        embed=None,
                        view=None,
                    )
                except discord.HTTPException:
                    pass


async def setup(bot: commands.Bot) -> None:
    # Supprime proprement l'ancienne V2 (commandes + listener sentrix-chat) pour ne jamais
    # avoir deux +create ou deux réponses IA en parallèle.
    old = bot.get_cog("CreateSentrix")
    if old is not None:
        await bot.remove_cog("CreateSentrix")
    existing = bot.get_command("create")
    if existing is not None:
        bot.remove_command("create")
    await bot.add_cog(CreateSentriXV3(bot))
