"""Créateur du serveur officiel SentriX : +create sentrix.

Version v3 : structure professionnelle compacte, salons nommés avec emojis, rôles
spécialisés, messages d'introduction, règlement complet, tickets et logs automatiques.
La commande est idempotente : l'ancienne installation v2 est mise à niveau sans créer
inutilement de doublons.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

import config
from utils import checks

logger = logging.getLogger("bot.create-sentrix")
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


class CreateSentrix(commands.Cog, name="CreateSentrix"):
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

    @staticmethod
    def _find_named(items, name: str, aliases: tuple[str, ...] = ()):
        for candidate in (name, *aliases):
            found = discord.utils.get(items, name=candidate)
            if found is not None:
                return found
        return None

    async def _role(
        self,
        guild: discord.Guild,
        name: str,
        color: discord.Color,
        permissions: discord.Permissions,
        *,
        aliases: tuple[str, ...] = (),
        hoist: bool = True,
    ):
        role = self._find_named(guild.roles, name, aliases)
        if role:
            try:
                await role.edit(
                    name=name,
                    color=color,
                    permissions=permissions,
                    hoist=hoist,
                    mentionable=False,
                    reason="Configuration officielle SentriX v3",
                )
            except discord.HTTPException:
                pass
            return role, False
        role = await guild.create_role(
            name=name,
            color=color,
            permissions=permissions,
            hoist=hoist,
            mentionable=False,
            reason="Configuration officielle SentriX v3",
        )
        return role, True

    async def _category(
        self,
        guild: discord.Guild,
        name: str,
        *,
        aliases: tuple[str, ...] = (),
        overwrites=None,
    ):
        category = self._find_named(guild.categories, name, aliases)
        if category:
            try:
                await category.edit(
                    name=name,
                    overwrites=overwrites if overwrites is not None else category.overwrites,
                    reason="Configuration officielle SentriX v3",
                )
            except discord.HTTPException:
                pass
            return category, False
        category = await guild.create_category(
            name,
            overwrites=overwrites or {},
            reason="Configuration officielle SentriX v3",
        )
        return category, True

    async def _text(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        name: str,
        topic: str,
        overwrites,
        *,
        aliases: tuple[str, ...] = (),
    ):
        channel = self._find_named(guild.text_channels, name, aliases)
        if channel:
            try:
                await channel.edit(
                    name=name,
                    category=category,
                    topic=topic[:1024],
                    overwrites=overwrites,
                    reason="Configuration officielle SentriX v3",
                )
            except discord.HTTPException:
                pass
            return channel, False
        channel = await guild.create_text_channel(
            name,
            category=category,
            topic=topic[:1024],
            overwrites=overwrites,
            reason="Configuration officielle SentriX v3",
        )
        return channel, True

    async def _voice(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        name: str,
        overwrites,
        *,
        aliases: tuple[str, ...] = (),
    ):
        channel = self._find_named(guild.voice_channels, name, aliases)
        if channel:
            try:
                await channel.edit(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    reason="Configuration officielle SentriX v3",
                )
            except discord.HTTPException:
                pass
            return channel, False
        channel = await guild.create_voice_channel(
            name,
            category=category,
            overwrites=overwrites,
            reason="Configuration officielle SentriX v3",
        )
        return channel, True

    async def _seed_embed(
        self,
        channel: discord.TextChannel,
        title: str,
        description: str,
        *,
        colour: int = 0x7C5CFC,
        fields: list[tuple[str, str, bool]] | None = None,
        footer: str = "SentriX • Serveur officiel",
    ) -> None:
        embed = discord.Embed(
            title=title,
            description=description,
            colour=colour,
            timestamp=discord.utils.utcnow(),
        )
        for field_name, field_value, inline in fields or []:
            embed.add_field(name=field_name, value=field_value, inline=inline)
        embed.set_footer(text=footer)

        existing = None
        legacy_messages = []
        try:
            async for message in channel.history(limit=40):
                if not self.bot.user or message.author.id != self.bot.user.id:
                    continue
                if any(item.title == title for item in message.embeds):
                    existing = message
                    break
                if (message.content or "").startswith("[SENTRIX-"):
                    legacy_messages.append(message)
        except discord.HTTPException:
            pass

        for message in legacy_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        if existing is not None:
            try:
                await existing.edit(content=None, embed=embed)
                return
            except discord.HTTPException:
                pass
        await channel.send(embed=embed)

    async def _seed_rules(self, channel: discord.TextChannel) -> None:
        fields = [
            (
                "1 • Respect et comportement",
                "Respecte les membres, le staff et les développeurs. Harcèlement, menaces, insultes graves, discriminations et provocations répétées sont interdits.",
                False,
            ),
            (
                "2 • Spam, flood et mentions",
                "Pas de spam, flood, chaînes de messages, caps abusives, réactions répétées ni mentions inutiles de membres, rôles ou staff.",
                False,
            ),
            (
                "3 • Publicité et liens",
                "Aucune publicité sauvage, invitation Discord, autopromotion ou lien douteux. Les liens de phishing, grabbers et redirections trompeuses entraînent une sanction immédiate.",
                False,
            ),
            (
                "4 • Contenu autorisé",
                "Pas de contenu NSFW, choquant, illégal, haineux, dangereux ou volontairement malveillant. Les fichiers et médias doivent rester adaptés à la communauté.",
                False,
            ),
            (
                "5 • Arnaques et sécurité",
                "Scam, usurpation, faux giveaways, vol de compte, tentative de récupération de token/mot de passe et contournement des protections SentriX sont interdits.",
                False,
            ),
            (
                "6 • Vie privée",
                "Ne publie pas d'informations privées sur une autre personne. Doxxing, divulgation de données personnelles et menaces de leak sont strictement interdits.",
                False,
            ),
            (
                "7 • Utilisation de SentriX",
                "Utilise les commandes et #🤖・sentrix-chat normalement. Pas de spam de commandes, tentative de surcharge, abus de l'IA ou exploitation volontaire d'un bug.",
                False,
            ),
            (
                "8 • Support et tickets",
                "Ouvre un ticket uniquement pour une vraie demande. Explique le problème clairement, évite les doubles tickets et respecte l'équipe support.",
                False,
            ),
            (
                "9 • Sanctions et contournement",
                "Contourner un mute, ban, blacklist ou une restriction avec un autre compte peut aggraver la sanction. Les décisions peuvent être contestées proprement via le support.",
                False,
            ),
            (
                "10 • Discord et bon sens",
                "Les Conditions d'utilisation et règles de Discord restent applicables. Le staff peut intervenir face à un comportement nuisible même s'il n'est pas décrit mot pour mot ici.",
                False,
            ),
        ]
        await self._seed_embed(
            channel,
            "📜 Règlement officiel SentriX",
            "Bienvenue sur le serveur officiel de **SentriX**. Le but est de garder un espace propre, professionnel et utile pour les utilisateurs du bot.\n\nEn restant sur le serveur, tu acceptes les règles ci-dessous.",
            colour=0x7C5CFC,
            fields=fields,
            footer="SentriX • Règlement officiel • Dernière mise à jour automatique",
        )

    async def _configure_database(
        self,
        guild: discord.Guild,
        *,
        owner_role: discord.Role,
        staff_role: discord.Role,
        welcome: discord.TextChannel,
        goodbye: discord.TextChannel,
        rules: discord.TextChannel,
        announcements: discord.TextChannel,
        suggestions: discord.TextChannel,
        sentrix_chat: discord.TextChannel,
        tickets_category: discord.CategoryChannel,
        reports: discord.TextChannel,
        log_channels: dict[str, discord.TextChannel],
    ) -> None:
        await self.bot.db.ensure_guild(guild.id)

        primary_log = log_channels["server"]
        settings = {
            "welcome_channel": welcome.id,
            "welcome_message": "Bienvenue {member} sur {server}. Lis le règlement puis découvre SentriX dans le salon IA.",
            "goodbye_channel": goodbye.id,
            "goodbye_message": "{member} a quitté {server}.",
            "rules_channel": rules.id,
            "announce_channel": announcements.id,
            "suggest_channel": suggestions.id,
            "bot_commands_channel": sentrix_chat.id,
            "ticket_category": tickets_category.id,
            "ticket_log_channel": log_channels["tickets"].id,
            "log_channel": primary_log.id,
            "log_messages": log_channels["messages"].id,
            "log_members": log_channels["members"].id,
            "log_voice": log_channels["voice"].id,
            "log_roles": log_channels["roles"].id,
            "log_server": log_channels["server"].id,
            "log_automod": log_channels["automod"].id,
            "log_moderation": log_channels["moderation"].id,
            "error_channel": primary_log.id,
            "report_channel": reports.id,
            "mod_role": staff_role.id,
            "admin_role": owner_role.id,
            "security_level": "moyen",
        }
        for column, value in settings.items():
            await self.bot.db.execute(
                f"UPDATE guild_config SET {column}=? WHERE guild_id=?",
                (value, guild.id),
            )

        for field in CORE_AUTOMOD:
            try:
                await self.bot.db.set_automod(guild.id, field, 1)
            except Exception:
                logger.warning(
                    "AutoMod %s non activé pendant +create sentrix",
                    field,
                    exc_info=True,
                )

        from utils import log_service

        for log_type, channel in log_channels.items():
            try:
                await log_service.set_log_channel(self.bot, guild.id, log_type, channel.id)
                await log_service.set_log_enabled(self.bot, guild.id, log_type, True)
            except Exception:
                logger.warning(
                    "Log automatique %s non configuré sur %s",
                    log_type,
                    guild.id,
                    exc_info=True,
                )

    async def _ticket_panel(
        self,
        guild: discord.Guild,
        panel_channel: discord.TextChannel,
        tickets_category: discord.CategoryChannel,
        support_role: discord.Role,
        logs_channel: discord.TextChannel,
    ) -> bool:
        """Crée ou met à jour le vrai panel Tickets v2."""
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
                    "🎫 Support officiel SentriX",
                    "Un bug, une question, un problème de configuration ou un signalement privé ? Ouvre un ticket : l'équipe support te répondra dans un salon privé.",
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
                "UPDATE ticket_types SET panel_id=?,description=?,emoji=?,button_label=?,"
                "staff_role_id=?,category_id=?,log_channel_id=?,mention_staff=1,max_per_member=1,"
                "name_format=?,open_message=? WHERE id=?",
                (
                    panel_id,
                    "Support, bug, configuration, question ou signalement lié à SentriX.",
                    "🎫",
                    "Ouvrir un ticket",
                    support_role.id,
                    tickets_category.id,
                    logs_channel.id,
                    "ticket-{pseudo}",
                    "Décris précisément ta demande. Un membre du support SentriX va prendre le relais.",
                    type_id,
                ),
            )

            panel = await cog.get_panel(panel_id)
            types = await cog.get_panel_types(panel_id)
            if not panel or not types:
                return False

            old_message_id = panel["message_id"]
            if old_message_id:
                try:
                    old = await panel_channel.fetch_message(int(old_message_id))
                    await old.delete()
                except discord.HTTPException:
                    pass

            from .tickets import TicketPanelView

            message = await panel_channel.send(
                embed=cog.build_panel_embed(panel),
                view=TicketPanelView(panel, types),
            )
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET message_id=?,channel_id=? WHERE id=?",
                (message.id, panel_channel.id, panel_id),
            )
            return True
        except Exception:
            logger.exception("Panel Support SentriX impossible guild=%s", guild.id)
            return False

    async def _build(self, guild: discord.Guild):
        default = guild.default_role
        me = guild.me
        if me is None:
            raise RuntimeError("SentriX n'est pas présent comme membre du serveur.")

        owner_role, r1 = await self._role(
            guild,
            "Owner SentriX",
            discord.Color.from_rgb(108, 82, 230),
            discord.Permissions(administrator=True),
        )
        lead_dev_role, r2 = await self._role(
            guild,
            "Lead Developer",
            discord.Color.from_rgb(92, 103, 255),
            discord.Permissions(
                view_audit_log=True,
                manage_guild=True,
                manage_roles=True,
                manage_channels=True,
                manage_webhooks=True,
                manage_messages=True,
                manage_threads=True,
                manage_emojis_and_stickers=True,
            ),
        )
        dev_role, r3 = await self._role(
            guild,
            "Developer SentriX",
            discord.Color.from_rgb(74, 104, 190),
            discord.Permissions(
                view_audit_log=True,
                manage_channels=True,
                manage_webhooks=True,
                manage_messages=True,
                manage_threads=True,
            ),
            aliases=("Dev SentriX",),
        )
        security_role, r4 = await self._role(
            guild,
            "Security Engineer",
            discord.Color.from_rgb(210, 70, 85),
            discord.Permissions(
                view_audit_log=True,
                kick_members=True,
                ban_members=True,
                moderate_members=True,
                manage_messages=True,
                manage_threads=True,
                manage_nicknames=True,
            ),
        )
        support_role, r5 = await self._role(
            guild,
            "Support Specialist",
            discord.Color.from_rgb(46, 180, 170),
            discord.Permissions(
                moderate_members=True,
                manage_messages=True,
                manage_threads=True,
                manage_nicknames=True,
                move_members=True,
                mute_members=True,
            ),
        )
        community_role, r6 = await self._role(
            guild,
            "Community Manager",
            discord.Color.from_rgb(220, 92, 170),
            discord.Permissions(
                manage_messages=True,
                manage_threads=True,
                manage_events=True,
                manage_nicknames=True,
            ),
        )
        qa_role, r7 = await self._role(
            guild,
            "QA Tester",
            discord.Color.from_rgb(130, 130, 160),
            discord.Permissions.none(),
        )
        staff_role, r8 = await self._role(
            guild,
            "Staff SentriX",
            discord.Color.from_rgb(95, 110, 145),
            discord.Permissions(
                moderate_members=True,
                manage_messages=True,
                manage_threads=True,
                manage_nicknames=True,
                move_members=True,
                mute_members=True,
            ),
        )

        if guild.owner and owner_role not in guild.owner.roles:
            try:
                await guild.owner.add_roles(owner_role, reason="Owner du serveur officiel SentriX")
            except discord.HTTPException:
                pass

        staff_roles = [
            owner_role,
            lead_dev_role,
            dev_role,
            security_role,
            support_role,
            community_role,
            qa_role,
            staff_role,
        ]
        developer_roles = [owner_role, lead_dev_role, dev_role, qa_role]

        bot_full = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            manage_channels=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            connect=True,
            speak=True,
        )

        readonly = {
            default: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
            ),
            me: bot_full,
        }
        for role in staff_roles:
            readonly[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        public = {
            default: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
            me: bot_full,
        }

        staff_only = {
            default: discord.PermissionOverwrite(view_channel=False),
            me: bot_full,
        }
        for role in staff_roles:
            staff_only[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        dev_only = {
            default: discord.PermissionOverwrite(view_channel=False),
            me: bot_full,
        }
        for role in developer_roles:
            dev_only[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        logs_only = {
            default: discord.PermissionOverwrite(view_channel=False),
            me: bot_full,
        }
        for role in staff_roles:
            logs_only[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
            )
        logs_only[owner_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
        logs_only[lead_dev_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )

        ticket_private = {
            default: discord.PermissionOverwrite(view_channel=False),
            me: bot_full,
        }
        for role in (owner_role, lead_dev_role, dev_role, security_role, support_role, staff_role):
            ticket_private[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        official, c1 = await self._category(
            guild,
            "📡 SENTRIX — OFFICIEL",
            aliases=("SENTRIX — OFFICIEL",),
        )
        community, c2 = await self._category(
            guild,
            "💬 SENTRIX — COMMUNAUTÉ",
            aliases=("SENTRIX — COMMUNAUTÉ",),
        )
        support, c3 = await self._category(
            guild,
            "🆘 SENTRIX — SUPPORT",
            aliases=("SENTRIX — SUPPORT",),
        )
        staff, c4 = await self._category(
            guild,
            "🔒 SENTRIX — STAFF",
            aliases=("SENTRIX — STAFF",),
            overwrites=staff_only,
        )
        logs_category, c5 = await self._category(
            guild,
            "📊 SENTRIX — LOGS",
            aliases=("SENTRIX — LOGS",),
            overwrites=logs_only,
        )
        tickets, c6 = await self._category(
            guild,
            "🎫 SENTRIX — TICKETS",
            aliases=("SENTRIX — TICKETS",),
            overwrites=ticket_private,
        )

        created_channels = 0

        async def text(category, name, topic, perms, aliases=()):
            nonlocal created_channels
            channel, is_new = await self._text(
                guild,
                category,
                name,
                topic,
                perms,
                aliases=aliases,
            )
            created_channels += int(is_new)
            return channel

        welcome = await text(
            official,
            "👋・bienvenue",
            "Accueil officiel des nouveaux membres SentriX.",
            readonly,
            ("bienvenue",),
        )
        rules = await text(
            official,
            "📜・règlement",
            "Règlement officiel et règles de sécurité de la communauté SentriX.",
            readonly,
            ("règlement",),
        )
        announcements = await text(
            official,
            "📢・annonces-sentrix",
            "Nouveautés, versions et annonces officielles SentriX.",
            readonly,
            ("annonces-sentrix",),
        )
        status = await text(
            official,
            "🟢・statut-sentrix",
            "État du bot, maintenances, incidents et disponibilité des services.",
            readonly,
            ("statut-sentrix",),
        )
        goodbye = await text(
            official,
            "👋・départs",
            "Journal public léger des départs de la communauté.",
            readonly,
            ("départs",),
        )

        general = await text(
            community,
            "💬・général",
            "Discussion principale de la communauté SentriX.",
            public,
            ("général",),
        )
        sentrix_chat = await text(
            community,
            "🤖・sentrix-chat",
            "Parle directement avec SentriX sans écrire +ai ni mentionner le bot.",
            public,
            ("sentrix-chat",),
        )
        suggestions = await text(
            community,
            "💡・suggestions",
            "Idées, retours produit et propositions d'amélioration.",
            public,
            ("suggestions",),
        )
        animations = await text(
            community,
            "🎉・animations",
            "Animations, rendez-vous et activités de la communauté SentriX.",
            public,
            ("animations",),
        )

        faq = await text(
            support,
            "❓・faq",
            "Réponses rapides aux questions fréquentes sur SentriX.",
            readonly,
            ("faq",),
        )
        ticket_channel = await text(
            support,
            "🎫・ouvrir-un-ticket",
            "Support privé officiel SentriX.",
            readonly,
            ("ouvrir-un-ticket",),
        )

        staff_chat = await text(
            staff,
            "🛡️・staff",
            "Coordination privée de l'équipe SentriX.",
            staff_only,
            ("staff",),
        )
        dev_channel = await text(
            staff,
            "💻・dev-sentrix",
            "Développement, versions, incidents techniques et architecture SentriX.",
            dev_only,
            ("dev-sentrix",),
        )
        qa_channel = await text(
            staff,
            "🧪・qa-tests",
            "Tests qualité, reproductions de bugs et validation avant mise en production.",
            dev_only,
            ("qa-tests",),
        )
        reports = await text(
            staff,
            "📨・reports",
            "Signalements utilisateurs et dossiers à traiter par l'équipe.",
            staff_only,
            ("reports",),
        )

        log_channels = {
            "messages": await text(
                logs_category,
                "📝・logs-messages",
                "Suppressions et modifications de messages.",
                logs_only,
                ("logs-messages",),
            ),
            "members": await text(
                logs_category,
                "👥・logs-membres",
                "Arrivées, départs et modifications de membres.",
                logs_only,
                ("logs-membres",),
            ),
            "roles": await text(
                logs_category,
                "🎭・logs-rôles",
                "Créations, suppressions et modifications de rôles.",
                logs_only,
                ("logs-rôles",),
            ),
            "server": await text(
                logs_category,
                "🏗️・logs-serveur",
                "Créations, suppressions et modifications de salons/catégories.",
                logs_only,
                ("logs-sentrix", "logs-serveur"),
            ),
            "voice": await text(
                logs_category,
                "🔊・logs-vocal",
                "Connexions, déconnexions et déplacements vocaux.",
                logs_only,
                ("logs-vocal",),
            ),
            "moderation": await text(
                logs_category,
                "🛡️・logs-modération",
                "Warns, mutes, kicks, bans et autres actions de modération.",
                logs_only,
                ("logs-modération",),
            ),
            "tickets": await text(
                logs_category,
                "🎫・logs-tickets",
                "Ouvertures, fermetures et actions importantes sur les tickets.",
                logs_only,
                ("logs-tickets",),
            ),
            "automod": await text(
                logs_category,
                "🔐・logs-sécurité",
                "AutoMod, anti-spam, anti-raid, anti-scam et protections SentriX.",
                logs_only,
                ("logs-sécurité",),
            ),
        }

        _, voice_community_new = await self._voice(
            guild,
            community,
            "🔊・Communauté SentriX",
            public,
            aliases=("Communauté SentriX",),
        )
        _, voice_staff_new = await self._voice(
            guild,
            staff,
            "🔒・Staff SentriX",
            staff_only,
            aliases=("Staff SentriX",),
        )
        created_channels += int(voice_community_new) + int(voice_staff_new)

        await self._seed_embed(
            welcome,
            "👋 Bienvenue sur SentriX",
            "Bienvenue sur le serveur officiel de **SentriX**.\n\nCommence par lire le règlement, puis passe dans **🤖・sentrix-chat** pour parler directement avec l'IA du bot.",
        )
        await self._seed_rules(rules)
        await self._seed_embed(
            announcements,
            "📢 Annonces officielles",
            "Les nouvelles versions, changements importants, maintenances planifiées et nouveautés SentriX seront publiés ici.",
        )
        await self._seed_embed(
            status,
            "🟢 Statut de SentriX",
            "Ce salon centralise l'état du bot et les incidents importants. En fonctionnement normal, aucune action n'est nécessaire.",
            colour=0x57F287,
        )
        await self._seed_embed(
            goodbye,
            "👋 Départs",
            "Les départs de la communauté peuvent être annoncés ici automatiquement.",
            colour=0x5865F2,
        )
        await self._seed_embed(
            general,
            "💬 Communauté SentriX",
            "Salon principal pour discuter avec la communauté. Garde les demandes privées et problèmes techniques pour le support.",
        )
        await self._seed_embed(
            sentrix_chat,
            "🤖 Parler avec SentriX",
            "Écris simplement ton message dans ce salon. **Pas besoin de `+ai` ni de mentionner le bot** : SentriX te répond directement.",
        )
        await self._seed_embed(
            suggestions,
            "💡 Suggestions",
            "Une idée pour améliorer le bot, le dashboard ou le serveur ? Explique-la clairement ici. Les meilleures propositions pourront être étudiées par l'équipe.",
        )
        await self._seed_embed(
            animations,
            "🎉 Animations",
            "Les animations, petits événements communautaires et rendez-vous seront organisés ici.",
        )
        await self._seed_embed(
            faq,
            "❓ FAQ SentriX",
            "**Parler à l'IA :** 🤖・sentrix-chat\n**Support privé :** 🎫・ouvrir-un-ticket\n**Nouveautés :** 📢・annonces-sentrix\n**État du bot :** 🟢・statut-sentrix",
        )
        await self._seed_embed(
            ticket_channel,
            "🎫 Support SentriX",
            "Pour un bug, une question de configuration ou un problème privé, utilise le panel ci-dessous. Un salon privé sera créé automatiquement.",
        )
        await self._seed_embed(
            staff_chat,
            "🛡️ Espace staff",
            "Coordination interne, décisions de modération et suivi opérationnel du serveur SentriX.",
            colour=0x5865F2,
        )
        await self._seed_embed(
            dev_channel,
            "💻 Développement SentriX",
            "Architecture, correctifs, déploiements, incidents techniques et suivi des versions.",
            colour=0x5865F2,
        )
        await self._seed_embed(
            qa_channel,
            "🧪 QA / Tests",
            "Reproduis les bugs, note les étapes, valide les correctifs et confirme ce qui est prêt avant production.",
            colour=0x5865F2,
        )
        await self._seed_embed(
            reports,
            "📨 Reports",
            "Les signalements importants et dossiers nécessitant l'intervention du staff sont centralisés ici.",
            colour=0xED4245,
        )

        log_intro = {
            "messages": ("📝 Logs messages", "Suppressions et modifications de messages seront enregistrées automatiquement ici."),
            "members": ("👥 Logs membres", "Arrivées, départs, changements de pseudo et rôles seront enregistrés ici."),
            "roles": ("🎭 Logs rôles", "Les modifications importantes de rôles seront enregistrées automatiquement ici."),
            "server": ("🏗️ Logs serveur", "Créations, suppressions et modifications de salons/catégories seront enregistrées ici."),
            "voice": ("🔊 Logs vocal", "Les mouvements vocaux suivis par SentriX seront enregistrés ici."),
            "moderation": ("🛡️ Logs modération", "Warns, mutes, kicks, bans et actions de modération seront enregistrés ici."),
            "tickets": ("🎫 Logs tickets", "Les événements importants du système de tickets seront enregistrés ici."),
            "automod": ("🔐 Logs sécurité", "AutoMod, anti-spam, anti-raid et protections de sécurité seront enregistrés ici."),
        }
        for key, channel in log_channels.items():
            title, description = log_intro[key]
            await self._seed_embed(
                channel,
                title,
                description,
                colour=0x2B2D31,
                footer="SentriX • Journal automatique",
            )

        await self._configure_database(
            guild,
            owner_role=owner_role,
            staff_role=staff_role,
            welcome=welcome,
            goodbye=goodbye,
            rules=rules,
            announcements=announcements,
            suggestions=suggestions,
            sentrix_chat=sentrix_chat,
            tickets_category=tickets,
            reports=reports,
            log_channels=log_channels,
        )
        ticket_ready = await self._ticket_panel(
            guild,
            ticket_channel,
            tickets,
            support_role,
            log_channels["tickets"],
        )

        return {
            "roles_created": sum(int(flag) for flag in (r1, r2, r3, r4, r5, r6, r7, r8)),
            "categories_created": sum(int(flag) for flag in (c1, c2, c3, c4, c5, c6)),
            "channels_created": created_channels,
            "ticket_ready": ticket_ready,
            "logs_ready": 8,
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Dans le salon 🤖・sentrix-chat, chaque message normal devient une demande IA."""
        if message.author.bot or not message.guild:
            return
        channel_name = getattr(message.channel, "name", "").casefold()
        if not channel_name.endswith("sentrix-chat"):
            return

        content = (message.content or "").strip()
        if not content:
            return

        prefix = (
            self.bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX)
            if hasattr(self.bot, "prefix_cache")
            else config.DEFAULT_PREFIX
        )
        if content.startswith(prefix):
            return

        lowered = content.casefold().lstrip()
        if self.bot.user and self.bot.user in message.mentions:
            return
        if lowered.startswith(("sentrix ", "sentrix,", "sentrix:", "sentri ", "snetri ")):
            return

        ai_cog = self.bot.get_cog("Ai")
        if ai_cog is None or not hasattr(ai_cog, "send_sentrix_reply"):
            ai_cog = next(
                (c for c in self.bot.cogs.values() if hasattr(c, "send_sentrix_reply")),
                None,
            )
        if ai_cog is None:
            return

        try:
            async with message.channel.typing():
                await ai_cog.send_sentrix_reply(
                    message.channel,
                    message.author,
                    content,
                    reply_to=message,
                )
        except Exception:
            logger.exception(
                "Réponse automatique sentrix-chat impossible guild=%s",
                message.guild.id,
            )

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
                return await ctx.send("La version professionnelle SentriX v3 est déjà installée sur ce serveur.")

            upgrading = previous is not None
            progress = await ctx.send(
                "Mise à niveau SentriX en cours…" if upgrading
                else "Création du serveur officiel SentriX en cours…"
            )

            try:
                result = await self._build(guild)
                await self._mark_installed(guild.id, ctx.author.id)
                support_state = "prêt" if result["ticket_ready"] else "à finaliser avec +ticketsetup"
                await progress.edit(
                    content=(
                        "Mise à niveau SentriX terminée. Structure professionnelle, 8 rôles spécialisés, "
                        "salons avec emojis, "
                        f"{result['logs_ready']} catégories de logs automatiques et support {support_state}. "
                        "Le règlement complet et les messages d'introduction ont été installés."
                    ),
                    embed=None,
                    view=None,
                )
            except discord.Forbidden:
                logger.warning("+create sentrix refusé guild=%s", guild.id, exc_info=True)
                await progress.edit(
                    content=(
                        "Installation arrêtée : une permission Discord manque. "
                        "Aucun verrou définitif n'a été posé."
                    ),
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                logger.warning("+create sentrix HTTP guild=%s", guild.id, exc_info=True)
                await progress.edit(
                    content=(
                        "Discord a interrompu l'installation. Les éléments déjà créés seront "
                        "réutilisés au prochain essai."
                    ),
                    embed=None,
                    view=None,
                )
            except Exception:
                logger.exception("Erreur +create sentrix guild=%s", guild.id)
                try:
                    await progress.edit(
                        content=(
                            "Installation interrompue par une erreur technique. "
                            "Aucun verrou définitif n'a été posé."
                        ),
                        embed=None,
                        view=None,
                    )
                except discord.HTTPException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CreateSentrix(bot))
