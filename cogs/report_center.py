"""Signalements SentriX : carte large Discord Components V2, prise en charge et sanctions.

Aucun signalement public ni sanction automatique. Les reportings sont opt-in,
adressés uniquement à un salon privé du staff. Les interactions persistantes
survivent aux redémarrages, et les sanctions exigent une confirmation explicite.
"""
from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.ext import commands

from cogs import setup_control_center
from services import moderation as moderation_service
from utils import log_service

logger = logging.getLogger("bot.member-reports")


def _safe(value: object, limit: int = 500) -> str:
    result = discord.utils.escape_markdown(str(value or "").strip()[:limit])
    return result.replace("@everyone", "@ everyone").replace("@here", "@ here")


def _stamp(dt) -> str:
    return f"<t:{int(dt.timestamp())}:R>" if dt else "Inconnue"


def _staff(guild: discord.Guild, user, role_id: int | None = None) -> bool:
    if not isinstance(user, discord.Member):
        return False
    p = user.guild_permissions
    return bool(
        p.administrator or p.manage_guild or p.moderate_members
        or (role_id and any(r.id == int(role_id) for r in user.roles))
    )


async def _settings(bot, guild_id: int):
    return await bot.db.fetchone(
        "SELECT * FROM member_report_settings WHERE guild_id=?", (guild_id,),
    )


class ReportReasonModal(discord.ui.Modal, title="🚨 Signaler un message"):
    def __init__(self, cog, message: discord.Message):
        super().__init__(timeout=300)
        self.cog, self.message = cog, message
        self.reason = discord.ui.TextInput(
            label="Motif du signalement", style=discord.TextStyle.paragraph,
            placeholder="Décrivez précisément le problème...",
            min_length=3, max_length=500, required=True,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.submit_report(
            interaction,
            target=self.message.author,
            reason=str(self.reason.value),
            source_channel_id=self.message.channel.id,
            source_message_id=self.message.id,
        )


class ReportSanctionModal(discord.ui.Modal):
    """Aucune sanction sans confirmation explicite et nouvelle vérification des droits."""

    def __init__(self, cog, report_id: int, action: str):
        super().__init__(title=f"Confirmer la sanction : {action}", timeout=300)
        self.cog, self.report_id, self.action = cog, report_id, action
        self.reason = discord.ui.TextInput(
            label="Raison de la sanction", style=discord.TextStyle.paragraph,
            default=f"Suite au signalement #{report_id}", max_length=350,
            min_length=5, required=True,
        )
        self.confirm = discord.ui.TextInput(
            label="Saisir CONFIRMER pour appliquer", placeholder="CONFIRMER",
            max_length=12, required=True,
        )
        self.add_item(self.reason)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction):
        if str(self.confirm.value).strip().upper() != "CONFIRMER":
            return await interaction.response.send_message(
                "Action annulée : confirmation incorrecte.", ephemeral=True,
            )
        await self.cog.execute_sanction(
            interaction, self.report_id, self.action, str(self.reason.value),
        )


