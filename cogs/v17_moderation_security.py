"""SentriX V17 — modération et sécurité avancées."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

import config
from database.db import now
from utils import checks, embeds, helpers, log_service
from utils import sentrix_panels as panels
from .v17_shared import (
    create_snapshot,
    ensure_schema,
    is_protected,
    register_command_policy,
    safe_discord_call,
    state,
)

logger = logging.getLogger("bot.v17-moderation-security")
SANCTION_DUPLICATE_TTL = 5.0
JOIN_WINDOW_SECONDS = 10.0
JOIN_RAID_THRESHOLD = 8
VALID_NUKE_ACTIONS = {"all", "channel_delete", "role_delete"}


class V17ConfirmationCancelled(commands.CheckFailure):
    pass


def _ctx_from_args(args, kwargs):
    for value in args:
        if isinstance(value, commands.Context):
            return value
    value = kwargs.get("ctx")
    return value if isinstance(value, commands.Context) else None


def _target_id_from_args(args, kwargs) -> int | None:
    for key in ("membre", "member", "user", "target", "user_id"):
        value = kwargs.get(key)
        if isinstance(value, (discord.Member, discord.User, discord.Object)):
            return int(value.id)
        if value is not None:
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                pass
    seen_ctx = False
    for value in args:
        if isinstance(value, commands.Context):
            seen_ctx = True
            continue
        if not seen_ctx:
            continue
        if isinstance(value, (discord.Member, discord.User, discord.Object)):
            return int(value.id)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def install_moderation_guards(bot: commands.Bot) -> None:
    cog = bot.get_cog("Moderation")
    if cog is None:
        return
    cls = type(cog)

    current_targetable = cls.check_targetable
    if not getattr(current_targetable, "_sentrix_v17_protected", False):
        async def targetable_v17(self, ctx: commands.Context, membre: discord.Member) -> bool:
            if not await current_targetable(self, ctx, membre):
                return False
            protected, reason = await is_protected(self.bot, ctx.guild.id, membre.id)
            if not protected:
                return True
            if ctx.author.id == ctx.guild.owner_id or await checks.is_verified_bot_owner(ctx):
                return True
            detail = f" Raison : {reason}" if reason else ""
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Ce membre est protégé contre les sanctions SentriX.{detail}', title='Membre protégé')))
            return False

        targetable_v17._sentrix_v17_protected = True
        targetable_v17._sentrix_original = current_targetable
        cls.check_targetable = targetable_v17

    for command_name in ("ban", "tempban", "kick", "mute", "unmute", "warn", "unban"):
        command = bot.get_command(command_name)
        if command is None or getattr(command.callback, "_sentrix_v17_dedupe", False):
            continue
        original = command.callback

        async def dedupe_callback(*args, __original=original, __name=command_name, **kwargs):
            ctx = _ctx_from_args(args, kwargs)
            target_id = _target_id_from_args(args, kwargs)
            if ctx is None or ctx.guild is None or target_id is None:
                return await __original(*args, **kwargs)
            key = (int(ctx.guild.id), str(__name), int(target_id))
            recent = state(bot)["sanction_recent"]
            mono = time.monotonic()
            previous = recent.get(key)
            if previous is not None and mono - float(previous) <= SANCTION_DUPLICATE_TTL:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning("Cette sanction vient déjà d'être lancée sur la même cible. Le second appel a été annulé.", title='Double sanction bloquée')))
            recent[key] = mono
            if len(recent) > 5000:
                cutoff = mono - 30.0
                for candidate, stamp in list(recent.items()):
                    if float(stamp) < cutoff:
                        recent.pop(candidate, None)
            return await __original(*args, **kwargs)

        dedupe_callback._sentrix_v17_dedupe = True
        dedupe_callback._sentrix_original = original
        command.callback = dedupe_callback


def install_danger_confirmations(bot: commands.Bot) -> None:
    dangerous = {
        "reset-economy": "réinitialiser toute l'économie",
        "wipe-server": "supprimer massivement la structure du serveur",
        "massrole": "modifier des rôles en masse",
        "roleall": "attribuer un rôle à de nombreux membres",
        "server-restore": "restaurer une sauvegarde serveur",
    }
    for command_name, label in dangerous.items():
        command = bot.get_command(command_name)
        if command is None or getattr(command.callback, "_sentrix_v17_confirmation", False):
            continue
        original = command.callback

        async def confirmed_callback(*args, __original=original, __name=command_name, __label=label, **kwargs):
            ctx = _ctx_from_args(args, kwargs)
            if ctx is None or ctx.guild is None:
                return await __original(*args, **kwargs)
            view = helpers.ConfirmView(ctx.author.id, timeout=30)
            message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embeds.warning(f"Vous êtes sur le point de **{__label}**. Une sauvegarde automatique sera créée avant l'action. Confirmer ?", title='Confirmation obligatoire')), view))
            await view.wait()
            if view.value is not True:
                try:
                    await panels.editer(message, panels.depuis_embed(embeds.info('Action annulée.')))
                except discord.HTTPException:
                    pass
                return None
            snapshot_id = await create_snapshot(bot, ctx.guild, f"auto-before-{__name}", ctx.author.id)
            try:
                await panels.editer(message, panels.depuis_embed(embeds.success(f'Confirmation reçue. Snapshot automatique : **#{snapshot_id}**.' if snapshot_id else 'Confirmation reçue.')))
            except discord.HTTPException:
                pass
            return await __original(*args, **kwargs)

        confirmed_callback._sentrix_v17_confirmation = True
        confirmed_callback._sentrix_original = original
        command.callback = confirmed_callback


async def _audit_actor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int):
    for attempt in range(3):
        try:
            async for entry in guild.audit_logs(limit=8, action=action):
                target = getattr(entry, "target", None)
                if int(getattr(target, "id", 0) or 0) == int(target_id):
                    return entry.user
        except (discord.Forbidden, discord.HTTPException):
            return None
        if attempt < 2:
            await asyncio.sleep(0.45 * (attempt + 1))
    return None


async def _antinuke_allowed(bot: commands.Bot, guild: discord.Guild, actor, action: str) -> bool:
    if actor is None:
        return True  # fail-safe : jamais restaurer automatiquement sans auteur fiable
    if actor.id in {guild.owner_id, getattr(getattr(bot, "user", None), "id", None)}:
        return True
    legacy = await bot.db.fetchone(
        "SELECT 1 FROM antinuke_whitelist WHERE guild_id=? AND user_id=?",
        (guild.id, actor.id),
    )
    if legacy:
        return True
    user_rule = await bot.db.fetchone(
        "SELECT 1 FROM v17_antinuke_whitelist WHERE guild_id=? AND subject_type='user' AND subject_id=? AND action IN (?, 'all') LIMIT 1",
        (guild.id, actor.id, action),
    )
    if user_rule:
        return True
    member = guild.get_member(actor.id)
    if member:
        role_ids = [role.id for role in member.roles]
        if role_ids:
            placeholders = ",".join("?" for _ in role_ids)
            row = await bot.db.fetchone(
                f"SELECT 1 FROM v17_antinuke_whitelist WHERE guild_id=? AND subject_type='role' "
                f"AND subject_id IN ({placeholders}) AND action IN (?, 'all') LIMIT 1",
                (guild.id, *role_ids, action),
            )
            if row:
                return True
    return False


async def _security_alert(bot: commands.Bot, guild: discord.Guild, title: str, description: str) -> None:
    e = embeds.warning(description, title=title)
    await log_service.send_log(bot, guild, "automod", e)


def install_antinuke_restore(bot: commands.Bot) -> None:
    runtime = state(bot)
    if runtime.get("v17_antinuke_listeners"):
        return

    async def channel_deleted(channel: discord.abc.GuildChannel):
        guild = channel.guild
        try:
            settings = await bot.db.get_automod(guild.id)
            if not settings or not settings["antinuke"]:
                return
            actor = await _audit_actor(guild, discord.AuditLogAction.channel_delete, channel.id)
            if await _antinuke_allowed(bot, guild, actor, "channel_delete"):
                return
            if actor is None:
                return
            clone = await safe_discord_call(
                lambda: channel.clone(reason=f"SentriX V17 anti-nuke : restauration après suppression par {actor}"),
                attempts=2,
            )
            try:
                await clone.edit(position=channel.position)
            except discord.HTTPException:
                pass
            await _security_alert(
                bot,
                guild,
                "Anti-nuke : salon restauré",
                f"**{channel.name}** a été supprimé par <@{actor.id}> (`{actor.id}`) sans autorisation et a été recréé.",
            )
        except Exception:
            logger.exception("V17 anti-nuke : restauration salon impossible.")

    async def role_deleted(role: discord.Role):
        guild = role.guild
        try:
            settings = await bot.db.get_automod(guild.id)
            if not settings or not settings["antinuke"] or role.is_default() or role.managed:
                return
            actor = await _audit_actor(guild, discord.AuditLogAction.role_delete, role.id)
            if await _antinuke_allowed(bot, guild, actor, "role_delete"):
                return
            if actor is None:
                return
            recreated = await safe_discord_call(
                lambda: guild.create_role(
                    name=role.name,
                    permissions=role.permissions,
                    colour=role.colour,
                    hoist=role.hoist,
                    mentionable=role.mentionable,
                    reason=f"SentriX V17 anti-nuke : restauration après suppression par {actor}",
                ),
                attempts=2,
            )
            try:
                await recreated.edit(position=min(role.position, max(1, guild.me.top_role.position - 1)))
            except discord.HTTPException:
                pass
            await _security_alert(
                bot,
                guild,
                "Anti-nuke : rôle restauré",
                f"Le rôle **{role.name}** a été supprimé par <@{actor.id}> (`{actor.id}`) sans autorisation et a été recréé.",
            )
        except Exception:
            logger.exception("V17 anti-nuke : restauration rôle impossible.")

    bot.add_listener(channel_deleted, "on_guild_channel_delete")
    bot.add_listener(role_deleted, "on_guild_role_delete")
    runtime["v17_antinuke_listeners"] = True


def install_join_risk_detection(bot: commands.Bot) -> None:
    runtime = state(bot)
    if runtime.get("v17_join_risk_listener"):
        return

    async def joined(member: discord.Member):
        try:
            if not await ensure_schema(bot):
                return
            stamp = time.monotonic()
            windows = state(bot)["join_windows"]
            bucket = windows.setdefault(member.guild.id, [])
            bucket[:] = [value for value in bucket if stamp - value <= JOIN_WINDOW_SECONDS]
            bucket.append(stamp)

            age_seconds = max(0, (discord.utils.utcnow() - member.created_at).total_seconds())
            score = 0
            reasons: list[str] = []
            if age_seconds < 86400:
                score += 4
                reasons.append("compte créé il y a moins de 24h")
            elif age_seconds < 7 * 86400:
                score += 2
                reasons.append("compte créé il y a moins de 7 jours")
            if member.avatar is None:
                score += 1
                reasons.append("avatar par défaut")
            if len(bucket) >= JOIN_RAID_THRESHOLD:
                score += 3
                reasons.append(f"pic de {len(bucket)} arrivées en {JOIN_WINDOW_SECONDS}s")
            name = (member.name or "").casefold()
            if sum(ch.isdigit() for ch in name) >= 6:
                score += 1
                reasons.append("nom contenant beaucoup de chiffres")

            await bot.db.execute(
                "INSERT INTO v17_suspicious_accounts (guild_id,user_id,score,reasons_json,joined_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET score=excluded.score,reasons_json=excluded.reasons_json,joined_at=excluded.joined_at",
                (member.guild.id, member.id, score, json.dumps(reasons, ensure_ascii=False), now()),
            )
            if score >= 5:
                await _security_alert(
                    bot,
                    member.guild,
                    "Compte à surveiller",
                    f"{member.mention} (`{member.id}`) obtient un score de risque **{score}/9**.\n"
                    + "\n".join(f"• {reason}" for reason in reasons)
                    + "\n\nAucune sanction automatique n'a été appliquée.",
                )
        except Exception:
            logger.exception("V17 : analyse de risque à l'arrivée impossible.")

    bot.add_listener(joined, "on_member_join")
    runtime["v17_join_risk_listener"] = True


class V17ModerationSecurity(commands.Cog, name="V17ModerationSecurity"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_schema(self.bot)

    @commands.hybrid_group(name="protectmember", description="Protéger des membres contre les sanctions SentriX.")
    @checks.is_owner_or_admin_for("moderation")
    async def protectmember(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM v17_protected_members WHERE guild_id=? ORDER BY created_at DESC LIMIT 25",
            (ctx.guild.id,),
        )
        text = "\n".join(f"• <@{r['user_id']}> — {r['reason'] or 'Aucune raison'}" for r in rows) or "Aucun membre protégé."
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info(text, title='Membres protégés')))

    @protectmember.command(name="add", description="Ajouter un membre protégé.")
    async def protectmember_add(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Membre protégé"):
        await self.bot.db.execute(
            "INSERT INTO v17_protected_members (guild_id,user_id,reason,added_by,created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=excluded.reason,added_by=excluded.added_by,created_at=excluded.created_at",
            (ctx.guild.id, membre.id, raison[:500], ctx.author.id, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} est maintenant protégé contre les sanctions SentriX.')))

    @protectmember.command(name="remove", description="Retirer une protection.")
    async def protectmember_remove(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM v17_protected_members WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, membre.id),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Protection retirée pour {membre.mention}.')))

    @commands.hybrid_command(name="caseproof", description="Ajouter une preuve à un dossier de modération.", with_app_command=False)
    @checks.has_permission_or_modrole("moderate_members")
    async def caseproof(self, ctx: commands.Context, numero: int, *, preuve: str):
        case = await self.bot.db.get_sanction_by_case(ctx.guild.id, numero)
        if not case:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Dossier #{numero} introuvable.')))
        await self.bot.db.execute(
            "INSERT INTO v17_case_proofs (guild_id,case_number,proof,added_by,created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id,case_number) DO UPDATE SET proof=excluded.proof,added_by=excluded.added_by,created_at=excluded.created_at",
            (ctx.guild.id, numero, preuve[:1800], ctx.author.id, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Preuve enregistrée sur le dossier **#{numero}**.')))

    @commands.hybrid_command(name="casefull", description="Afficher un dossier complet, preuve incluse.", with_app_command=False)
    @checks.has_permission_or_modrole("moderate_members")
    async def casefull(self, ctx: commands.Context, numero: int):
        row = await self.bot.db.get_sanction_by_case(ctx.guild.id, numero)
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Dossier #{numero} introuvable.')))
        proof = await self.bot.db.fetchone(
            "SELECT * FROM v17_case_proofs WHERE guild_id=? AND case_number=?",
            (ctx.guild.id, numero),
        )
        undo = await self.bot.db.fetchone(
            "SELECT * FROM v17_mod_undo WHERE guild_id=? AND case_number=?",
            (ctx.guild.id, numero),
        )
        e = embeds.neutral(f"Dossier #{numero} — {row['action']}")
        e.add_field(name="Membre", value=f"<@{row['user_id']}>\n`{row['user_id']}`", inline=True)
        e.add_field(name="Modérateur", value=f"<@{row['moderator_id']}>\n`{row['moderator_id']}`", inline=True)
        e.add_field(name="Date", value=f"<t:{row['created_at']}:F>", inline=True)
        if row["duration_seconds"]:
            e.add_field(name="Durée", value=helpers.format_duration(row["duration_seconds"]), inline=True)
        e.add_field(name="Raison", value=row["reason"] or "Aucune raison", inline=False)
        e.add_field(name="Preuve", value=proof["proof"] if proof else "Aucune preuve enregistrée", inline=False)
        if undo:
            e.add_field(name="Annulation", value=f"Annulé par <@{undo['undone_by']}> <t:{undo['undone_at']}:R> — {undo['detail'] or ''}", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_group(name="staffnote", description="Notes privées du staff sur un membre.")
    @checks.has_permission_or_modrole("moderate_members")
    async def staffnote(self, ctx: commands.Context):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Utilisez `+staffnote add`, `+staffnote list` ou `+staffnote remove`.')))

    @staffnote.command(name="add")
    async def staffnote_add(self, ctx: commands.Context, membre: discord.Member, *, note: str):
        await self.bot.db.execute(
            "INSERT INTO v17_staff_notes (guild_id,user_id,author_id,note,created_at) VALUES (?,?,?,?,?)",
            (ctx.guild.id, membre.id, ctx.author.id, note[:1800], now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Note privée ajoutée pour {membre.mention}.')))

    @staffnote.command(name="list")
    async def staffnote_list(self, ctx: commands.Context, membre: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM v17_staff_notes WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 15",
            (ctx.guild.id, membre.id),
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucune note staff pour ce membre.')))
        e = embeds.neutral(f"Notes staff — {membre.display_name}")
        for row in rows:
            e.add_field(
                name=f"#{row['id']} — <t:{row['created_at']}:R>",
                value=f"Par <@{row['author_id']}>\n{row['note']}",
                inline=False,
            )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @staffnote.command(name="remove")
    async def staffnote_remove(self, ctx: commands.Context, note_id: int):
        row = await self.bot.db.fetchone(
            "SELECT id FROM v17_staff_notes WHERE id=? AND guild_id=?",
            (note_id, ctx.guild.id),
        )
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Note introuvable.')))
        await self.bot.db.execute("DELETE FROM v17_staff_notes WHERE id=?", (note_id,))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Note **#{note_id}** supprimée.')))

    @commands.hybrid_command(name="userhistory", description="Historique centralisé d'un membre.", with_app_command=False)
    @checks.has_permission_or_modrole("moderate_members")
    async def userhistory(self, ctx: commands.Context, membre: discord.Member):
        sanctions = await self.bot.db.get_sanction_history(ctx.guild.id, membre.id, limit=8)
        tickets = await self.bot.db.fetchall(
            "SELECT id,status,category,created_at,closed_at,rating FROM tickets WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 8",
            (ctx.guild.id, membre.id),
        )
        notes = await self.bot.db.fetchall(
            "SELECT * FROM v17_staff_notes WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 5",
            (ctx.guild.id, membre.id),
        )
        automod = await self.bot.db.automod_history_for_user(ctx.guild.id, membre.id, limit=5)
        e = embeds.neutral(f"Historique centralisé — {membre.display_name}")
        e.set_thumbnail(url=membre.display_avatar.url)
        e.add_field(name="Sanctions", value="\n".join(
            f"#{r['case_number']} {r['action']} — <t:{r['created_at']}:R>" for r in sanctions
        ) or "Aucune", inline=False)
        e.add_field(name="Tickets", value="\n".join(
            f"#{r['id']} {r['category'] or 'ticket'} — {r['status']} — <t:{r['created_at']}:R>" for r in tickets
        ) or "Aucun", inline=False)
        e.add_field(name="AutoMod", value="\n".join(
            f"{r['filter_name']} → {r['action']} — <t:{r['timestamp']}:R>" for r in automod
        ) or "Aucun", inline=False)
        e.add_field(name="Notes privées", value="\n".join(
            f"#{r['id']} par <@{r['author_id']}> — {r['note'][:180]}" for r in notes
        ) or "Aucune", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="modundo", description="Annuler une sanction récente lorsque l'action est réversible.", with_app_command=False)
    @checks.has_permission_or_modrole("moderate_members")
    async def modundo(self, ctx: commands.Context, numero: int):
        row = await self.bot.db.get_sanction_by_case(ctx.guild.id, numero)
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Dossier introuvable.')))
        if await self.bot.db.fetchone("SELECT 1 FROM v17_mod_undo WHERE guild_id=? AND case_number=?", (ctx.guild.id, numero)):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Ce dossier a déjà été annulé.')))
        action = str(row["action"] or "")
        detail = ""
        try:
            if action in {"ban", "tempban"}:
                await safe_discord_call(
                    lambda: ctx.guild.unban(discord.Object(id=row["user_id"]), reason=f"Undo dossier #{numero} par {ctx.author}"),
                    attempts=2,
                )
                await self.bot.db.execute("DELETE FROM tempactions WHERE guild_id=? AND user_id=? AND action='ban'", (ctx.guild.id, row["user_id"]))
                detail = "bannissement retiré"
            elif action == "mute":
                member = ctx.guild.get_member(row["user_id"])
                if member is None:
                    return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Le membre n'est plus sur le serveur ; impossible de retirer son timeout.")))
                await member.timeout(None, reason=f"Undo dossier #{numero} par {ctx.author}")
                detail = "timeout retiré"
            elif action == "warn":
                warning = await self.bot.db.fetchone(
                    "SELECT id FROM warnings WHERE guild_id=? AND user_id=? AND reason=? AND timestamp BETWEEN ? AND ? ORDER BY id DESC LIMIT 1",
                    (ctx.guild.id, row["user_id"], row["reason"], int(row["created_at"]) - 5, int(row["created_at"]) + 5),
                )
                if not warning:
                    return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'avertissement d'origine n'a pas pu être retrouvé précisément.")))
                await self.bot.db.execute("DELETE FROM warnings WHERE id=?", (warning["id"],))
                detail = f"avertissement #{warning['id']} supprimé"
            else:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"L'action **{action}** n'est pas réversible automatiquement. Les kicks/unbans et actions similaires restent dans l'audit.")))
        except discord.HTTPException:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Discord a refusé l'annulation. Vérifiez les permissions et l'état actuel de la cible.")))
        await self.bot.db.execute(
            "INSERT INTO v17_mod_undo (guild_id,case_number,undone_by,detail,undone_at) VALUES (?,?,?,?,?)",
            (ctx.guild.id, numero, ctx.author.id, detail, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Dossier **#{numero}** annulé : {detail}.')))

    @commands.hybrid_group(name="sanctionpolicy", description="Configurer les sanctions progressives par nombre de warns.")
    @checks.is_owner_or_admin_for("moderation")
    async def sanctionpolicy(self, ctx: commands.Context):
        row = await self._policy(ctx.guild.id)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f"État : **{('activé' if row['enabled'] else 'désactivé')}**\nMute : **{row['mute_warns']} warns** pendant {helpers.format_duration(row['mute_seconds'])}\nTempban : **{row['tempban_warns']} warns** pendant {helpers.format_duration(row['tempban_seconds'])}\nBan : **{row['ban_warns']} warns**", title='Sanctions progressives')))

    async def _policy(self, guild_id: int):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO v17_sanction_policy (guild_id,updated_at) VALUES (?,?)",
            (guild_id, now()),
        )
        return await self.bot.db.fetchone("SELECT * FROM v17_sanction_policy WHERE guild_id=?", (guild_id,))

    @sanctionpolicy.command(name="enable")
    async def sanctionpolicy_enable(self, ctx: commands.Context):
        await self._policy(ctx.guild.id)
        await self.bot.db.execute("UPDATE v17_sanction_policy SET enabled=1,updated_at=? WHERE guild_id=?", (now(), ctx.guild.id))
        # Empêche l'ancien seuil unique de bannissement de se déclencher en parallèle.
        await self.bot.db.set_guild_config(ctx.guild.id, "warn_ban_threshold", 0)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success("Sanctions progressives V17 activées. L'ancien seuil unique de ban a été désactivé pour éviter les doubles sanctions.")))

    @sanctionpolicy.command(name="disable")
    async def sanctionpolicy_disable(self, ctx: commands.Context):
        await self._policy(ctx.guild.id)
        await self.bot.db.execute("UPDATE v17_sanction_policy SET enabled=0,updated_at=? WHERE guild_id=?", (now(), ctx.guild.id))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success('Sanctions progressives V17 désactivées.')))

    @sanctionpolicy.command(name="set")
    async def sanctionpolicy_set(self, ctx: commands.Context, action: str, warns: app_commands.Range[int, 1, 50], duree: str = "1h"):
        action = action.casefold().strip()
        row = await self._policy(ctx.guild.id)
        if action not in {"mute", "tempban", "ban"}:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Action valide : `mute`, `tempban` ou `ban`.')))
        updates = {"mute": "mute_warns", "tempban": "tempban_warns", "ban": "ban_warns"}
        await self.bot.db.execute(f"UPDATE v17_sanction_policy SET {updates[action]}=?,updated_at=? WHERE guild_id=?", (warns, now(), ctx.guild.id))
        if action in {"mute", "tempban"}:
            seconds = helpers.parse_duration(duree)
            if seconds is None or seconds <= 0:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide, ex. `30m`, `2h`, `1j`.')))
            field = "mute_seconds" if action == "mute" else "tempban_seconds"
            await self.bot.db.execute(f"UPDATE v17_sanction_policy SET {field}=?,updated_at=? WHERE guild_id=?", (seconds, now(), ctx.guild.id))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Palier **{action}** réglé sur **{warns} warn(s)**.')))

    @commands.hybrid_group(name="serversnapshot", description="Snapshots de sécurité du serveur.")
    @checks.is_owner_or_admin_for("securite")
    async def serversnapshot(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT id,label,created_at FROM v17_snapshots WHERE guild_id=? ORDER BY created_at DESC LIMIT 10", (ctx.guild.id,))
        text = "\n".join(f"• **#{r['id']}** {r['label']} — <t:{r['created_at']}:R>" for r in rows) or "Aucun snapshot."
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info(text, title='Snapshots V17')))

    @serversnapshot.command(name="create")
    async def serversnapshot_create(self, ctx: commands.Context, *, nom: str = "manuel"):
        snapshot_id = await create_snapshot(self.bot, ctx.guild, nom, ctx.author.id)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Snapshot **#{snapshot_id}** créé.')))

    @serversnapshot.command(name="restore")
    async def serversnapshot_restore(self, ctx: commands.Context, snapshot_id: int):
        row = await self.bot.db.fetchone("SELECT * FROM v17_snapshots WHERE id=? AND guild_id=?", (snapshot_id, ctx.guild.id))
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Snapshot introuvable.')))
        view = helpers.ConfirmView(ctx.author.id, timeout=30)
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embeds.warning('La restauration est **additive** : elle recrée ce qui manque sans supprimer les éléments actuels. Continuer ?')), view))
        await view.wait()
        if view.value is not True:
            return await panels.editer(msg, panels.depuis_embed(embeds.info('Restauration annulée.')))
        payload = json.loads(row["data_json"])
        created_roles = 0
        created_channels = 0
        role_map: dict[int, discord.Role] = {r.id: r for r in ctx.guild.roles}
        for saved in sorted(payload.get("roles", []), key=lambda x: x.get("position", 0)):
            existing = discord.utils.get(ctx.guild.roles, name=saved.get("name"))
            if existing:
                role_map[int(saved["id"])] = existing
                continue
            try:
                role = await safe_discord_call(lambda s=saved: ctx.guild.create_role(
                    name=s.get("name", "Rôle restauré")[:100],
                    permissions=discord.Permissions(int(s.get("permissions", 0))),
                    colour=discord.Colour(int(s.get("colour", 0))),
                    hoist=bool(s.get("hoist", False)),
                    mentionable=bool(s.get("mentionable", False)),
                    reason=f"Restauration snapshot V17 #{snapshot_id}",
                ), attempts=2)
                role_map[int(saved["id"])] = role
                created_roles += 1
            except discord.HTTPException:
                continue
        category_map: dict[int, discord.CategoryChannel] = {}
        for saved in payload.get("channels", []):
            if saved.get("type") != "category":
                continue
            existing = discord.utils.get(ctx.guild.categories, name=saved.get("name"))
            if existing:
                category_map[int(saved["id"])] = existing
                continue
            try:
                category = await ctx.guild.create_category(saved.get("name", "Catégorie restaurée")[:100], reason=f"Snapshot V17 #{snapshot_id}")
                category_map[int(saved["id"])] = category
                created_channels += 1
            except discord.HTTPException:
                pass
        for saved in payload.get("channels", []):
            kind = saved.get("type")
            if kind == "category":
                continue
            name = str(saved.get("name") or "salon-restaure")[:100]
            if discord.utils.get(ctx.guild.channels, name=name):
                continue
            category = category_map.get(int(saved.get("category_id") or 0))
            try:
                if kind == "text":
                    await ctx.guild.create_text_channel(
                        name,
                        category=category,
                        topic=saved.get("topic"),
                        slowmode_delay=int(saved.get("slowmode_delay") or 0),
                        nsfw=bool(saved.get("nsfw", False)),
                        reason=f"Snapshot V17 #{snapshot_id}",
                    )
                    created_channels += 1
                elif kind == "voice":
                    await ctx.guild.create_voice_channel(
                        name,
                        category=category,
                        bitrate=min(int(saved.get("bitrate") or 64000), ctx.guild.bitrate_limit),
                        user_limit=int(saved.get("user_limit") or 0),
                        reason=f"Snapshot V17 #{snapshot_id}",
                    )
                    created_channels += 1
            except discord.HTTPException:
                continue
        await panels.editer(msg, panels.depuis_embed(embeds.success(f'Snapshot restauré : **{created_roles} rôle(s)** et **{created_channels} salon(s)/catégorie(s)** recréés.')))

    @commands.hybrid_command(name="smartlockdown", description="Verrouillage intelligent réversible du serveur.", with_app_command=False)
    @checks.is_owner_or_admin_for("securite")
    async def smartlockdown(self, ctx: commands.Context, mode: str):
        mode = mode.casefold().strip()
        if mode not in {"on", "off", "activer", "desactiver", "désactiver"}:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez `+smartlockdown on` ou `+smartlockdown off`.')))
        enable = mode in {"on", "activer"}
        changed = 0
        if enable:
            await create_snapshot(self.bot, ctx.guild, "auto-before-smartlockdown", ctx.author.id)
            await self.bot.db.execute("DELETE FROM v17_lockdown_state WHERE guild_id=?", (ctx.guild.id,))
            for channel in ctx.guild.text_channels:
                if not channel.permissions_for(ctx.guild.me).manage_channels:
                    continue
                overwrite = channel.overwrites_for(ctx.guild.default_role)
                old = overwrite.send_messages
                state_value = -1 if old is None else (1 if old else 0)
                await self.bot.db.execute(
                    "INSERT OR REPLACE INTO v17_lockdown_state (guild_id,channel_id,send_messages_state,saved_at) VALUES (?,?,?,?)",
                    (ctx.guild.id, channel.id, state_value, now()),
                )
                if old is not False:
                    overwrite.send_messages = False
                    try:
                        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Smart lockdown par {ctx.author}")
                        changed += 1
                    except discord.HTTPException:
                        pass
        else:
            rows = await self.bot.db.fetchall("SELECT * FROM v17_lockdown_state WHERE guild_id=?", (ctx.guild.id,))
            for row in rows:
                channel = ctx.guild.get_channel(row["channel_id"])
                if not isinstance(channel, discord.TextChannel):
                    continue
                overwrite = channel.overwrites_for(ctx.guild.default_role)
                saved = int(row["send_messages_state"])
                overwrite.send_messages = None if saved == -1 else bool(saved)
                try:
                    await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Fin smart lockdown par {ctx.author}")
                    changed += 1
                except discord.HTTPException:
                    pass
            await self.bot.db.execute("DELETE FROM v17_lockdown_state WHERE guild_id=?", (ctx.guild.id,))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Smart lockdown {('activé' if enable else 'désactivé')} — **{changed} salon(s)** modifié(s).")))

    @commands.hybrid_group(name="nukewhitelist", description="Whitelist anti-nuke par utilisateur, rôle et action.")
    @checks.is_owner_or_admin_for("securite")
    async def nukewhitelist(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM v17_antinuke_whitelist WHERE guild_id=? ORDER BY subject_type,subject_id", (ctx.guild.id,))
        text = "\n".join(
            f"• {('<@'+str(r['subject_id'])+'>') if r['subject_type']=='user' else ('<@&'+str(r['subject_id'])+'>')} — `{r['action']}`"
            for r in rows[:30]
        ) or "Aucune règle V17."
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info(text, title='Whitelist anti-nuke V17')))

    @nukewhitelist.command(name="user")
    async def nukewhitelist_user(self, ctx: commands.Context, membre: discord.Member, action: str = "all"):
        action = action.casefold()
        if action not in VALID_NUKE_ACTIONS:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Action : `all`, `channel_delete` ou `role_delete`.')))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO v17_antinuke_whitelist (guild_id,subject_type,subject_id,action,added_by,created_at) VALUES (?,'user',?,?,?,?)",
            (ctx.guild.id, membre.id, action, ctx.author.id, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} autorisé pour `{action}`.')))

    @nukewhitelist.command(name="role")
    async def nukewhitelist_role(self, ctx: commands.Context, role: discord.Role, action: str = "all"):
        action = action.casefold()
        if action not in VALID_NUKE_ACTIONS:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Action : `all`, `channel_delete` ou `role_delete`.')))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO v17_antinuke_whitelist (guild_id,subject_type,subject_id,action,added_by,created_at) VALUES (?,'role',?,?,?,?)",
            (ctx.guild.id, role.id, action, ctx.author.id, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{role.mention} autorisé pour `{action}`.')))

    @nukewhitelist.command(name="remove")
    async def nukewhitelist_remove(self, ctx: commands.Context, identifiant: str, action: str = "all"):
        raw = identifiant.strip().replace("<@&", "").replace("<@", "").replace("!", "").replace(">", "")
        try:
            subject_id = int(raw)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Mention ou ID invalide.')))
        await self.bot.db.execute(
            "DELETE FROM v17_antinuke_whitelist WHERE guild_id=? AND subject_id=? AND action=?",
            (ctx.guild.id, subject_id, action.casefold()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success('Règle supprimée.')))

    @commands.hybrid_command(name="suspiciouslist", description="Afficher les comptes récents à surveiller.", with_app_command=False)
    @checks.is_owner_or_admin_for("securite")
    async def suspiciouslist(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM v17_suspicious_accounts WHERE guild_id=? AND score>0 ORDER BY score DESC,joined_at DESC LIMIT 20",
            (ctx.guild.id,),
        )
        text = "\n".join(
            f"• <@{r['user_id']}> — **{r['score']}/9** — {', '.join(json.loads(r['reasons_json'] or '[]'))}"
            for r in rows
        ) or "Aucun compte signalé."
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info(text[:4000], title='Comptes à surveiller — aucune sanction automatique')))

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        command = ctx.command.root_parent or ctx.command if ctx.command else None
        if command is None or command.name.casefold() != "warn" or ctx.guild is None:
            return
        member = None
        try:
            # Le convertisseur garde les arguments déjà analysés dans ctx.args.
            member = next((value for value in ctx.args if isinstance(value, discord.Member) and value.id != ctx.author.id), None)
        except Exception:
            pass
        if member is None:
            return
        policy = await self._policy(ctx.guild.id)
        if not policy["enabled"]:
            return
        count_row = await self.bot.db.fetchone("SELECT COUNT(*) c FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
        count = int(count_row["c"] if count_row else 0)
        choices = []
        if count >= int(policy["ban_warns"]):
            choices.append(("ban", int(policy["ban_warns"]), 0))
        elif count >= int(policy["tempban_warns"]):
            choices.append(("tempban", int(policy["tempban_warns"]), int(policy["tempban_seconds"])))
        elif count >= int(policy["mute_warns"]):
            choices.append(("mute", int(policy["mute_warns"]), int(policy["mute_seconds"])))
        if not choices:
            return
        level, threshold, seconds = choices[0]
        reservation = await self.bot.db.execute(
            "INSERT OR IGNORE INTO v17_sanction_escalations (guild_id,user_id,level,warning_count,triggered_at) VALUES (?,?,?,?,?)",
            (ctx.guild.id, member.id, level, count, now()),
        )
        if reservation.rowcount < 1:
            return
        error = checks.check_bot_hierarchy(ctx.guild, member)
        if error:
            await self.bot.db.execute("DELETE FROM v17_sanction_escalations WHERE guild_id=? AND user_id=? AND level=?", (ctx.guild.id, member.id, level))
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Palier {level} atteint, mais action impossible : {error}')))
        reason = f"Sanction progressive V17 : {count} avertissements (palier {threshold})"
        try:
            if level == "mute":
                await member.timeout(discord.utils.utcnow() + timedelta(seconds=seconds), reason=reason)
            elif level == "tempban":
                await ctx.guild.ban(member, reason=reason, delete_message_seconds=0)
                await self.bot.db.execute("INSERT INTO tempactions (guild_id,user_id,action,expires_at) VALUES (?,?,'ban',?)", (ctx.guild.id, member.id, now() + seconds))
            else:
                await ctx.guild.ban(member, reason=reason, delete_message_seconds=0)
            action_name = "tempban" if level == "tempban" else level
            case_number = await self.bot.db.record_sanction(ctx.guild.id, member.id, self.bot.user.id, action_name, reason, seconds or None)
            await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'{member.mention} a atteint **{count} avertissements** : **{level}** appliqué automatiquement. Dossier **#{case_number}**.', title='Sanction progressive')))
        except discord.HTTPException:
            await self.bot.db.execute("DELETE FROM v17_sanction_escalations WHERE guild_id=? AND user_id=? AND level=?", (ctx.guild.id, member.id, level))
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le palier a été atteint mais Discord a refusé la sanction automatique.')))


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    await ensure_schema(bot)
    register_command_policy(
        moderation={"protectmember", "caseproof", "casefull", "staffnote", "userhistory", "modundo", "sanctionpolicy"},
        security={"serversnapshot", "smartlockdown", "nukewhitelist", "suspiciouslist"},
    )
    if bot.get_cog("V17ModerationSecurity") is None:
        await bot.add_cog(V17ModerationSecurity(bot))
    install_moderation_guards(bot)
    install_danger_confirmations(bot)
    install_antinuke_restore(bot)
    install_join_risk_detection(bot)


__all__ = ["install"]
