"""Créateur du serveur officiel SentriX : +create sentrix.

Structure volontairement courte et propre : informations officielles, communauté,
conversation IA native, support/tickets et espace staff. Aucun template Discord générique
et seulement trois rôles SentriX.
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
CORE_AUTOMOD = ("antispam", "antiinvite", "antimention", "antiraid", "antiscam")

INSTALL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sentrix_server_installations (
    guild_id INTEGER PRIMARY KEY,
    installed_at INTEGER NOT NULL,
    installed_by INTEGER NOT NULL,
    template_key TEXT NOT NULL DEFAULT 'sentrix-official-v2'
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

    async def _role(self, guild, name, color, permissions):
        role = discord.utils.get(guild.roles, name=name)
        if role:
            try:
                await role.edit(color=color, permissions=permissions, hoist=True,
                                reason="Configuration officielle SentriX")
            except discord.HTTPException:
                pass
            return role, False
        role = await guild.create_role(
            name=name, color=color, permissions=permissions, hoist=True,
            mentionable=False, reason="Configuration officielle SentriX",
        )
        return role, True

    async def _category(self, guild, name, overwrites=None):
        category = discord.utils.get(guild.categories, name=name)
        if category:
            if overwrites:
                try:
                    await category.edit(overwrites=overwrites, reason="Configuration officielle SentriX")
                except discord.HTTPException:
                    pass
            return category, False
        return await guild.create_category(
            name, overwrites=overwrites or {}, reason="Configuration officielle SentriX"
        ), True

    async def _text(self, guild, category, name, topic, overwrites):
        channel = discord.utils.get(guild.text_channels, name=name)
        if channel:
            try:
                await channel.edit(category=category, topic=topic[:1024], overwrites=overwrites,
                                   reason="Configuration officielle SentriX")
            except discord.HTTPException:
                pass
            return channel, False
        return await guild.create_text_channel(
            name, category=category, topic=topic[:1024], overwrites=overwrites,
            reason="Configuration officielle SentriX",
        ), True

    async def _voice(self, guild, category, name, overwrites):
        channel = discord.utils.get(guild.voice_channels, name=name)
        if channel:
            try:
                await channel.edit(category=category, overwrites=overwrites,
                                   reason="Configuration officielle SentriX")
            except discord.HTTPException:
                pass
            return channel, False
        return await guild.create_voice_channel(
            name, category=category, overwrites=overwrites,
            reason="Configuration officielle SentriX",
        ), True

    async def _seed(self, channel: discord.TextChannel, marker: str, content: str):
        try:
            async for msg in channel.history(limit=30):
                if self.bot.user and msg.author.id == self.bot.user.id and marker in (msg.content or ""):
                    return
        except discord.HTTPException:
            pass
        await channel.send(content)

    async def _configure_database(
        self, guild, owner_role, staff_role, welcome, goodbye, rules, announcements,
        suggestions, sentrix_chat, tickets_category, logs, reports,
    ):
        await self.bot.db.ensure_guild(guild.id)
        await self.bot.db.execute(
            "UPDATE guild_config SET welcome_channel=?,welcome_message=?,goodbye_channel=?,"
            "goodbye_message=?,rules_channel=?,announce_channel=?,suggest_channel=?,"
            "bot_commands_channel=?,ticket_category=?,ticket_log_channel=?,log_channel=?,"
            "log_messages=?,log_members=?,log_moderation=?,log_automod=?,error_channel=?,"
            "report_channel=?,mod_role=?,admin_role=?,security_level=? WHERE guild_id=?",
            (
                welcome.id,
                "Bienvenue {member} sur {server}. Lis le règlement puis découvre SentriX dans #sentrix-chat.",
                goodbye.id,
                "{member} a quitté {server}.",
                rules.id, announcements.id, suggestions.id, sentrix_chat.id,
                tickets_category.id, logs.id, logs.id, logs.id, logs.id, logs.id, logs.id,
                logs.id, reports.id, staff_role.id, owner_role.id, "moyen", guild.id,
            ),
        )
        for field in CORE_AUTOMOD:
            try:
                await self.bot.db.set_automod(guild.id, field, 1)
            except Exception:
                logger.warning("AutoMod %s non activé pendant +create sentrix", field, exc_info=True)

    async def _ticket_panel(self, guild, panel_channel, tickets_category, staff_role, logs_channel):
        """Crée/réutilise un vrai panel du système Tickets v2 existant."""
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
                    "Besoin d'aide, un bug à signaler ou une question sur SentriX ? Ouvre un ticket ci-dessous.",
                    panel_channel.id, "button", 1, panel_id,
                ),
            )

            ticket_type = await cog.get_type_by_name(guild.id, "Support SentriX")
            type_id = int(ticket_type["id"]) if ticket_type else await cog.add_type(
                guild.id, panel_id, "Support SentriX"
            )
            await self.bot.db.execute("UPDATE ticket_types SET panel_id=? WHERE id=?", (panel_id, type_id))
            await self.bot.db.execute(
                "UPDATE ticket_types SET description=?,emoji=NULL,button_label=?,staff_role_id=?,"
                "category_id=?,log_channel_id=?,mention_staff=1,max_per_member=1,name_format=?,"
                "open_message=? WHERE id=?",
                (
                    "Support, bug, question ou problème lié à SentriX.",
                    "Ouvrir un ticket", staff_role.id, tickets_category.id, logs_channel.id,
                    "ticket-{pseudo}",
                    "Explique clairement ta demande. Un membre du staff SentriX prendra le relais.",
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
            logger.exception("Panel Support SentriX impossible guild=%s", guild.id)
            return False

    async def _build(self, guild: discord.Guild):
        default, me = guild.default_role, guild.me
        if me is None:
            raise RuntimeError("SentriX n'est pas présent comme membre du serveur.")

        owner_role, r1 = await self._role(
            guild, "Owner SentriX", discord.Color.from_rgb(92, 76, 210),
            discord.Permissions(administrator=True),
        )
        dev_role, r2 = await self._role(
            guild, "Dev SentriX", discord.Color.from_rgb(82, 91, 120),
            discord.Permissions(view_audit_log=True, manage_guild=True, manage_roles=True,
                                manage_channels=True, manage_webhooks=True,
                                manage_messages=True, manage_threads=True),
        )
        staff_role, r3 = await self._role(
            guild, "Staff SentriX", discord.Color.from_rgb(95, 110, 145),
            discord.Permissions(kick_members=True, moderate_members=True, manage_messages=True,
                                manage_threads=True, manage_nicknames=True, move_members=True,
                                mute_members=True),
        )
        if guild.owner and owner_role not in guild.owner.roles:
            try:
                await guild.owner.add_roles(owner_role, reason="Owner du serveur SentriX")
            except discord.HTTPException:
                pass

        bot_full = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_messages=True, manage_channels=True,
            read_message_history=True, connect=True, speak=True,
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

        official, c1 = await self._category(guild, "SENTRIX — OFFICIEL")
        community, c2 = await self._category(guild, "SENTRIX — COMMUNAUTÉ")
        support, c3 = await self._category(guild, "SENTRIX — SUPPORT")
        staff, c4 = await self._category(guild, "SENTRIX — STAFF", staff_only)
        tickets, c5 = await self._category(guild, "SENTRIX — TICKETS", ticket_private)
        created = 0

        async def text(category, name, topic, perms):
            nonlocal created
            channel, is_new = await self._text(guild, category, name, topic, perms)
            created += int(is_new)
            return channel

        welcome = await text(official, "bienvenue", "Accueil officiel des nouveaux membres SentriX.", readonly)
        rules = await text(official, "règlement", "Règles officielles de la communauté SentriX.", readonly)
        announcements = await text(official, "annonces-sentrix", "Nouveautés et annonces officielles SentriX.", readonly)
        status = await text(official, "statut-sentrix", "État du bot, maintenances et incidents.", readonly)
        goodbye = await text(official, "départs", "Départs de la communauté SentriX.", readonly)

        await text(community, "général", "Discussion principale de la communauté.", public)
        sentrix_chat = await text(community, "sentrix-chat", "Parle directement avec SentriX sans +ai.", public)
        suggestions = await text(community, "suggestions", "Idées et retours pour améliorer SentriX.", public)
        await text(community, "animations", "Animations et rendez-vous SentriX.", public)

        faq = await text(support, "faq", "Questions fréquentes sur SentriX.", readonly)
        ticket_channel = await text(support, "ouvrir-un-ticket", "Support privé SentriX.", readonly)

        await text(staff, "staff", "Coordination privée du staff SentriX.", staff_only)
        await text(staff, "dev-sentrix", "Développement, bugs et versions SentriX.", dev_only)
        reports = await text(staff, "reports", "Signalements à traiter par le staff.", staff_only)
        logs = await text(staff, "logs-sentrix", "Logs utiles sans pollution du général.", staff_only)

        _, v1 = await self._voice(guild, community, "Communauté SentriX", public)
        _, v2 = await self._voice(guild, staff, "Staff SentriX", staff_only)
        created += int(v1) + int(v2)

        await self._seed(welcome, "[SENTRIX-WELCOME]",
                         "[SENTRIX-WELCOME]\nBienvenue sur l'espace officiel SentriX. Lis #règlement puis découvre le bot dans #sentrix-chat.")
        await self._seed(rules, "[SENTRIX-RULES]",
                         "[SENTRIX-RULES]\n1. Respecte les membres et le staff.\n2. Pas de spam, scam, raid ou contenu dangereux.\n3. Utilise #sentrix-chat pour discuter avec l'IA.\n4. Utilise les tickets pour les demandes privées.\n5. Les annonces et décisions staff doivent être respectées.")
        await self._seed(sentrix_chat, "[SENTRIX-CHAT]",
                         "[SENTRIX-CHAT]\nÉcris simplement ton message ici : SentriX te répond directement, sans +ai.")
        await self._seed(faq, "[SENTRIX-FAQ]",
                         "[SENTRIX-FAQ]\nParler à SentriX : #sentrix-chat\nAide privée : #ouvrir-un-ticket\nNouveautés : #annonces-sentrix\nÉtat du bot : #statut-sentrix")
        await self._seed(status, "[SENTRIX-STATUS]",
                         "[SENTRIX-STATUS]\nSentriX est installé. Les maintenances et incidents importants seront publiés ici.")

        await self._configure_database(
            guild, owner_role, staff_role, welcome, goodbye, rules, announcements,
            suggestions, sentrix_chat, tickets, logs, reports,
        )
        ticket_ready = await self._ticket_panel(guild, ticket_channel, tickets, staff_role, logs)
        return {
            "roles_created": int(r1) + int(r2) + int(r3),
            "categories_created": int(c1) + int(c2) + int(c3) + int(c4) + int(c5),
            "channels_created": created,
            "ticket_ready": ticket_ready,
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Tout message normal dans #sentrix-chat devient une demande IA."""
        if message.author.bot or not message.guild:
            return
        if getattr(message.channel, "name", "").casefold() != "sentrix-chat":
            return
        content = (message.content or "").strip()
        if not content:
            return
        prefix = self.bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX) \
            if hasattr(self.bot, "prefix_cache") else config.DEFAULT_PREFIX
        if content.startswith(prefix):
            return

        lowered = content.casefold().lstrip()
        if self.bot.user and self.bot.user in message.mentions:
            return
        if lowered.startswith(("sentrix ", "sentrix,", "sentrix:", "sentri ", "snetri ")):
            return

        ai_cog = self.bot.get_cog("Ai")
        if ai_cog is None or not hasattr(ai_cog, "send_sentrix_reply"):
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
                return await ctx.send("L'espace officiel SentriX a déjà été créé sur ce serveur.")

            progress = await ctx.send(
                "Création de l'espace officiel SentriX en cours : structure courte, IA intégrée et support privé."
            )
            try:
                result = await self._build(guild)
                await self._mark_installed(guild.id, ctx.author.id)
                support = "prêt" if result["ticket_ready"] else "à finaliser avec +ticketsetup"
                await progress.edit(
                    content=(
                        "Espace SentriX créé. 3 rôles SentriX seulement : Owner, Dev et Staff. "
                        f"5 catégories et {result['channels_created']} nouveau(x) salon(s) créé(s) pendant cette exécution. "
                        f"Support {support}. Dans #sentrix-chat, les membres parlent directement avec SentriX sans +ai."
                    ), embed=None, view=None,
                )
            except discord.Forbidden:
                logger.warning("+create sentrix refusé guild=%s", guild.id, exc_info=True)
                await progress.edit(content="Installation arrêtée : une permission Discord manque. Aucun verrou définitif n'a été posé.", embed=None, view=None)
            except discord.HTTPException:
                logger.warning("+create sentrix HTTP guild=%s", guild.id, exc_info=True)
                await progress.edit(content="Discord a interrompu l'installation. Les éléments déjà créés seront réutilisés au prochain essai.", embed=None, view=None)
            except Exception:
                logger.exception("Erreur +create sentrix guild=%s", guild.id)
                try:
                    await progress.edit(content="Installation interrompue par une erreur technique. Aucun verrou définitif n'a été posé.", embed=None, view=None)
                except discord.HTTPException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CreateSentrix(bot))