class ReportReviewView(discord.ui.LayoutView):
    def __init__(self, cog, report):
        super().__init__(timeout=None)
        self.cog = cog
        self.report = dict(report)

    async def build(self):
        self.clear_items()
        r = self.report
        guild = self.cog.bot.get_guild(int(r["guild_id"]))
        target = guild.get_member(int(r["target_id"])) if guild else None
        reporter = guild.get_member(int(r["reporter_id"])) if guild else None
        created = int(r["created_at"])
        count = await self.cog.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?",
            (r["guild_id"], r["target_id"]),
        )
        sanctions = await self.cog.bot.db.fetchall(
            "SELECT action,COUNT(*) AS n FROM sanctions WHERE guild_id=? AND user_id=? "
            "GROUP BY action ORDER BY n DESC",
            (r["guild_id"], r["target_id"]),
        )
        history = " · ".join(
            f"{int(row['n'])} {row['action']}" for row in sanctions[:4]
        ) or "Aucune sanction antérieure"
        status = str(r["status"])
        if status == "pending":
            footer = f"⏳ Signalement en attente depuis <t:{created}:F> (<t:{created}:R>)"
        elif status == "claimed":
            footer = f"🟦 Pris en charge par <@{r['claimed_by']}> · <t:{int(r['updated_at'])}:R>"
        else:
            footer = f"✅ Traité par <@{r['claimed_by'] or r['reporter_id']}> · <t:{int(r['updated_at'])}:R>"
        source = (
            f"dans <#{r['source_channel_id']}>"
            if r["source_channel_id"] else "sans message associé"
        )
        card = discord.ui.Container(accent_colour=discord.Colour(0xCD7864))
        card.add_item(discord.ui.TextDisplay(
            f"## 🚨 Signalement envers <@{r['target_id']}>\n"
            f"Compte créé {_stamp(discord.utils.snowflake_time(int(r['target_id'])))}"
            f" · Arrivé sur le serveur {_stamp(target.joined_at if target else None)}\n\n"
            f"🔎 **{history}** · **{int(count['n'] if count else 0)} avertissement(s)**"
        ))
        history_button = discord.ui.Button(
            label="🔎 Voir les sanctions", style=discord.ButtonStyle.primary,
            custom_id=f"sentrix:report:history:{r['id']}",
        )
        history_button.callback = self.history
        card.add_item(discord.ui.ActionRow(history_button))
        card.add_item(discord.ui.Separator())
        card.add_item(discord.ui.TextDisplay(
            f"**Signalé par <@{r['reporter_id']}>** {source} · <t:{created}:R>\n"
            f"> {_safe(r['reason'], 500).replace(chr(10), chr(10)+'> ')}"
        ))
        if r["source_message_id"] and r["source_channel_id"]:
            url = (
                f"https://discord.com/channels/{r['guild_id']}/"
                f"{r['source_channel_id']}/{r['source_message_id']}"
            )
            card.add_item(discord.ui.ActionRow(discord.ui.Button(
                label="🔗 Message", style=discord.ButtonStyle.link, url=url,
            )))
        card.add_item(discord.ui.Separator())
        card.add_item(discord.ui.TextDisplay(f"**{footer}**"))
        if status != "resolved":
            sanction = discord.ui.Select(
                custom_id=f"sentrix:report:sanction:{r['id']}",
                placeholder="⚖️ Sanctionner le membre",
                options=[
                    discord.SelectOption(label="Avertissement", value="warn", emoji="⚠️"),
                    discord.SelectOption(label="Timeout 10 minutes", value="mute", emoji="🔇"),
                    discord.SelectOption(label="Expulsion", value="kick", emoji="🚪"),
                    discord.SelectOption(label="Bannissement", value="ban", emoji="🔨"),
                ],
            )
            sanction.callback = self.sanction
            card.add_item(discord.ui.ActionRow(sanction))
        claim = discord.ui.Button(
            label="🛡️ Prendre en charge", style=discord.ButtonStyle.primary,
            custom_id=f"sentrix:report:claim:{r['id']}", disabled=status != "pending",
        )
        claim.callback = self.claim
        resolve = discord.ui.Button(
            label="✅ Marquer comme traité", style=discord.ButtonStyle.success,
            custom_id=f"sentrix:report:resolve:{r['id']}", disabled=status == "resolved",
        )
        resolve.callback = self.resolve
        tickets = discord.ui.Button(
            label="🎫 Tickets", style=discord.ButtonStyle.secondary,
            custom_id=f"sentrix:report:tickets:{r['id']}",
        )
        tickets.callback = self.tickets
        card.add_item(discord.ui.ActionRow(claim, resolve, tickets))
        card.add_item(discord.ui.TextDisplay("-# SentriX · Dossier de signalement privé"))
        self.add_item(card)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        config = await _settings(self.cog.bot, self.report["guild_id"])
        role_id = int(config["staff_role_id"]) if config and config["staff_role_id"] else None
        if interaction.guild_id == self.report["guild_id"] and _staff(
            interaction.guild, interaction.user, role_id,
        ):
            return True
        await interaction.response.send_message(
            "Ces actions sont réservées à l'équipe de modération.", ephemeral=True,
        )
        return False

    async def history(self, interaction):
        rows = await self.cog.bot.db.get_sanction_history(
            self.report["guild_id"], self.report["target_id"], limit=10,
        )
        lines = [
            f"**#{x['case_number']} · {_safe(x['action'], 20)}** · "
            f"<t:{int(x['created_at'])}:R> · {_safe(x['reason'], 140)}"
            for x in rows
        ]
        await interaction.response.send_message(
            f"📜 **Sanctions de <@{self.report['target_id']}>**\n"
            + ("\n".join(lines) if lines else "Aucune sanction enregistrée."),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    async def claim(self, interaction):
        cur = await self.cog.bot.db.execute(
            "UPDATE member_reports SET status='claimed',claimed_by=?,updated_at=? "
            "WHERE id=? AND guild_id=? AND status='pending'",
            (interaction.user.id, int(time.time()), self.report["id"], interaction.guild_id),
        )
        if int(cur.rowcount or 0) != 1:
            return await interaction.response.send_message(
                "Ce dossier est déjà pris en charge ou terminé.", ephemeral=True,
            )
        await self.cog.refresh_card(interaction, self.report["id"])

    async def resolve(self, interaction):
        r = await self.cog.get_report(self.report["id"])
        if not r or r["status"] == "resolved":
            return await interaction.response.send_message("Dossier déjà terminé.", ephemeral=True)
        if r["claimed_by"] and r["claimed_by"] != interaction.user.id and not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
        ):
            return await interaction.response.send_message(
                "Ce dossier est pris en charge par un autre modérateur.", ephemeral=True,
            )
        cur = await self.cog.bot.db.execute(
            "UPDATE member_reports SET status='resolved',"
            "claimed_by=COALESCE(claimed_by,?),updated_at=? WHERE id=? AND status!='resolved'",
            (interaction.user.id, int(time.time()), r["id"]),
        )
        if int(cur.rowcount or 0) != 1:
            return await interaction.response.send_message("Dossier déjà traité.", ephemeral=True)
        await self.cog.refresh_card(interaction, r["id"])

    async def sanction(self, interaction):
        r = await self.cog.get_report(self.report["id"])
        if not r or r["status"] == "resolved":
            return await interaction.response.send_message("Dossier déjà traité.", ephemeral=True)
        action = str(interaction.data["values"][0])
        if action not in {"warn", "mute", "kick", "ban"}:
            return await interaction.response.send_message("Action invalide.", ephemeral=True)
        await interaction.response.send_modal(ReportSanctionModal(self.cog, r["id"], action))

    async def tickets(self, interaction):
        row = await self.cog.bot.db.fetchone(
            "SELECT channel_id,message_id FROM ticket_panels_v2 "
            "WHERE guild_id=? AND enabled=1 AND message_id IS NOT NULL LIMIT 1",
            (interaction.guild_id,),
        )
        if row:
            link = (
                f"https://discord.com/channels/{interaction.guild_id}/"
                f"{row['channel_id']}/{row['message_id']}"
            )
            return await interaction.response.send_message(
                f"🎫 Panneau de tickets du serveur : {link}", ephemeral=True,
            )
        await interaction.response.send_message(
            "Aucun panneau de tickets actif. Ouvrez /config tickets pour le configurer.",
            ephemeral=True,
        )


