"""SentriX V17 — tickets et journalisation avancée."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from types import MethodType

import discord
from discord.ext import commands

from database.db import now
from utils import checks, embeds, helpers, log_service
from .v17_shared import ensure_schema, register_command_policy, safe_discord_call, state

logger = logging.getLogger("bot.v17-tickets-logs")
LOG_BATCH_DELAY = 2.2
LOG_BATCH_THRESHOLD = 3
LOG_CACHE_TTL = 10.0

EVENT_TITLES = {
    "Message supprimé": "message_delete",
    "Message modifié": "message_edit",
    "Membre arrivé": "member_join",
    "Membre parti": "member_leave",
    "Rôles d'un membre modifiés": "member_roles",
    "Timeout modifié": "member_timeout",
    "Membre banni": "member_ban",
    "Membre débanni": "member_unban",
    "Activité vocale": "voice_activity",
    "Salon créé": "channel_create",
    "Salon supprimé": "channel_delete",
    "Salon modifié": "channel_update",
    "Rôle créé": "role_create",
    "Rôle supprimé": "role_delete",
    "Rôle modifié": "role_update",
    "Serveur modifié": "guild_update",
}
EVENT_LABELS = {
    "message_delete": "Messages supprimés",
    "message_edit": "Messages modifiés",
    "member_join": "Arrivées",
    "member_leave": "Départs",
    "member_roles": "Rôles des membres",
    "member_timeout": "Timeouts",
    "member_ban": "Bannissements",
    "member_unban": "Débannissements",
    "voice_activity": "Activité vocale",
    "channel_create": "Créations de salons",
    "channel_delete": "Suppressions de salons",
    "channel_update": "Modifications de salons",
    "role_create": "Créations de rôles",
    "role_delete": "Suppressions de rôles",
    "role_update": "Modifications de rôles",
    "guild_update": "Modifications du serveur",
}
GROUPABLE = {"channel_create", "channel_delete", "member_ban", "member_unban"}
AUDIT_ACTIONS = {
    "channel_create": discord.AuditLogAction.channel_create,
    "channel_delete": discord.AuditLogAction.channel_delete,
    "member_ban": discord.AuditLogAction.ban,
    "member_unban": discord.AuditLogAction.unban,
}
GROUP_TITLES = {
    "channel_create": "Création de salons",
    "channel_delete": "Suppression de salons",
    "member_ban": "Bannissements",
    "member_unban": "Débannissements",
}


def _target_id(embed: discord.Embed) -> int | None:
    footer = str(getattr(getattr(embed, "footer", None), "text", "") or "")
    match = re.search(r"(\d{15,22})", footer)
    if match:
        return int(match.group(1))
    desc = str(embed.description or "")
    match = re.search(r"<@!?(\d{15,22})>|<@&(\d{15,22})>|<#(\d{15,22})>", desc)
    if match:
        return int(next(value for value in match.groups() if value))
    return None


def _event_key(embed: discord.Embed) -> str | None:
    return EVENT_TITLES.get(str(embed.title or ""))


async def _event_enabled(bot, guild_id: int, event_key: str) -> bool:
    runtime = state(bot)
    cache = runtime.setdefault("v17_log_event_cache", {})
    key = (int(guild_id), str(event_key))
    item = cache.get(key)
    mono = time.monotonic()
    if item is not None and mono - float(item[0]) <= LOG_CACHE_TTL:
        return bool(item[1])
    row = await bot.db.fetchone(
        "SELECT enabled FROM v17_log_event_settings WHERE guild_id=? AND event_key=?",
        key,
    )
    value = True if row is None else bool(row["enabled"])
    cache[key] = (mono, value)
    return value


def _invalidate_event_cache(bot, guild_id: int, event_key: str | None = None) -> None:
    cache = state(bot).setdefault("v17_log_event_cache", {})
    gid = int(guild_id)
    if event_key is not None:
        cache.pop((gid, str(event_key)), None)
        return
    for key in [key for key in cache if key[0] == gid]:
        cache.pop(key, None)


async def _audit_actor_map(guild: discord.Guild, event_key: str, target_ids: set[int]) -> dict[int, discord.abc.User]:
    action = AUDIT_ACTIONS.get(event_key)
    if action is None or not target_ids:
        return {}
    result: dict[int, discord.abc.User] = {}
    try:
        async for entry in guild.audit_logs(limit=min(100, max(25, len(target_ids) * 4)), action=action):
            target_id = int(getattr(getattr(entry, "target", None), "id", 0) or 0)
            if target_id in target_ids and entry.user is not None:
                result[target_id] = entry.user
                if len(result) >= len(target_ids):
                    break
    except (discord.Forbidden, discord.HTTPException):
        return {}
    return result


def _line_from_embed(embed: discord.Embed, target_id: int | None, actor) -> str:
    desc = str(embed.description or "").replace("\n", " — ").strip()
    desc = desc[:500] if desc else (f"`{target_id}`" if target_id else "Événement Discord")
    actor_text = f" par {getattr(actor, 'mention', str(actor))} (`{actor.id}`)" if actor is not None else ""
    return f"• {desc}{actor_text}"


async def _flush_group(bot, original, key: tuple[int, str, str]) -> None:
    await asyncio.sleep(LOG_BATCH_DELAY)
    runtime = state(bot)
    buffers = runtime.setdefault("v17_log_buffers", {})
    items = buffers.pop(key, [])
    if not items:
        return
    guild = items[0][0]
    log_type = key[2]
    if len(items) < LOG_BATCH_THRESHOLD:
        for _guild, embed, file in items:
            await original(bot, _guild, log_type, embed, file=file)
        return

    event_key = key[1]
    ids = {_target_id(embed) for _guild, embed, _file in items}
    ids.discard(None)
    actors = await _audit_actor_map(guild, event_key, {int(value) for value in ids})
    lines = []
    for _guild, embed, _file in items:
        target_id = _target_id(embed)
        lines.append(_line_from_embed(embed, target_id, actors.get(target_id) if target_id else None))

    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip()
        if len(candidate) > 3500 and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)

    for index, chunk in enumerate(chunks, start=1):
        suffix = f" • {index}/{len(chunks)}" if len(chunks) > 1 else ""
        grouped = discord.Embed(
            title=f"{GROUP_TITLES.get(event_key, 'Événements')} ({len(items)}){suffix}",
            description=chunk,
            colour=items[0][1].colour,
            timestamp=discord.utils.utcnow(),
        )
        grouped.set_footer(text="SentriX • Journal groupé V17")
        await original(bot, guild, log_type, grouped, file=None)


def install_log_pipeline(bot: commands.Bot) -> None:
    runtime = state(bot)
    if runtime.get("v17_log_pipeline"):
        return
    current = log_service.send_log
    if getattr(current, "_sentrix_v17_events", False):
        runtime["v17_log_pipeline"] = True
        return

    async def send_log_v17(runtime_bot, guild: discord.Guild, log_type: str, embed: discord.Embed, file: discord.File | None = None, **identity) -> bool:
        event_key = _event_key(embed)
        if event_key is not None and not await _event_enabled(runtime_bot, guild.id, event_key):
            return False
        if event_key not in GROUPABLE or file is not None:
            return await current(runtime_bot, guild, log_type, embed, file=file, **identity)
        key = (guild.id, event_key, str(log_type))
        buffers = state(runtime_bot).setdefault("v17_log_buffers", {})
        buffers.setdefault(key, []).append((guild, embed.copy(), file))
        tasks = state(runtime_bot).setdefault("v17_log_buffer_tasks", {})
        task = tasks.get(key)
        if task is None or task.done():
            async def runner():
                try:
                    await _flush_group(runtime_bot, current, key)
                finally:
                    tasks.pop(key, None)
            tasks[key] = asyncio.create_task(runner(), name=f"sentrix-v17-log-{guild.id}-{event_key}")
        return True

    send_log_v17._sentrix_v17_events = True
    send_log_v17._sentrix_original = current
    log_service.send_log = send_log_v17
    runtime["v17_log_pipeline"] = True
    logger.info("V17 : logs événementiels + regroupement salons/bans activés.")


def install_ticket_patches(bot: commands.Bot) -> None:
    cog = bot.get_cog("Tickets")
    if cog is None:
        return
    from . import tickets as tickets_mod
    from . import ticket_claim_security as claim_security

    cls = type(cog)
    current_claim = cls.btn_claim
    if not getattr(current_claim, "_sentrix_v17_atomic_claim", False):
        async def atomic_claim(self, interaction: discord.Interaction, ticket):
            channel = interaction.channel
            guild = interaction.guild
            member = interaction.user
            if not isinstance(channel, discord.TextChannel) or guild is None or not isinstance(member, discord.Member):
                return await interaction.response.send_message(embed=embeds.error("Impossible de prendre en charge ce ticket."), ephemeral=True)

            fresh = await self.get_ticket_by_channel(channel.id)
            if not fresh or fresh["status"] != "ouvert":
                return await interaction.response.send_message(embed=embeds.error("Ce ticket n'est plus ouvert."), ephemeral=True)
            current_id = fresh["claimed_by"]
            if current_id:
                current_member = guild.get_member(int(current_id))
                return await interaction.response.send_message(
                    embed=embeds.warning(
                        "Vous avez déjà pris ce ticket en charge." if int(current_id) == member.id
                        else f"Ce ticket est déjà pris en charge par {current_member.mention if current_member else 'un autre membre du staff'}."
                    ),
                    ephemeral=True,
                )

            reservation = await self.bot.db.execute(
                "UPDATE tickets SET claimed_by=?,last_activity_at=? WHERE id=? AND status='ouvert' AND claimed_by IS NULL",
                (member.id, now(), fresh["id"]),
            )
            if reservation.rowcount < 1:
                winner = await self.get_ticket_by_channel(channel.id)
                current_member = guild.get_member(int(winner["claimed_by"])) if winner and winner["claimed_by"] else None
                return await interaction.response.send_message(
                    embed=embeds.warning(f"Un autre membre du staff a été plus rapide : {current_member.mention if current_member else 'ticket déjà pris'}."),
                    ephemeral=True,
                )

            await interaction.response.defer()
            try:
                await claim_security._set_staff_role_visibility(self, channel, fresh, visible=False)
                await claim_security._grant_claimant(channel, member)
            except discord.HTTPException:
                await self.bot.db.execute("UPDATE tickets SET claimed_by=NULL WHERE id=? AND claimed_by=?", (fresh["id"], member.id))
                await claim_security._set_staff_role_visibility(self, channel, fresh, visible=True)
                return await interaction.followup.send(embed=embeds.error("Discord a refusé la modification des accès ; le claim a été annulé."), ephemeral=True)

            await self.bot.db.execute(
                "INSERT OR IGNORE INTO v17_ticket_claim_events (ticket_id,guild_id,staff_id,claimed_at) VALUES (?,?,?,?)",
                (fresh["id"], guild.id, member.id, now()),
            )
            await interaction.followup.send(embed=embeds.success(
                f"{member.mention} a pris en charge ce ticket. Un seul membre du staff peut désormais le gérer, hors Administrateurs."
            ))

        atomic_claim._sentrix_v17_atomic_claim = True
        atomic_claim._sentrix_original = current_claim
        cls.btn_claim = atomic_claim

    current_transcript = cls._fetch_transcript_text
    if not getattr(current_transcript, "_sentrix_v17_rich_transcript", False):
        async def rich_transcript(self, channel: discord.TextChannel) -> str:
            lines: list[str] = []
            async for msg in channel.history(limit=3000, oldest_first=True):
                edited = f" • modifié {msg.edited_at:%Y-%m-%d %H:%M}" if msg.edited_at else ""
                reply = ""
                if msg.reference and msg.reference.message_id:
                    reply = f" • répond à {msg.reference.message_id}"
                content = msg.content or "[aucun texte]"
                lines.append(f"[{msg.created_at:%Y-%m-%d %H:%M}] {msg.author} ({msg.author.id}){edited}{reply}: {content}")
                for attachment in msg.attachments:
                    lines.append(f"    [fichier] {attachment.filename} — {attachment.url}")
                for sticker in getattr(msg, "stickers", ()):
                    lines.append(f"    [sticker] {sticker.name} ({sticker.id})")
                for embed in msg.embeds:
                    if embed.title:
                        lines.append(f"    [embed titre] {embed.title}")
                    if embed.description:
                        lines.append(f"    [embed description] {embed.description}")
                    for field in embed.fields:
                        lines.append(f"    [embed champ] {field.name}: {field.value}")
            return "\n".join(lines) or "Aucun message."

        rich_transcript._sentrix_v17_rich_transcript = True
        rich_transcript._sentrix_original = current_transcript
        cls._fetch_transcript_text = rich_transcript

    current_auto_delete = cls._auto_delete
    if not getattr(current_auto_delete, "_sentrix_v17_reopen_window", False):
        async def auto_delete_v17(self, channel: discord.TextChannel, ticket_id: int, delay: int):
            await asyncio.sleep(max(0, int(delay)))
            current = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id=?", (ticket_id,))
            if not current or current["status"] != "ferme":
                return
            setting = await self.bot.db.fetchone("SELECT reopen_minutes FROM v17_ticket_settings WHERE guild_id=?", (channel.guild.id,))
            reopen_minutes = int(setting["reopen_minutes"] if setting else 0)
            if reopen_minutes > 0 and current["closed_at"]:
                remaining = int(current["closed_at"]) + reopen_minutes * 60 - now()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    current = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id=?", (ticket_id,))
                    if not current or current["status"] != "ferme":
                        return
            await self.bot.db.execute("UPDATE tickets SET status='supprime' WHERE id=? AND status='ferme'", (ticket_id,))
            try:
                await channel.delete(reason="Ticket fermé : fenêtre de réouverture terminée.")
            except discord.HTTPException:
                pass

        auto_delete_v17._sentrix_v17_reopen_window = True
        auto_delete_v17._sentrix_original = current_auto_delete
        cls._auto_delete = auto_delete_v17

    state(bot)["v17_ticket_patches"] = True


class V17TicketsLogs(commands.Cog, name="V17TicketsLogs"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_schema(self.bot)

    @commands.hybrid_group(name="logevent", description="Activer ou désactiver un événement de log précis.")
    @checks.is_owner_or_admin_for("configuration")
    async def logevent(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT event_key,enabled FROM v17_log_event_settings WHERE guild_id=?", (ctx.guild.id,))
        saved = {r["event_key"]: bool(r["enabled"]) for r in rows}
        text = "\n".join(
            f"{'●' if saved.get(key, True) else '○'} **{EVENT_LABELS[key]}** — `{key}`"
            for key in EVENT_LABELS
        )
        await ctx.send(embed=embeds.info(text, title="Logs par événement"))

    @logevent.command(name="on")
    async def logevent_on(self, ctx: commands.Context, evenement: str):
        key = evenement.casefold().strip()
        if key not in EVENT_LABELS:
            return await ctx.send(embed=embeds.error("Événement inconnu. Lancez `+logevent` pour voir les clés."))
        await self.bot.db.execute(
            "INSERT INTO v17_log_event_settings (guild_id,event_key,enabled) VALUES (?,?,1) "
            "ON CONFLICT(guild_id,event_key) DO UPDATE SET enabled=1",
            (ctx.guild.id, key),
        )
        _invalidate_event_cache(self.bot, ctx.guild.id, key)
        await ctx.send(embed=embeds.success(f"Log **{EVENT_LABELS[key]}** activé."))

    @logevent.command(name="off")
    async def logevent_off(self, ctx: commands.Context, evenement: str):
        key = evenement.casefold().strip()
        if key not in EVENT_LABELS:
            return await ctx.send(embed=embeds.error("Événement inconnu. Lancez `+logevent` pour voir les clés."))
        await self.bot.db.execute(
            "INSERT INTO v17_log_event_settings (guild_id,event_key,enabled) VALUES (?,?,0) "
            "ON CONFLICT(guild_id,event_key) DO UPDATE SET enabled=0",
            (ctx.guild.id, key),
        )
        _invalidate_event_cache(self.bot, ctx.guild.id, key)
        await ctx.send(embed=embeds.success(f"Log **{EVENT_LABELS[key]}** désactivé."))

    @commands.hybrid_command(name="logsearch", description="Rechercher l'historique enregistré d'un membre.", with_app_command=False)
    @checks.has_permission_or_modrole("moderate_members")
    async def logsearch(self, ctx: commands.Context, membre: discord.Member):
        sanctions = await self.bot.db.fetchall(
            "SELECT case_number,action,reason,created_at FROM sanctions WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 10",
            (ctx.guild.id, membre.id),
        )
        automod = await self.bot.db.fetchall(
            "SELECT filter_name,action,reason,timestamp FROM automod_logs WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC LIMIT 10",
            (ctx.guild.id, membre.id),
        )
        tickets = await self.bot.db.fetchall(
            "SELECT id,category,status,created_at FROM tickets WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 10",
            (ctx.guild.id, membre.id),
        )
        notes = await self.bot.db.fetchall(
            "SELECT id,note,author_id,created_at FROM v17_staff_notes WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 5",
            (ctx.guild.id, membre.id),
        )
        e = embeds.neutral(f"Recherche logs — {membre.display_name}")
        e.add_field(name="Modération", value="\n".join(
            f"#{r['case_number']} {r['action']} — {r['reason'] or 'Sans raison'} — <t:{r['created_at']}:R>" for r in sanctions
        )[:1024] or "Aucun résultat", inline=False)
        e.add_field(name="AutoMod", value="\n".join(
            f"{r['filter_name']} → {r['action']} — <t:{r['timestamp']}:R>" for r in automod
        )[:1024] or "Aucun résultat", inline=False)
        e.add_field(name="Tickets", value="\n".join(
            f"#{r['id']} {r['category'] or 'ticket'} — {r['status']} — <t:{r['created_at']}:R>" for r in tickets
        )[:1024] or "Aucun résultat", inline=False)
        e.add_field(name="Notes staff", value="\n".join(
            f"#{r['id']} par <@{r['author_id']}> — {r['note'][:120]}" for r in notes
        )[:1024] or "Aucun résultat", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="ticketreopenwindow", description="Configurer la durée pendant laquelle un ticket fermé peut être rouvert.", with_app_command=False)
    @checks.is_owner_or_admin_for("tickets")
    async def ticketreopenwindow(self, ctx: commands.Context, minutes: int):
        if minutes < 0 or minutes > 10080:
            return await ctx.send(embed=embeds.error("Choisissez entre 0 et 10080 minutes (7 jours)."))
        await self.bot.db.execute(
            "INSERT INTO v17_ticket_settings (guild_id,reopen_minutes,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET reopen_minutes=excluded.reopen_minutes,updated_at=excluded.updated_at",
            (ctx.guild.id, minutes, now()),
        )
        if minutes > 0:
            conf = await self.bot.db.get_guild_config(ctx.guild.id)
            current_delay = int(conf["ticket_delete_delay"] or 30) if conf else 30
            if current_delay < minutes * 60:
                await self.bot.db.set_guild_config(ctx.guild.id, "ticket_delete_delay", minutes * 60)
        await ctx.send(embed=embeds.success(
            "Réouverture désactivée." if minutes == 0 else f"Les tickets fermés restent réouvrables pendant **{minutes} minute(s)**."
        ))

    @commands.hybrid_command(name="reopenticket", description="Rouvrir le ticket fermé de ce salon.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def reopenticket(self, ctx: commands.Context):
        ticket = await self.bot.db.fetchone("SELECT * FROM tickets WHERE channel_id=?", (ctx.channel.id,))
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        if ticket["status"] != "ferme":
            return await ctx.send(embed=embeds.warning("Ce ticket n'est pas fermé."))
        setting = await self.bot.db.fetchone("SELECT reopen_minutes FROM v17_ticket_settings WHERE guild_id=?", (ctx.guild.id,))
        minutes = int(setting["reopen_minutes"] if setting else 0)
        if minutes <= 0:
            return await ctx.send(embed=embeds.error("La réouverture n'est pas activée. Un administrateur peut utiliser `+ticketreopenwindow`."))
        if not ticket["closed_at"] or now() > int(ticket["closed_at"]) + minutes * 60:
            return await ctx.send(embed=embeds.error("La fenêtre de réouverture est terminée."))
        await self.bot.db.execute("UPDATE tickets SET status='ouvert',closed_at=NULL,locked=0,last_activity_at=? WHERE id=? AND status='ferme'", (now(), ticket["id"]))
        owner = ctx.guild.get_member(ticket["user_id"])
        if owner:
            overwrite = ctx.channel.overwrites_for(owner)
            overwrite.view_channel = True
            overwrite.send_messages = True
            overwrite.read_message_history = True
            try:
                await ctx.channel.set_permissions(owner, overwrite=overwrite, reason=f"Ticket rouvert par {ctx.author}")
            except discord.HTTPException:
                pass
        from .tickets import TicketControlView, get_button_settings
        settings = await get_button_settings(self.bot, ctx.guild.id)
        await ctx.send(embed=embeds.success(f"Ticket **#{ticket['id']}** rouvert par {ctx.author.mention}."), view=TicketControlView(settings))

    @commands.hybrid_command(name="ticketstaffstats", description="Statistiques de traitement des tickets par membre du staff.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def ticketstaffstats(self, ctx: commands.Context, membre: discord.Member | None = None):
        target = membre or ctx.author
        row = await self.bot.db.fetchone(
            "SELECT COUNT(*) claimed, "
            "SUM(CASE WHEN t.status!='ouvert' THEN 1 ELSE 0 END) resolved, "
            "AVG(CASE WHEN t.closed_at IS NOT NULL THEN t.closed_at-t.created_at END) avg_resolution, "
            "AVG(t.rating) avg_rating "
            "FROM v17_ticket_claim_events c JOIN tickets t ON t.id=c.ticket_id "
            "WHERE c.guild_id=? AND c.staff_id=?",
            (ctx.guild.id, target.id),
        )
        active = await self.bot.db.fetchone(
            "SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND claimed_by=? AND status='ouvert'",
            (ctx.guild.id, target.id),
        )
        claimed = int(row["claimed"] or 0) if row else 0
        resolved = int(row["resolved"] or 0) if row else 0
        avg_seconds = int(row["avg_resolution"] or 0) if row else 0
        rating = float(row["avg_rating"] or 0) if row else 0.0
        e = embeds.neutral(f"Stats tickets staff — {target.display_name}")
        e.add_field(name="Pris en charge", value=str(claimed), inline=True)
        e.add_field(name="Résolus/fermés", value=str(resolved), inline=True)
        e.add_field(name="Actuellement ouverts", value=str(int(active["c"] if active else 0)), inline=True)
        e.add_field(name="Temps moyen de résolution", value=helpers.format_duration(avg_seconds) if avg_seconds else "N/A", inline=True)
        e.add_field(name="Note moyenne", value=f"{rating:.1f}/5" if rating else "N/A", inline=True)
        await ctx.send(embed=e)


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    await ensure_schema(bot)
    register_command_policy(
        configuration={"logevent"},
        moderation={"logsearch"},
        tickets={"ticketreopenwindow", "reopenticket", "ticketstaffstats"},
    )
    if bot.get_cog("V17TicketsLogs") is None:
        await bot.add_cog(V17TicketsLogs(bot))
    install_log_pipeline(bot)
    install_ticket_patches(bot)


__all__ = ["install"]
