"""Créateur du serveur officiel SentriX : +create sentrix.

Cette commande ne clone aucun template communautaire générique. Elle construit une
structure courte et reconnaissable, pensée autour de SentriX lui-même : informations
officielles, salon de conversation IA sans commande, support/tickets, animations et un
petit espace staff. Elle est idempotente pendant l'installation et verrouillée après une
installation réussie de cette génération.
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

TEMPLATE_KEY = "sentrix-official-v2"

INSTALL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sentrix_server_installations (
    guild_id INTEGER PRIMARY KEY,
    installed_at INTEGER NOT NULL,
    installed_by INTEGER NOT NULL,
    template_key TEXT NOT NULL DEFAULT 'sentrix-official-v2'
)
"""

CORE_AUTOMOD = (
    "antispam",
    "antiinvite",
    "antimention",
    "antiraid",
    "antiscam",
)


class CreateSentrix(commands.Cog, name="CreateSentrix"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    async def _ensure_table(self) -> None:
        await self.bot.db.execute(INSTALL_TABLE_SQL)

    async def _installation(self, guild_id: int):
        await self._ensure_table()
        return await self.bot.db.fetchone(
            "SELECT guild_id, installed_at, installed_by, template_key "
            "FROM sentrix_server_installations WHERE guild_id = ?",
            (guild_id,),
        )

    async def _mark_installed(self, guild_id: int, user_id: int) -> None:
        await self.bot.db.execute(
            "INSERT INTO sentrix_server_installations "
            "(guild_id, installed_at, installed_by, template_key) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "installed_at=excluded.installed_at, installed_by=excluded.installed_by, "
            "template_key=excluded.template_key",
            (guild_id, int(time.time()), user_id, TEMPLATE_KEY),
        )

    async def _ensure_role(
        self,
        guild: discord.Guild,
        name: str,
        *,
        color: discord.Color,
        permissions: discord.Permissions,
        hoist: bool = True,
    ) -> tuple[discord.Role, bool]:
        role = discord.utils.get(guild.roles, name=name)
        if role is not None:
            try:
                await role.edit(
                    color=color,
                    permissions=permissions,
                    hoist=hoist,
                    reason="Configuration officielle SentriX",
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
            reason="Configuration officielle SentriX",
        )
        return role, True

    async def _ensure_category(
        self,
        guild: discord.Guild,
        name: str,
        *,
        overwrites: dict | None = None,
    ) -> tuple[discord.CategoryChannel, bool]:
        category = discord.utils.get(guild.categories, name=name)
        if category is None:
            category = await guild.create_category(
                name,
                overwrites=overwrites or {},
                reason="Configuration officielle SentriX",
            )
            return category, True
        if overwrites:
            try:
                await category.edit(overwrites=overwrites, reason="Configuration officielle SentriX")
            except discord.HTTPException:
                pass
        return category, False

    async def _ensure_text(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        name: str,
        *,
        topic: str,
        overwrites: dict,
    ) -> tuple[discord.TextChannel, bool]:
        channel = discord.utils.get(guild.text_channels, name=name)
        if channel is None:
            channel = await guild.create_text_channel(
                name,
                category=category,
                topic=topic[:1024],
                overwrites=overwrites,
                reason="Configuration officielle SentriX",
            )
            return channel, True
        try:
            await channel.edit(
                category=category,
                topic=topic[:1024],
                overwrites=overwrites,
                reason="Configuration officielle SentriX",
            )
        except discord.HTTPException:
            pass
        return channel, False

    async def _ensure_voice(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        name: str,
        *,
        overwrites: dict,
    ) -> tuple[discord.VoiceChannel, bool]:
        channel = discord.utils.get(guild.voice_channels, name=name)
        if channel is None:
            channel = await guild.create_voice_channel(
                name,
                category=category,
                overwrites=overwrites,
                reason="Configuration officielle SentriX",
            )
            return channel, True
        try:
            await channel.edit(category=category, overwrites=overwrites, reason="Configuration officielle SentriX")
        except discord.HTTPException:
            pass
        return channel, False

    async def _seed(self, channel: discord.TextChannel, marker: str, content: str) -> None:
        """Publie chaque message d'accueil une seule fois, y compris après un retry."""
        try:
            async for message in channel.history(limit=30):
                if message.author.id == self.bot.user.id and marker in (message.content or ""):
                    return
        except discord.HTTPException:
            pass
        await channel.send(content)

    async def _apply_database_config(
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
        ticket_category: discord.CategoryChannel,
        logs: discord.TextChannel,
        reports: discord.TextChannel,
    ) -> None:
        await self.bot.db.ensure_guild(guild.id)
        await self.bot.db.execute(
            "UPDATE guild_config SET "
            "welcome_channel=?, welcome_message=?, goodbye_channel=?, goodbye_message=?, "
            "rules_channel=?, announce_channel=?, suggest_channel=?, bot_commands_channel=?, "
            "ticket_category=?, ticket_log_channel=?, log_channel=?, log_messages=?, "
            "log_members=?, log_moderation=?, log_automod=?, error_channel=?, report_channel=?, "
            "mod_role=?, admin_role=?, security_level=? WHERE guild_id=?",
            (
                welcome.id,
                "Bienvenue {member} sur {server}. Découvre SentriX dans #sentrix-chat et consulte le règlement avant de participer.",
                goodbye.id,
                "{member} a quitté {server}.",
                rules.id,
                announcements.id,
                suggestions.id,
                sentrix_chat.id,
                ticket_category.id,
                logs.id,
                logs.id,
                logs.id,
                logs.id,
                logs.id,
                logs.id,
                logs.id,
                reports.id,
                staff_role.id,
                owner_role.id,
                "moyen",
                guild.id,
            ),
        )
        for field in CORE_AUTOMOD:
            try:
                await self.bot.db.set_automod(guild.id, field, 1)
            except Exception:
                logger.warning("Activation AutoMod impossible pour %s sur %s", field, guild.id, exc_info=True)

    async def _setup_ticket_panel(
        self,
        guild: discord.Guild,
        *,
        panel_channel: discord.TextChannel,
        tickets_category: discord.CategoryChannel,
        staff_role: discord.Role,
        logs_channel: discord.TextChannel,
    ) -> bool:
        ticket_cog = self.bot.get_cog("Tickets")
        if ticket_cog is None:
            logger.warning("Tickets introuvable pendant +create sentrix guild=%s", guild.id)
            return False
        try:
            panel = await ticket_cog.get_panel_by_name(guild.id, "Support SentriX")
            if panel is None:
                panel_id = await ticket_cog.create_panel(guild.id, "Support SentriX")
            else:
                panel_id = int(panel["id"])

            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET title=?, description=?, channel_id=?, style=?, max_per_member=?, enabled=1 "
                "WHERE id=?",
                (
                    "Support SentriX",
                    "Besoin d'aide, un bug à signaler ou une question sur SentriX ? Ouvre un ticket ci-dessous.",
                    panel_channel.id,
                    "button",
                    1,
                    panel_id,
                ),
            )

            ticket_type = await ticket_cog.get_type_by_name(guild.id, "Support SentriX")
            if ticket_type is None:
                type_id = await ticket_cog.add_type(guild.id, panel_id, "Support SentriX")
            else:
                type_id = int(ticket_type["id"])
                await self.bot.db.execute("UPDATE ticket_types SET panel_id=? WHERE id=?", (panel_id, type_id))

            await self.bot.db.execute(
                "UPDATE ticket_types SET description=?, emoji=NULL, button_label=?, staff_role_id=?, "
                "category_id=?, log_channel_id=?, mention_staff=1, max_per_member=1, "
                "name_format=?, open_message=?, enabled=1 WHERE id=?",
                (
                    "Support, bug, question ou problème lié à SentriX.",
                    "Ouvrir un ticket",
                    staff_role.id,
                    tickets_category.id,
                    logs_channel.id,
                    "ticket-{pseudo}",
                    "Explique clairement ta demande. Un membre du staff SentriX prendra le relais.",
                    type_id,
                ),
            )

            panel = await ticket_cog.get_panel(panel_id)
            types = await ticket_cog.get_panel_types(panel_id)
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
                embed=ticket_cog.build_panel_embed(panel),
                view=TicketPanelView(panel, types),
            )
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET message_id=?, channel_id=? WHERE id=?",
                (message.id, panel_channel.id, panel_id),
            )
            return True
        except Exception:
            logger.exception("Création du panel Support SentriX impossible guild=%s", guild.id)
            return False

    async def _build_official_server(self, guild: discord.Guild) -> dict:
        default = guild.default_role
        me = guild.me
        if me is None:
            raise RuntimeError("Membre bot introuvable dans le serveur.")

        owner_permissions = discord.Permissions(administrator=True)
        dev_permissions = discord.Permissions(
            view_audit_log=True,
            manage_guild=True,
            manage_roles=True,
            manage_channels=True,
            manage_webhooks=True,
            manage_messages=True,
            manage_threads=True,
        )
        staff_permissions = discord.Permissions(
            kick_members=True,
            moderate_members=True,
            manage_messages=True,
            manage_threads=True,
            manage_nicknames=True,
            move_members=True,
            mute_members=True,
        )

        owner_role, owner_created = await self._ensure_role(
            guild, "Owner SentriX", color=discord.Color.from_rgb(92, 76, 210), permissions=owner_permissions
        )
        dev_role, dev_created = await self._ensure_role(
            guild, "Dev SentriX", color=discord.Color.from_rgb(82, 91, 120), permissions=dev_permissions
        )
        staff_role, staff_created = await self._ensure_role(
            guild, "Staff SentriX", color=discord.Color.from_rgb(95, 110, 145), permissions=staff_permissions
        )

        if guild.owner is not None and owner_role not in guild.owner.roles:
            try:
                await guild.owner.add_roles(owner_role, reason="Owner du serveur officiel SentriX")
            except discord.HTTPException:
                pass

        bot_full = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            manage_channels=True,
            read_message_history=True,
            connect=True,
            speak=True,
        )
        readonly = {
            default: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            owner_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            dev_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            me: bot_full,
        }
        public = {
            default: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            me: bot_full,
        }
        support_readonly = dict(readonly)
        staff_only = {
            default: discord.PermissionOverwrite(view_channel=False),
            owner_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            dev_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            me: bot_full,
        }
        dev_only = {
            default: discord.PermissionOverwrite(view_channel=False),
            owner_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            dev_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            me: bot_full,
        }
        ticket_private = {
            default: discord.PermissionOverwrite(view_channel=False),
            owner_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True),
            dev_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True),
            me: bot_full,
        }

        official, c1 = await self._ensure_category(guild, "SENTRIX — OFFICIEL")
        community, c2 = await self._ensure_category(guild, "SENTRIX — COMMUNAUTÉ")
        support, c3 = await self._ensure_category(guild, "SENTRIX — SUPPORT")
        staff, c4 = await self._ensure_category(guild, "SENTRIX — STAFF", overwrites=staff_only)
        tickets_category, c5 = await self._ensure_category(guild, "SENTRIX — TICKETS", overwrites=ticket_private)

        channels_created = 0

        async def text(category, name, topic, overwrites):
            nonlocal channels_created
            channel, created = await self._ensure_text(
                guild, category, name, topic=topic, overwrites=overwrites
            )
            channels_created += int(created)
            return channel

        welcome = await text(official, "bienvenue", "Accueil officiel des nouveaux membres du serveur SentriX.", readonly)
        rules = await text(official, "règlement", "Règles courtes et officielles de la communauté SentriX.", readonly)
        announcements = await text(official, "annonces-sentrix", "Annonces et nouveautés officielles de SentriX.", readonly)
        status = await text(official, "statut-sentrix", "État du bot, maintenances et incidents connus.", readonly)
        goodbye = await text(official, "départs", "Journal public et sobre des départs de la communauté.", readonly)

        general = await text(community, "général", "Discussion principale de la communauté SentriX.", public)
        sentrix_chat = await text(community, "sentrix-chat", "Parle directement avec SentriX ici, sans écrire +ai.", public)
        suggestions = await text(community, "suggestions", "Idées et retours pour améliorer SentriX.", public)
        animations = await text(community, "animations", "Animations officielles et rendez-vous de la communauté.", public)

        faq = await text(support, "faq", "Réponses rapides aux questions fréquentes sur SentriX.", readonly)
        ticket_panel = await text(support, "ouvrir-un-ticket", "Ouvre un ticket privé avec le staff SentriX.", support_readonly)

        staff_chat = await text(staff, "staff", "Coordination privée du staff SentriX.", staff_only)
        dev_chat = await text(staff, "dev-sentrix", "Développement, bugs techniques et suivi des versions SentriX.", dev_only)
        reports = await text(staff, "reports", "Signalements et dossiers nécessitant une vérification staff.", staff_only)
        logs = await text(staff, "logs-sentrix", "Logs utiles du bot et de la modération. Aucun spam technique dans général.", staff_only)

        _, voice_public_created = await self._ensure_voice(
            guild, community, "Communauté SentriX", overwrites=public
        )
        _, voice_staff_created = await self._ensure_voice(
            guild, staff, "Staff SentriX", overwrites=staff_only
        )

        await self._seed(
            welcome,
            "[SENTRIX-WELCOME]",
            "[SENTRIX-WELCOME]\nBienvenue sur l'espace officiel SentriX. Commence par lire #règlement, puis découvre le bot dans #sentrix-chat.",
        )
        await self._seed(
            rules,
            "[SENTRIX-RULES]",
            "[SENTRIX-RULES]\n1. Respecte les membres et le staff.\n2. Pas de spam, scam, raid ou contenu dangereux.\n3. Utilise #sentrix-chat pour discuter avec l'IA.\n4. Utilise les tickets pour les demandes privées.\n5. Les annonces et décisions staff doivent être respectées.",
        )
        await self._seed(
            sentrix_chat,
            "[SENTRIX-CHAT]",
            "[SENTRIX-CHAT]\nÉcris simplement ton message dans ce salon : SentriX te répond directement, sans +ai et sans commande spéciale.",
        )
        await self._seed(
            faq,
            "[SENTRIX-FAQ]",
            "[SENTRIX-FAQ]\nParler à SentriX : #sentrix-chat\nBesoin d'aide privée : #ouvrir-un-ticket\nNouveautés : #annonces-sentrix\nÉtat du bot : #statut-sentrix",
        )
        await self._seed(
            status,
            "[SENTRIX-STATUS]",
            "[SENTRIX-STATUS]\nSentriX est installé sur ce serveur. Les maintenances et incidents importants pourront être publiés ici.",
        )

        await self._apply_database_config(
            guild,
            owner_role=owner_role,
            staff_role=staff_role,
            welcome=welcome,
            goodbye=goodbye,
            rules=rules,
            announcements=announcements,
            suggestions=suggestions,
            sentrix_chat=sentrix_chat,
            ticket_category=tickets_category,
            logs=logs,
            reports=reports,
        )
        ticket_ready = await self._setup_ticket_panel(
            guild,
            panel_channel=ticket_panel,
            tickets_category=tickets_category,
            staff_role=staff_role,
            logs_channel=logs,
        )

        return {
            "roles_created": int(owner_created) + int(dev_created) + int(staff_created),
            "categories_created": sum((c1, c2, c3, c4, c5)),
            "channels_created": channels_created + int(voice_public_created) + int(voice_staff_created),
            "ticket_ready": ticket_ready,
            "general": general,
            "animations": animations,
            "staff_chat": staff_chat,
            "dev_chat": dev_chat,
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Dans #sentrix-chat, un message normal devient directement une conversation IA."""
        if message.author.bot or message.guild is None:
            return
        if getattr(message.channel, "name", "").casefold() != "sentrix-chat":
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

        # Les mentions et les messages commençant explicitement par "SentriX" sont déjà
        # gérés par le listener naturel du cog IA. On les laisse à ce chemin pour éviter
        # toute double réponse.
        lowered = content.casefold().lstrip()
        if self.bot.user is not None and self.bot.user in message.mentions:
            return
        if lowered.startswith(("sentrix ", "sentrix,", "sentrix:", "sentri ", "snetri ")):
            return

        ai_cog = self.bot.get_cog("Ai")
        if ai_cog is None or not hasattr(ai_cog, "send_sentrix_reply"):
            for cog in self.bot.cogs.values():
                if hasattr(cog, "send_sentrix_reply"):
                    ai_cog = cog
                    break
        if ai_cog is None or not hasattr(ai_cog, "send_sentrix_reply"):
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
            logger.exception("Réponse automatique #sentrix-chat impossible guild=%s", message.guild.id)

    @commands.group(name="create", invoke_without_command=True)
    @checks.is_owner_or_admin_for("configuration")
    async def create(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send("Utilise `+create sentrix` pour installer l'espace officiel SentriX sur ce serveur.")

    @create.command(name="sentrix")
    @checks.is_owner_or_admin_for("configuration")
    async def create_sentrix(self, ctx: commands.Context):
        guild = ctx.guild
        if guild is None:
            return await ctx.send("Cette commande doit être utilisée dans un serveur Discord.")

        me = guild.me
        if me is None or not me.guild_permissions.administrator:
            return await ctx.send(
                "SentriX doit avoir Administrateur pendant l'installation pour créer correctement les rôles, salons et permissions."
            )

        lock = self._lock_for(guild.id)
        if lock.locked():
            return await ctx.send("Une installation SentriX est déjà en cours sur ce serveur.")

        async with lock:
            previous = await self._installation(guild.id)
            if previous is not None and str(previous["template_key"] or "") == TEMPLATE_KEY:
                return await ctx.send(
                    "L'espace officiel SentriX a déjà été créé sur ce serveur. `+create sentrix` ne peut être utilisé qu'une seule fois."
                )

            progress = await ctx.send(
                "Création de l'espace officiel SentriX en cours... Peu de rôles, salons utiles uniquement, IA intégrée et support privé."
            )
            try:
                result = await self._build_official_server(guild)
                await self._mark_installed(guild.id, ctx.author.id)
                ticket_state = "prêt" if result["ticket_ready"] else "à finaliser avec +ticketsetup"
                await progress.edit(
                    content=(
                        "Espace SentriX créé. "
                        f"3 rôles maximum, 5 catégories, {result['channels_created']} nouveau(x) salon(s) créé(s) pendant cette exécution. "
                        f"Support : {ticket_state}. #sentrix-chat répond maintenant sans +ai. "
                        "Owner SentriX, Dev SentriX et Staff SentriX sont les seuls rôles SentriX ajoutés."
                    ),
                    embed=None,
                    view=None,
                )
            except discord.Forbidden:
                logger.warning("+create sentrix refusé par Discord guild=%s", guild.id, exc_info=True)
                await progress.edit(
                    content="Installation arrêtée : une permission Discord manque. Le verrou n'a pas été posé, tu peux corriger les permissions puis relancer `+create sentrix`.",
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                logger.warning("+create sentrix HTTP error guild=%s", guild.id, exc_info=True)
                await progress.edit(
                    content="Discord a interrompu l'installation. Les éléments déjà créés seront réutilisés au prochain essai et la commande reste disponible.",
                    embed=None,
                    view=None,
                )
            except Exception:
                logger.exception("Erreur +create sentrix guild=%s", guild.id)
                try:
                    await progress.edit(
                        content="Installation interrompue par une erreur technique. Aucun verrou définitif n'a été posé ; tu peux relancer après correction.",
                        embed=None,
                        view=None,
                    )
                except discord.HTTPException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CreateSentrix(bot))