class ReportSettingsView(discord.ui.LayoutView):
    def __init__(self, cog, guild, owner_id):
        super().__init__(timeout=900)
        self.cog, self.guild, self.owner_id = cog, guild, owner_id

    async def interaction_check(self, interaction):
        if (interaction.user.id == self.owner_id
                and await setup_control_center._can_setup(self.cog.bot, interaction.user, interaction.guild)):
            return True
        await interaction.response.send_message(
            "Configuration réservée au responsable ayant ouvert ce panneau.", ephemeral=True,
        )
        return False

    async def refresh(self, interaction):
        await self.build()
        await interaction.response.edit_message(view=self)

    async def build(self):
        self.clear_items()
        row = await _settings(self.cog.bot, self.guild.id)
        enabled = bool(row and row["enabled"])
        notify = bool(row and row["notify_staff"])
        cid = int(row["channel_id"]) if row and row["channel_id"] else None
        rid = int(row["staff_role_id"]) if row and row["staff_role_id"] else None
        channel = self.guild.get_channel(cid) if cid else None
        role = self.guild.get_role(rid) if rid else None
        reports = await self.cog.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM member_reports WHERE guild_id=? AND status!='resolved'",
            (self.guild.id,),
        )
        c = discord.ui.Container(accent_colour=discord.Colour(0xCD7864))
        c.add_item(discord.ui.TextDisplay(
            "## 🚨 SentriX · Centre des signalements\n"
            "Recevez des fiches larges et gérez chaque dossier dans Discord."
        ))
        c.add_item(discord.ui.Separator())
        c.add_item(discord.ui.TextDisplay(
            f"**Système : {'🟢 ACTIVÉ' if enabled else '⚪ DÉSACTIVÉ'}**\n"
            f"📍 Salon privé : {channel.mention if channel else '**Non configuré**'}\n"
            f"👮 Rôle staff : {role.mention if role else 'Permissions de modération natives'}\n"
            f"🔔 Mention du staff : **{'Oui' if notify else 'Non'}**\n"
            f"📨 Dossiers en attente : **{int(reports['n'] if reports else 0)}**"
        ))
        toggle = discord.ui.Button(
            label="Désactiver les signalements" if enabled else "Activer les signalements",
            style=discord.ButtonStyle.secondary,
        )
        toggle.callback = self.toggle
        notify_button = discord.ui.Button(
            label="🔕 Sans ping" if notify else "🔔 Notifier le staff",
            style=discord.ButtonStyle.secondary,
        )
        notify_button.callback = self.toggle_notify
        c.add_item(discord.ui.ActionRow(toggle, notify_button))
        c.add_item(discord.ui.TextDisplay("**📍 Choisissez un salon STAFF privé**"))
        choose = discord.ui.ChannelSelect(
            placeholder="Salon de réception des signalements",
            channel_types=[discord.ChannelType.text], min_values=0, max_values=1,
        )
        choose.callback = self.select_channel
        c.add_item(discord.ui.ActionRow(choose))
        c.add_item(discord.ui.TextDisplay("**👮 Rôle du staff pouvant gérer les dossiers**"))
        roles = discord.ui.RoleSelect(
            placeholder="Rôle modération (facultatif)",
            min_values=0, max_values=1,
        )
        roles.callback = self.select_role
        c.add_item(discord.ui.ActionRow(roles))
        c.add_item(discord.ui.TextDisplay(
            "-# Après activation : clic droit sur un message → Applications → Signaler ce message. "
            "10 minutes entre deux signalements par membre. "
            "Aucune sanction ne part sans confirmation d'un modérateur."
        ))
        self.add_item(c)

    async def toggle(self, interaction):
        row = await _settings(self.cog.bot, self.guild.id)
        if not row or not row["channel_id"] or not self.cog.valid_private_channel(
            self.guild, self.guild.get_channel(int(row["channel_id"])),
        ):
            return await interaction.response.send_message(
                "Choisissez d'abord un salon staff privé accessible à SentriX.",
                ephemeral=True,
            )
        await self.cog.bot.db.execute(
            "UPDATE member_report_settings SET enabled=? WHERE guild_id=?",
            (0 if row["enabled"] else 1, self.guild.id),
        )
        await self.refresh(interaction)

    async def toggle_notify(self, interaction):
        row = await _settings(self.cog.bot, self.guild.id)
        await self.cog.bot.db.execute(
            "INSERT INTO member_report_settings (guild_id,notify_staff) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET notify_staff=excluded.notify_staff",
            (self.guild.id, 0 if row and row["notify_staff"] else 1),
        )
        await self.refresh(interaction)

    async def select_channel(self, interaction):
        values = interaction.data.get("values", [])
        channel = self.guild.get_channel(int(values[0])) if values else None
        if channel and not self.cog.valid_private_channel(self.guild, channel):
            return await interaction.response.send_message(
                "Ce salon doit être privé (invisible pour @everyone) et permettre à SentriX d'envoyer des messages.",
                ephemeral=True,
            )
        await self.cog.bot.db.execute(
            "INSERT INTO member_report_settings (guild_id,channel_id,enabled) VALUES (?,?,0) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,enabled=0",
            (self.guild.id, channel.id if channel else None),
        )
        await self.refresh(interaction)

    async def select_role(self, interaction):
        values = interaction.data.get("values", [])
        role = self.guild.get_role(int(values[0])) if values else None
        if role and (role.is_default() or role.managed):
            return await interaction.response.send_message(
                "Rôle invalide : sélectionnez un rôle de modération ordinaire.",
                ephemeral=True,
            )
        await self.cog.bot.db.execute(
            "INSERT INTO member_report_settings (guild_id,staff_role_id) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET staff_role_id=excluded.staff_role_id",
            (self.guild.id, role.id if role else None),
        )
        await self.refresh(interaction)


