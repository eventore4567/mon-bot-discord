"""Constructeur officiel SentriX.

La syntaxe publique reste ``+create sentrix`` mais l'implémentation est volontairement
simple : une commande ``create`` classique avec un argument de modèle. Aucun groupe de
sous-commandes, aucune table d'installation et aucun patch runtime ne sont nécessaires.

La commande est relançable : elle réutilise les rôles, catégories et salons portant les
noms officiels, répare leur configuration, remet en place les messages, les logs, les
tickets et les réglages SentriX.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config
from utils import checks
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.create-sentrix")

TEMPLATE_NAME = "sentrix"
REASON = "Configuration officielle SentriX"
CORE_AUTOMOD = ("antispam", "antiinvite", "antimention", "antiraid", "antiscam")


class CreateSentrix(commands.Cog, name="CreateSentrix"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    @staticmethod
    def _find_named(items, name: str, aliases: tuple[str, ...] = ()):
        for candidate in (name, *aliases):
            found = discord.utils.get(items, name=candidate)
            if found is not None:
                return found
        return None

    async def _authorized(self, ctx: commands.Context) -> bool:
        author = ctx.author
        if isinstance(author, discord.Member) and author.guild_permissions.administrator:
            return True
        try:
            return await checks.is_verified_bot_owner(ctx)
        except Exception:
            logger.exception("Vérification propriétaire impossible pour +create sentrix")
            return False

    async def _role(
        self,
        guild: discord.Guild,
        name: str,
        colour: discord.Color,
        permissions: discord.Permissions,
        *,
        aliases: tuple[str, ...] = (),
        hoist: bool = True,
    ) -> tuple[discord.Role, bool]:
        role = self._find_named(guild.roles, name, aliases)
        if role is not None:
            try:
                await role.edit(
                    name=name,
                    colour=colour,
                    permissions=permissions,
                    hoist=hoist,
                    mentionable=False,
                    reason=REASON,
                )
            except discord.HTTPException:
                logger.warning("Impossible de remettre à niveau le rôle %s", name, exc_info=True)
            return role, False

        role = await guild.create_role(
            name=name,
            colour=colour,
            permissions=permissions,
            hoist=hoist,
            mentionable=False,
            reason=REASON,
        )
        return role, True

    async def _category(
        self,
        guild: discord.Guild,
        name: str,
        *,
        aliases: tuple[str, ...] = (),
        overwrites: dict | None = None,
    ) -> tuple[discord.CategoryChannel, bool]:
        category = self._find_named(guild.categories, name, aliases)
        if category is not None:
            try:
                await category.edit(
                    name=name,
                    overwrites=overwrites if overwrites is not None else category.overwrites,
                    reason=REASON,
                )
            except discord.HTTPException:
                logger.warning("Impossible de remettre à niveau la catégorie %s", name, exc_info=True)
            return category, False

        category = await guild.create_category(
            name=name,
            overwrites=overwrites or {},
            reason=REASON,
        )
        return category, True

    async def _text(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        name: str,
        topic: str,
        overwrites: dict,
        *,
        aliases: tuple[str, ...] = (),
    ) -> tuple[discord.TextChannel, bool]:
        channel = self._find_named(guild.text_channels, name, aliases)
        if channel is not None:
            try:
                await channel.edit(
                    name=name,
                    category=category,
                    topic=topic[:1024],
                    overwrites=overwrites,
                    reason=REASON,
                )
            except discord.HTTPException:
                logger.warning("Impossible de remettre à niveau le salon %s", name, exc_info=True)
            return channel, False

        channel = await guild.create_text_channel(
            name=name,
            category=category,
            topic=topic[:1024],
            overwrites=overwrites,
            reason=REASON,
        )
        return channel, True

    async def _voice(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        name: str,
        overwrites: dict,
        *,
        aliases: tuple[str, ...] = (),
    ) -> tuple[discord.VoiceChannel, bool]:
        channel = self._find_named(guild.voice_channels, name, aliases)
        if channel is not None:
            try:
                await channel.edit(
                    name=name,
                    category=category,
                    overwrites=overwrites,
                    reason=REASON,
                )
            except discord.HTTPException:
                logger.warning("Impossible de remettre à niveau le vocal %s", name, exc_info=True)
            return channel, False

        channel = await guild.create_voice_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            reason=REASON,
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
    ) -> bool:
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
        try:
            async for message in channel.history(limit=40):
                if self.bot.user is None or message.author.id != self.bot.user.id:
                    continue
                if any(item.title == title for item in message.embeds):
                    existing = message
                    break
        except discord.HTTPException:
            existing = None

        try:
            if existing is not None:
                await existing.edit(content=None, embed=embed)
            else:
                await panels.envoyer(channel, panels.depuis_embed(embed))
            return True
        except discord.HTTPException:
            logger.warning("Message d'introduction impossible dans #%s", channel.name, exc_info=True)
            return False

    async def _seed_rules(self, channel: discord.TextChannel) -> bool:
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
                "Utilise les commandes et le salon 🤖・sentrix-chat normalement. Pas de spam de commandes, surcharge volontaire, abus de l'IA ou exploitation d'un bug.",
                False,
            ),
            (
                "8 • Support et tickets",
                "Ouvre un ticket uniquement pour une vraie demande. Explique le problème clairement, évite les doubles tickets et respecte l'équipe support.",
                False,
            ),
            (
                "9 • Sanctions et contournement",
                "Contourner un mute, ban, blacklist ou une restriction avec un autre compte peut aggraver la sanction. Une décision peut être contestée proprement via le support.",
                False,
            ),
            (
                "10 • Discord et bon sens",
                "Les Conditions d'utilisation et règles de Discord restent applicables. Le staff peut intervenir face à un comportement nuisible même s'il n'est pas décrit mot pour mot ici.",
                False,
            ),
        ]
        return await self._seed_embed(
            channel,
            "📜 Règlement officiel SentriX",
            'Bienvenue sur le serveur officiel de **SentriX**. Le but est de garder un espace propre, professionnel et utile pour les utilisateurs du bot.\n\nEn restant sur le serveur, vous acceptes les règles ci-dessous.',
            fields=fields,
            footer="SentriX • Règlement officiel",
        )

    async def _assign_role(
        self,
        member: discord.Member | None,
        role: discord.Role,
        *,
        reason: str,
    ) -> None:
        if member is None or role in member.roles:
            return
        try:
            await member.add_roles(role, reason=reason)
        except discord.HTTPException:
            logger.warning(
                "Attribution du rôle %s impossible à %s",
                role.name,
                getattr(member, "id", "?"),
                exc_info=True,
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
    ) -> list[str]:
        warnings: list[str] = []
        try:
            await self.bot.db.ensure_guild(guild.id)
        except Exception:
            logger.exception("ensure_guild impossible pendant +create sentrix")
            return ["base de données"]

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
            "log_channel": log_channels["server"].id,
            "log_messages": log_channels["messages"].id,
            "log_members": log_channels["members"].id,
            "log_voice": log_channels["voice"].id,
            "log_roles": log_channels["roles"].id,
            "log_server": log_channels["server"].id,
            "log_automod": log_channels["automod"].id,
            "log_moderation": log_channels["moderation"].id,
            "error_channel": log_channels["server"].id,
            "report_channel": reports.id,
            "mod_role": staff_role.id,
            "admin_role": owner_role.id,
            "security_level": "moyen",
        }

        for column, value in settings.items():
            try:
                await self.bot.db.execute(
                    f"UPDATE guild_config SET {column}=? WHERE guild_id=?",
                    (value, guild.id),
                )
            except Exception:
                if "configuration DB" not in warnings:
                    warnings.append("configuration DB")
                logger.exception("Réglage %s impossible pendant +create sentrix", column)

        for field in CORE_AUTOMOD:
            try:
                await self.bot.db.set_automod(guild.id, field, 1)
            except Exception:
                if "AutoMod" not in warnings:
                    warnings.append("AutoMod")
                logger.exception("AutoMod %s impossible pendant +create sentrix", field)

        try:
            from utils import log_service
        except Exception:
            logger.exception("Service de logs indisponible pendant +create sentrix")
            warnings.append("logs")
            return warnings

        for log_type, channel in log_channels.items():
            try:
                await log_service.set_log_channel(self.bot, guild.id, log_type, channel.id)
                await log_service.set_log_enabled(self.bot, guild.id, log_type, True)
            except Exception:
                if "logs" not in warnings:
                    warnings.append("logs")
                logger.exception("Log %s impossible pendant +create sentrix", log_type)

        return warnings

    async def _ticket_panel(
        self,
        guild: discord.Guild,
        panel_channel: discord.TextChannel,
        tickets_category: discord.CategoryChannel,
        support_role: discord.Role,
        logs_channel: discord.TextChannel,
    ) -> bool:
        cog = self.bot.get_cog("Tickets")
        if cog is None:
            logger.warning("Cog Tickets indisponible pendant +create sentrix")
            return False

        try:
            panel = await cog.get_panel_by_name(guild.id, "Support SentriX")
            panel_id = int(panel["id"]) if panel else await cog.create_panel(guild.id, "Support SentriX")

            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET title=?,description=?,channel_id=?,style=?,"
                "max_per_member=?,enabled=1 WHERE id=?",
                (
                    "🎫 Support officiel SentriX",
                    "Un bug, une question, un problème de configuration ou un signalement privé ? Ouvrez un ticket : l'équipe support vous répondra dans un salon privé.",
                    panel_channel.id,
                    "button",
                    1,
                    panel_id,
                ),
            )

            ticket_type = await cog.get_type_by_name(guild.id, "Support SentriX")
            type_id = (
                int(ticket_type["id"])
                if ticket_type
                else await cog.add_type(guild.id, panel_id, "Support SentriX")
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
                    'Décrivez précisément votre demande. Un membre du support SentriX va prendre le relais.',
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

            message = await panels.envoyer(panel_channel, panels.avec_composants(panels.depuis_embed(cog.build_panel_embed(panel)), TicketPanelView(panel, types)))
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET message_id=?,channel_id=? WHERE id=?",
                (message.id, panel_channel.id, panel_id),
            )
            return True
        except Exception:
            logger.exception("Panel Support SentriX impossible guild=%s", guild.id)
            return False

    async def _build(
        self,
        guild: discord.Guild,
        installer: discord.Member,
    ) -> dict[str, object]:
        default = guild.default_role
        me = guild.me
        if me is None:
            raise RuntimeError("SentriX n'est pas présent comme membre du serveur.")

        role_specs = [
            (
                "Owner SentriX",
                discord.Color.from_rgb(108, 82, 230),
                discord.Permissions(administrator=True),
                (),
            ),
            (
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
                (),
            ),
            (
                "Developer SentriX",
                discord.Color.from_rgb(74, 104, 190),
                discord.Permissions(
                    view_audit_log=True,
                    manage_channels=True,
                    manage_webhooks=True,
                    manage_messages=True,
                    manage_threads=True,
                ),
                ("Dev SentriX",),
            ),
            (
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
                (),
            ),
            (
                "Support Lead",
                discord.Color.from_rgb(42, 166, 160),
                discord.Permissions(
                    view_audit_log=True,
                    moderate_members=True,
                    kick_members=True,
                    manage_messages=True,
                    manage_threads=True,
                    manage_nicknames=True,
                    move_members=True,
                    mute_members=True,
                ),
                (),
            ),
            (
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
                (),
            ),
            (
                "Community Manager",
                discord.Color.from_rgb(220, 92, 170),
                discord.Permissions(
                    manage_messages=True,
                    manage_threads=True,
                    manage_events=True,
                    manage_nicknames=True,
                ),
                (),
            ),
            (
                "QA Tester",
                discord.Color.from_rgb(130, 130, 160),
                discord.Permissions.none(),
                (),
            ),
            (
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
                (),
            ),
            (
                "SentriX Bot",
                discord.Color.from_rgb(88, 72, 235),
                discord.Permissions(
                    view_audit_log=True,
                    manage_roles=True,
                    manage_channels=True,
                    manage_messages=True,
                    manage_threads=True,
                    moderate_members=True,
                    kick_members=True,
                    ban_members=True,
                    send_messages=True,
                    embed_links=True,
                    attach_files=True,
                    read_message_history=True,
                    add_reactions=True,
                ),
                (),
            ),
        ]

        roles: dict[str, discord.Role] = {}
        roles_created = 0
        for name, colour, permissions, aliases in role_specs:
            role, is_new = await self._role(
                guild,
                name,
                colour,
                permissions,
                aliases=aliases,
                hoist=True,
            )
            roles[name] = role
            roles_created += int(is_new)

        owner_role = roles["Owner SentriX"]
        lead_dev_role = roles["Lead Developer"]
        dev_role = roles["Developer SentriX"]
        security_role = roles["Security Engineer"]
        support_lead_role = roles["Support Lead"]
        support_role = roles["Support Specialist"]
        community_role = roles["Community Manager"]
        qa_role = roles["QA Tester"]
        staff_role = roles["Staff SentriX"]
        bot_role = roles["SentriX Bot"]

        await self._assign_role(
            installer,
            owner_role,
            reason="Installation du serveur officiel SentriX",
        )
        if guild.owner is not None and guild.owner.id != installer.id:
            await self._assign_role(
                guild.owner,
                owner_role,
                reason="Propriétaire du serveur officiel SentriX",
            )
        await self._assign_role(
            me,
            bot_role,
            reason="Rôle officiel du bot SentriX",
        )

        staff_roles = [
            owner_role,
            lead_dev_role,
            dev_role,
            security_role,
            support_lead_role,
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
        for role in (owner_role, lead_dev_role):
            logs_only[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        ticket_private = {
            default: discord.PermissionOverwrite(view_channel=False),
            me: bot_full,
        }
        for role in (
            owner_role,
            lead_dev_role,
            dev_role,
            security_role,
            support_lead_role,
            support_role,
            staff_role,
        ):
            ticket_private[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        category_specs = [
            ("official", "📡 SENTRIX — OFFICIEL", ("SENTRIX — OFFICIEL",), None),
            ("community", "💬 SENTRIX — COMMUNAUTÉ", ("SENTRIX — COMMUNAUTÉ",), None),
            ("support", "🆘 SENTRIX — SUPPORT", ("SENTRIX — SUPPORT",), None),
            ("staff", "🔒 SENTRIX — STAFF", ("SENTRIX — STAFF",), staff_only),
            ("logs", "📊 SENTRIX — LOGS", ("SENTRIX — LOGS",), logs_only),
            ("tickets", "🎫 SENTRIX — TICKETS", ("SENTRIX — TICKETS",), ticket_private),
        ]

        categories: dict[str, discord.CategoryChannel] = {}
        categories_created = 0
        for key, name, aliases, overwrites in category_specs:
            category, is_new = await self._category(
                guild,
                name,
                aliases=aliases,
                overwrites=overwrites,
            )
            categories[key] = category
            categories_created += int(is_new)

        created_channels = 0

        async def text(
            category_key: str,
            name: str,
            topic: str,
            perms: dict,
            aliases: tuple[str, ...] = (),
        ) -> discord.TextChannel:
            nonlocal created_channels
            channel, is_new = await self._text(
                guild,
                categories[category_key],
                name,
                topic,
                perms,
                aliases=aliases,
            )
            created_channels += int(is_new)
            return channel

        welcome = await text(
            "official",
            "👋・bienvenue",
            "Accueil officiel des nouveaux membres SentriX.",
            readonly,
            ("bienvenue",),
        )
        rules = await text(
            "official",
            "📜・règlement",
            "Règlement officiel et règles de sécurité de la communauté SentriX.",
            readonly,
            ("règlement",),
        )
        announcements = await text(
            "official",
            "📢・annonces-sentrix",
            "Nouveautés, versions et annonces officielles SentriX.",
            readonly,
            ("annonces-sentrix",),
        )
        status = await text(
            "official",
            "🟢・statut-sentrix",
            "État du bot, maintenances, incidents et disponibilité des services.",
            readonly,
            ("statut-sentrix",),
        )
        goodbye = await text(
            "official",
            "👋・départs",
            "Journal public léger des départs de la communauté.",
            readonly,
            ("départs",),
        )

        general = await text(
            "community",
            "💬・général",
            "Discussion principale de la communauté SentriX.",
            public,
            ("général",),
        )
        sentrix_chat = await text(
            "community",
            "🤖・sentrix-chat",
            "Parle directement avec SentriX sans écrire +ai ni mentionner le bot.",
            public,
            ("sentrix-chat",),
        )
        suggestions = await text(
            "community",
            "💡・suggestions",
            "Idées, retours produit et propositions d'amélioration.",
            public,
            ("suggestions",),
        )
        animations = await text(
            "community",
            "🎉・animations",
            "Animations, rendez-vous et activités de la communauté SentriX.",
            public,
            ("animations",),
        )

        faq = await text(
            "support",
            "❓・faq",
            "Réponses rapides aux questions fréquentes sur SentriX.",
            readonly,
            ("faq",),
        )
        ticket_channel = await text(
            "support",
            "🎫・ouvrir-un-ticket",
            "Support privé officiel SentriX.",
            readonly,
            ("ouvrir-un-ticket",),
        )

        staff_chat = await text(
            "staff",
            "🛡️・staff",
            "Coordination privée de l'équipe SentriX.",
            staff_only,
            ("staff",),
        )
        dev_channel = await text(
            "staff",
            "💻・dev-sentrix",
            "Développement, versions, incidents techniques et architecture SentriX.",
            dev_only,
            ("dev-sentrix",),
        )
        qa_channel = await text(
            "staff",
            "🧪・qa-tests",
            "Tests qualité, reproductions de bugs et validation avant mise en production.",
            dev_only,
            ("qa-tests",),
        )
        reports = await text(
            "staff",
            "📨・reports",
            "Signalements utilisateurs et dossiers à traiter par l'équipe.",
            staff_only,
            ("reports",),
        )

        log_channels = {
            "messages": await text(
                "logs",
                "📝・logs-messages",
                "Suppressions et modifications de messages.",
                logs_only,
                ("logs-messages",),
            ),
            "members": await text(
                "logs",
                "👥・logs-membres",
                "Arrivées, départs et modifications de membres.",
                logs_only,
                ("logs-membres",),
            ),
            "roles": await text(
                "logs",
                "🎭・logs-rôles",
                "Créations, suppressions et modifications de rôles.",
                logs_only,
                ("logs-rôles",),
            ),
            "server": await text(
                "logs",
                "🏗️・logs-serveur",
                "Créations, suppressions et modifications de salons/catégories.",
                logs_only,
                ("logs-sentrix", "logs-serveur"),
            ),
            "voice": await text(
                "logs",
                "🔊・logs-vocal",
                "Connexions, déconnexions et déplacements vocaux.",
                logs_only,
                ("logs-vocal",),
            ),
            "moderation": await text(
                "logs",
                "🛡️・logs-modération",
                "Warns, mutes, kicks, bans et autres actions de modération.",
                logs_only,
                ("logs-modération",),
            ),
            "tickets": await text(
                "logs",
                "🎫・logs-tickets",
                "Ouvertures, fermetures et actions importantes sur les tickets.",
                logs_only,
                ("logs-tickets",),
            ),
            "automod": await text(
                "logs",
                "🔐・logs-sécurité",
                "AutoMod, anti-spam, anti-raid, anti-scam et protections SentriX.",
                logs_only,
                ("logs-sécurité",),
            ),
        }

        _, voice_community_new = await self._voice(
            guild,
            categories["community"],
            "🔊・Communauté SentriX",
            public,
            aliases=("Communauté SentriX",),
        )
        _, voice_staff_new = await self._voice(
            guild,
            categories["staff"],
            "🔒・Staff SentriX",
            staff_only,
            aliases=("Staff SentriX",),
        )
        created_channels += int(voice_community_new) + int(voice_staff_new)

        seed_jobs = [
            self._seed_embed(
                welcome,
                "👋 Bienvenue sur SentriX",
                "Bienvenue sur le serveur officiel de **SentriX**.\n\nCommencez par lire le règlement, puis passez dans **🤖・sentrix-chat** pour parler directement avec l'IA du bot.",
            ),
            self._seed_rules(rules),
            self._seed_embed(
                announcements,
                "📢 Annonces officielles",
                "Les nouvelles versions, changements importants, maintenances planifiées et nouveautés SentriX seront publiés ici.",
            ),
            self._seed_embed(
                status,
                "🟢 Statut de SentriX",
                "Ce salon centralise l'état du bot et les incidents importants. En fonctionnement normal, aucune action n'est nécessaire.",
                colour=0x57F287,
            ),
            self._seed_embed(
                goodbye,
                "👋 Départs",
                "Les départs de la communauté peuvent être annoncés ici automatiquement.",
                colour=0x5865F2,
            ),
            self._seed_embed(
                general,
                "💬 Communauté SentriX",
                "Salon principal pour discuter avec la communauté. Garde les demandes privées et problèmes techniques pour le support.",
            ),
            self._seed_embed(
                sentrix_chat,
                "🤖 Parler avec SentriX",
                'Écrivez simplement votre message dans ce salon. **Pas besoin de `+ai` ni de mentionner le bot** : SentriX vous répond directement.',
            ),
            self._seed_embed(
                suggestions,
                "💡 Suggestions",
                "Une idée pour améliorer le bot, le dashboard ou le serveur ? Explique-la clairement ici.",
            ),
            self._seed_embed(
                animations,
                "🎉 Animations",
                "Les animations, petits événements communautaires et rendez-vous seront organisés ici.",
            ),
            self._seed_embed(
                faq,
                "❓ FAQ SentriX",
                "**Parler à l'IA :** 🤖・sentrix-chat\n**Support privé :** 🎫・ouvrir-un-ticket\n**Nouveautés :** 📢・annonces-sentrix\n**État du bot :** 🟢・statut-sentrix",
            ),
            self._seed_embed(
                ticket_channel,
                "🎫 Support SentriX",
                "Pour un bug, une question de configuration ou un problème privé, utilise le panel ci-dessous. Un salon privé sera créé automatiquement.",
            ),
            self._seed_embed(
                staff_chat,
                "🛡️ Espace staff",
                "Coordination interne, décisions de modération et suivi opérationnel du serveur SentriX.",
                colour=0x5865F2,
            ),
            self._seed_embed(
                dev_channel,
                "💻 Développement SentriX",
                "Architecture, correctifs, déploiements, incidents techniques et suivi des versions.",
                colour=0x5865F2,
            ),
            self._seed_embed(
                qa_channel,
                "🧪 QA / Tests",
                "Reproduis les bugs, note les étapes, valide les correctifs et confirme ce qui est prêt avant production.",
                colour=0x5865F2,
            ),
            self._seed_embed(
                reports,
                "📨 Reports",
                "Les signalements importants et dossiers nécessitant l'intervention du staff sont centralisés ici.",
                colour=0xED4245,
            ),
        ]

        seed_results = await asyncio.gather(*seed_jobs, return_exceptions=False)

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
        log_seed_results = []
        for key, channel in log_channels.items():
            title, description = log_intro[key]
            log_seed_results.append(
                await self._seed_embed(
                    channel,
                    title,
                    description,
                    colour=0x2B2D31,
                    footer="SentriX • Journal automatique",
                )
            )

        warnings = await self._configure_database(
            guild,
            owner_role=owner_role,
            staff_role=staff_role,
            welcome=welcome,
            goodbye=goodbye,
            rules=rules,
            announcements=announcements,
            suggestions=suggestions,
            sentrix_chat=sentrix_chat,
            tickets_category=categories["tickets"],
            reports=reports,
            log_channels=log_channels,
        )

        ticket_ready = await self._ticket_panel(
            guild,
            ticket_channel,
            categories["tickets"],
            support_role,
            log_channels["tickets"],
        )
        if not ticket_ready:
            warnings.append("panel tickets")

        failed_seed_count = sum(not bool(item) for item in seed_results) + sum(
            not bool(item) for item in log_seed_results
        )
        if failed_seed_count:
            warnings.append(f"{failed_seed_count} message(s) d'introduction")

        return {
            "roles_created": roles_created,
            "roles_total": len(role_specs),
            "categories_created": categories_created,
            "categories_total": len(category_specs),
            "channels_created": created_channels,
            "logs_ready": len(log_channels),
            "ticket_ready": ticket_ready,
            "warnings": warnings,
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Dans 🤖・sentrix-chat, un message normal est envoyé directement à l'IA."""
        if message.author.bot or message.guild is None:
            return
        if getattr(message.channel, "name", "").casefold() != "🤖・sentrix-chat":
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
                (cog for cog in self.bot.cogs.values() if hasattr(cog, "send_sentrix_reply")),
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
            logger.exception("Réponse automatique sentrix-chat impossible guild=%s", message.guild.id)

    @commands.command(name="create")
    async def create(self, ctx: commands.Context, *, template: str = ""):
        """Installe ou répare le modèle officiel avec ``+create sentrix``."""
        requested = template.strip().casefold()
        if requested != TEMPLATE_NAME:
            return await ctx.send('Utilisez `+create sentrix` pour créer ou réparer le serveur officiel SentriX.')

        guild = ctx.guild
        if guild is None or not isinstance(ctx.author, discord.Member):
            return await ctx.send("Cette commande doit être utilisée dans un serveur Discord.")

        if not await self._authorized(ctx):
            return await ctx.send("Cette commande est réservée aux administrateurs du serveur.")

        me = guild.me
        if me is None:
            return await ctx.send("SentriX n'est pas correctement présent sur ce serveur.")
        if not me.guild_permissions.administrator:
            return await ctx.send('Donnez temporairement la permission **Administrateur** à SentriX puis relancez `+create sentrix`.')

        lock = self._lock_for(guild.id)
        if lock.locked():
            return await ctx.send("Une création/réparation SentriX est déjà en cours sur ce serveur.")

        async with lock:
            progress = await ctx.send(
                "Création/réparation du serveur SentriX en cours… "
                "Je vérifie les rôles, salons, permissions, logs et tickets."
            )
            try:
                result = await self._build(guild, ctx.author)
            except discord.Forbidden as error:
                logger.exception("+create sentrix interdit guild=%s", guild.id)
                try:
                    await progress.edit(
                        content=(
                            f'Installation arrêtée : Discord a refusé une action. Vérifiez que le rôle de SentriX est placé assez haut et possède Administrateur. `{type(error).__name__}`'
                        )
                    )
                except discord.HTTPException:
                    pass
                return
            except discord.HTTPException as error:
                logger.exception("+create sentrix HTTP guild=%s", guild.id)
                detail = str(error).replace("\n", " ")[:180]
                try:
                    await progress.edit(
                        content=(
                            f"Discord a interrompu l'installation. Relancez `+create sentrix` : les éléments déjà créés seront réutilisés. Détail : `{detail or type(error).__name__}`"
                        )
                    )
                except discord.HTTPException:
                    pass
                return
            except Exception as error:
                logger.exception("+create sentrix erreur guild=%s", guild.id)
                detail = str(error).replace("\n", " ")[:180]
                try:
                    await progress.edit(
                        content=(
                            f"La création a rencontré une erreur interne, mais la commande n'a pas été verrouillée. Vous pouvez la relancer après correction. Détail : `{type(error).__name__}: {detail}`"
                        )
                    )
                except discord.HTTPException:
                    pass
                return

            warnings = list(result.get("warnings") or [])
            warning_text = (
                " Quelques éléments restent à finaliser : " + ", ".join(warnings) + "."
                if warnings
                else ""
            )
            await progress.edit(
                content=(
                    "Serveur SentriX prêt. "
                    f"{result['roles_total']} rôles professionnels, "
                    f"{result['categories_total']} catégories, "
                    f"{result['logs_ready']} salons de logs, accueil/départ, règlement, IA et support configurés."
                    + warning_text
                )
            )


async def setup(bot: commands.Bot) -> None:
    # cogs/create_command_router.py est la racine canonique de +create (sous-groupes
    # sentrix / server / manox). Quand il est deja installe, ce cog historique n'a plus
    # rien a enregistrer : tenter de le faire levait CommandRegistrationError et faisait
    # echouer tout le chargement de cogs.create_sentrix.
    existing = bot.get_command("create")
    if isinstance(existing, commands.Group):
        logger.info(
            "Routeur +create canonique deja en place : cog CreateSentrix historique ignore."
        )
        return
    await bot.add_cog(CreateSentrix(bot))