class ReportCenter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}
        self._message_menu = app_commands.ContextMenu(
            name="Signaler ce message", callback=self.context_report,
        )

    async def cog_load(self):
        await self.ensure_schema()
        if self.bot.tree.get_command(
            "Signaler ce message", type=discord.AppCommandType.message
        ) is None:
            self.bot.tree.add_command(self._message_menu)
        rows = await self.bot.db.fetchall(
            "SELECT * FROM member_reports WHERE status!='resolved' AND staff_message_id IS NOT NULL"
        )
        for r in rows:
            try:
                v = ReportReviewView(self, r)
                await v.build()
                self.bot.add_view(v, message_id=int(r["staff_message_id"]))
            except Exception:
                logger.exception("Impossible de restaurer le dossier #%s.", r["id"])

    async def cog_unload(self):
        self.bot.tree.remove_command(
            "Signaler ce message", type=discord.AppCommandType.message
        )

    async def ensure_schema(self):
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS member_report_settings("
            "guild_id INTEGER PRIMARY KEY,channel_id INTEGER,enabled INTEGER NOT NULL DEFAULT 0,"
            "staff_role_id INTEGER,notify_staff INTEGER NOT NULL DEFAULT 0)"
        )
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS member_reports("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,"
            "target_id INTEGER NOT NULL,reporter_id INTEGER NOT NULL,reason TEXT NOT NULL,"
            "source_channel_id INTEGER,source_message_id INTEGER,staff_channel_id INTEGER NOT NULL,"
            "staff_message_id INTEGER,status TEXT NOT NULL DEFAULT 'pending',"
            "claimed_by INTEGER,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)"
        )
        await self.bot.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_member_reports_recent "
            "ON member_reports(guild_id,reporter_id,created_at)"
        )

    @staticmethod
    def valid_private_channel(guild, channel) -> bool:
        if not isinstance(channel, discord.TextChannel):
            return False
        if channel.permissions_for(guild.default_role).view_channel:
            return False
        me = guild.me
        if me is None:
            return False
        permissions = channel.permissions_for(me)
        return bool(
            permissions.view_channel and permissions.send_messages
            and permissions.embed_links
        )

    async def open_config(self, interaction):
        if not await setup_control_center._can_setup(
            self.bot, interaction.user, interaction.guild
        ):
            return await interaction.response.send_message(
                "Permission Gérer le serveur requise.", ephemeral=True,
            )
        v = ReportSettingsView(self, interaction.guild, interaction.user.id)
        await v.build()
        await interaction.response.send_message(view=v, ephemeral=True)

    async def context_report(self, interaction: discord.Interaction, message: discord.Message):
        conf = await _settings(self.bot, interaction.guild_id)
        if not conf or not conf["enabled"]:
            return await interaction.response.send_message(
                "Les signalements ne sont pas activés sur ce serveur.", ephemeral=True,
            )
        await interaction.response.send_modal(ReportReasonModal(self, message))

    async def get_report(self, report_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM member_reports WHERE id=?", (int(report_id),),
        )

    async def submit_report(
        self, interaction, *, target, reason, source_channel_id=None, source_message_id=None,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Serveur requis.", ephemeral=True)
        conf = await _settings(self.bot, guild.id)
        channel = (
            guild.get_channel(int(conf["channel_id"]))
            if conf and conf["channel_id"] else None
        )
        if not conf or not conf["enabled"] or not self.valid_private_channel(guild, channel):
            return await interaction.response.send_message(
                "Le salon de signalements est indisponible ou n'est plus privé. Contactez le staff.",
                ephemeral=True,
            )
        reason = reason.strip()
        if not 3 <= len(reason) <= 500:
            return await interaction.response.send_message("Motif invalide (3 à 500 caractères).", ephemeral=True)
        if target.id == interaction.user.id:
            return await interaction.response.send_message(
                "Vous ne pouvez pas vous signaler vous-même.", ephemeral=True,
            )
        recent = await self.bot.db.fetchone(
            "SELECT id FROM member_reports WHERE guild_id=? AND reporter_id=? AND created_at>? "
            "ORDER BY id DESC LIMIT 1",
            (guild.id, interaction.user.id, int(time.time()) - 600),
        )
        if recent and not _staff(guild, interaction.user):
            return await interaction.response.send_message(
                "Un seul signalement toutes les 10 minutes. Le staff a reçu le précédent.",
                ephemeral=True,
            )
        ts = int(time.time())
        cursor = await self.bot.db.execute(
            "INSERT INTO member_reports "
            "(guild_id,target_id,reporter_id,reason,source_channel_id,source_message_id,"
            "staff_channel_id,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,'pending',?,?)",
            (
                guild.id, target.id, interaction.user.id, reason,
                source_channel_id, source_message_id, channel.id, ts, ts,
            ),
        )
        report_id = int(cursor.lastrowid)
        row = await self.get_report(report_id)
        view = ReportReviewView(self, row)
        await view.build()
        role = guild.get_role(int(conf["staff_role_id"])) if conf["staff_role_id"] else None
        ping = role.mention if role and conf["notify_staff"] else None
        allowed = discord.AllowedMentions(
            everyone=False, users=False, roles=[role] if ping else False
        )
        try:
            sent = await channel.send(
                content=ping, view=view, allowed_mentions=allowed,
            )
        except discord.HTTPException:
            await self.bot.db.execute("DELETE FROM member_reports WHERE id=?", (report_id,))
            logger.exception("Envoi d'un signalement refusé guild=%s", guild.id)
            return await interaction.response.send_message(
                "Impossible de transmettre le signalement au salon staff.", ephemeral=True,
            )
        await self.bot.db.execute(
            "UPDATE member_reports SET staff_message_id=? WHERE id=?",
            (sent.id, report_id),
        )
        await interaction.response.send_message(
            f"✅ Signalement **#{report_id}** transmis au staff en privé.",
            ephemeral=True,
        )

    async def refresh_card(self, interaction, report_id: int):
        r = await self.get_report(report_id)
        view = ReportReviewView(self, r)
        await view.build()
        await interaction.response.edit_message(view=view)

    async def execute_sanction(self, interaction, report_id: int, action: str, reason: str):
        if action not in {"warn", "mute", "kick", "ban"}:
            return await interaction.response.send_message("Sanction inconnue.", ephemeral=True)
        r = await self.get_report(report_id)
        if r is None or r["guild_id"] != interaction.guild_id or r["status"] == "resolved":
            return await interaction.response.send_message("Dossier indisponible ou déjà traité.", ephemeral=True)
        settings = await _settings(self.bot, r["guild_id"])
        role_id = int(settings["staff_role_id"]) if settings and settings["staff_role_id"] else None
        if not _staff(interaction.guild, interaction.user, role_id):
            return await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
        p = interaction.user.guild_permissions
        permission = {
            "warn": p.moderate_members,
            "mute": p.moderate_members,
            "kick": p.kick_members,
            "ban": p.ban_members,
        }[action]
        if not (permission or p.administrator):
            return await interaction.response.send_message(
                "Cette sanction nécessite les permissions Discord adaptées.", ephemeral=True,
            )
        guild = interaction.guild
        target = guild.get_member(int(r["target_id"]))
        if target is None:
            return await interaction.response.send_message(
                "Le membre n'est plus sur le serveur. Aucune sanction automatique appliquée.",
                ephemeral=True,
            )
        me = guild.me
        required_bot = {
            "warn": "moderate_members",
            "mute": "moderate_members",
            "kick": "kick_members",
            "ban": "ban_members",
        }[action]
        if not me or not getattr(me.guild_permissions, required_bot, False):
            return await interaction.response.send_message(
                "SentriX ne dispose pas de la permission nécessaire.", ephemeral=True,
            )
        lock = self._locks.setdefault(report_id, asyncio.Lock())
        async with lock:
            r = await self.get_report(report_id)
            if not r or r["status"] == "resolved":
                return await interaction.response.send_message(
                    "Dossier déjà terminé : action annulée.", ephemeral=True,
                )
            if r["claimed_by"] and r["claimed_by"] != interaction.user.id and not (
                p.administrator or p.manage_guild
            ):
                return await interaction.response.send_message(
                    "Dossier pris en charge par un autre membre du staff.", ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True, thinking=True)
            moderation_cog = self.bot.get_cog("Moderation")
            conf = await self.bot.db.get_guild_config(guild.id)
            dm_text = None
            if moderation_cog:
                template = await moderation_cog._get_sanction_dm_template(guild.id, action)
                if template:
                    dm_text = moderation_cog._render_sanction_dm_text(
                        template, target=target, guild=guild, reason=reason,
                        duration_seconds=600 if action == "mute" else None,
                        actor=interaction.user,
                        action_label=moderation_cog.DM_ACTION_LABELS[action],
                    )
            try:
                if action == "warn":
                    warn_role = guild.get_role(conf["warn_role"]) if conf and conf["warn_role"] else None
                    # Pas de ban surprise via signalement : le staff applique uniquement
                    # la sanction confirmée dans la modale. /warn conserve son escalade.
                    result = await moderation_service.warn(
                        self.bot, guild=guild, actor=interaction.user,
                        target=target, reason=reason, dm_text=dm_text,
                        warn_role=warn_role, ban_threshold=0,
                    )
                elif action == "mute":
                    result = await moderation_service.mute(
                        self.bot, guild=guild, actor=interaction.user,
                        target=target, reason=reason, duree="10m",
                        render_dm_text=lambda seconds: dm_text,
                    )
                elif action == "kick":
                    result = await moderation_service.kick(
                        self.bot, guild=guild, actor=interaction.user,
                        target=target, reason=reason, dm_text=dm_text,
                    )
                else:
                    result = await moderation_service.ban(
                        self.bot, guild=guild, actor=interaction.user,
                        target=target, reason=reason, dm_text=dm_text,
                        delete_message_seconds=0,
                    )
            except (discord.HTTPException, discord.Forbidden) as exc:
                logger.warning("Sanction refusée report=%s action=%s : %s", report_id, action, exc)
                return await interaction.followup.send(
                    "Discord a refusé la sanction. Vérifiez la hiérarchie et les permissions.",
                    ephemeral=True,
                )
            if not result.executed:
                return await interaction.followup.send(
                    _safe(getattr(result, "rejection_reason", None) or getattr(result, "hierarchy_error", None) or "Sanction non autorisée.", 300),
                    ephemeral=True,
                )
            await self.bot.db.execute(
                "UPDATE member_reports SET status='resolved',claimed_by=COALESCE(claimed_by,?),"
                "updated_at=? WHERE id=? AND status!='resolved'",
                (interaction.user.id, int(time.time()), report_id),
            )
            if moderation_cog:
                try:
                    ctx = SimpleNamespace(guild=guild, author=interaction.user)
                    await moderation_cog.log_sanction(
                        ctx, action, target, reason,
                        duration_seconds=600 if action == "mute" else None,
                        case_number=result.case_number,
                    )
                except Exception:
                    logger.exception("Log secondaire sanction report=%s impossible", report_id)
            if r["staff_message_id"]:
                report_channel = guild.get_channel(int(r["staff_channel_id"]))
                if report_channel:
                    try:
                        original = await report_channel.fetch_message(int(r["staff_message_id"]))
                        updated = await self.get_report(report_id)
                        view = ReportReviewView(self, updated)
                        await view.build()
                        await original.edit(view=view)
                    except discord.HTTPException:
                        logger.warning("Carte du dossier #%s non actualisée.", report_id)
            await interaction.followup.send(
                f"✅ {action.upper()} appliqué et signalement #{report_id} traité.",
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(ReportCenter(bot))
