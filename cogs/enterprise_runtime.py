"""Installation idempotente de la suite Enterprise depuis le chargeur historique des cogs.

Le recours de bannissement est volontairement préparé et envoyé AVANT l'appel Discord
qui bannit le membre. Après un ban, le bot peut perdre la possibilité d'ouvrir un MP avec
l'utilisateur puisqu'ils ne partagent plus forcément de serveur. Le lien de recours est
donc envoyé pendant que le membre est encore présent, puis l'événement on_member_ban ne
fait que rattacher le numéro de dossier réel au recours déjà créé.
"""
from __future__ import annotations

import asyncio
import logging
import secrets

import discord
from discord.ext import commands

from database.db import now


logger = logging.getLogger("bot.enterprise-runtime")
_PREBAN_REUSE_SECONDS = 120


async def _install_preban_appeal_delivery(bot: commands.Bot, service) -> None:
    """Branche les recours sur le MP de sanction AVANT le bannissement réel.

    On enveloppe uniquement _send_sanction_dm du Cog Moderation. Les autres sanctions
    gardent exactement leur comportement. Pour ban/tempban, le MP de sanction historique
    part d'abord, puis un second MP très court contient le lien personnel de recours. Si
    le serveur a désactivé le MP de sanction, le recours reste indépendant et peut quand
    même être envoyé tant que les recours Enterprise sont activés.
    """
    moderation = bot.get_cog("Moderation")
    if moderation is None:
        return

    cls = type(moderation)
    current = cls._send_sanction_dm
    if getattr(current, "_sentrix_preban_appeal", False):
        return

    original = current
    from . import enterprise_suite as enterprise_module

    async def send_sanction_dm_with_appeal(
        self,
        ctx: commands.Context,
        target: discord.abc.User,
        action: str,
        reason: str,
        duration_seconds: int | None = None,
    ) -> bool:
        # Le message de sanction existant reste la source canonique et conserve toutes les
        # personnalisations +sanctiondm. On le laisse partir en premier.
        normal_sent = await original(self, ctx, target, action, reason, duration_seconds)

        if action not in {"ban", "tempban"} or ctx.guild is None:
            return normal_sent

        runtime_service = bot.get_cog("EnterpriseSuite") or service
        if runtime_service is None:
            return normal_sent

        try:
            settings = await runtime_service.get_settings(ctx.guild.id)
            if not int(settings.get("appeals_enabled", 1)):
                return normal_sent

            # Un nouveau ban invalide les anciens recours encore actifs pour ce membre.
            await bot.db.execute(
                "UPDATE ban_appeals SET status='superseded', reviewed_at=? "
                "WHERE guild_id=? AND user_id=? AND status IN ('awaiting_user','open','more_info')",
                (now(), ctx.guild.id, target.id),
            )

            token = secrets.token_urlsafe(32)
            cur = await bot.db.execute(
                "INSERT INTO ban_appeals "
                "(guild_id,user_id,token_hash,status,ban_reason,case_number,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    ctx.guild.id,
                    target.id,
                    enterprise_module._token_hash(token),
                    "awaiting_user",
                    str(reason or "Aucune raison fournie")[:1500],
                    None,
                    now(),
                ),
            )
            appeal_id = int(cur.lastrowid)
            link = f"{enterprise_module.config.DASHBOARD_PUBLIC_URL}/appeal/{token}"
            appeal_message = (
                f"Recours de bannissement pour **{ctx.guild.name}**\n"
                "Si vous souhaitez contester cette sanction, utilisez ce lien personnel :\n"
                f"{link}\n\n"
                "Ne partagez pas ce lien."
            )

            try:
                await target.send(
                    appeal_message[:2000],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException):
                # Le membre est encore présent à ce moment-là. Si même ce MP échoue, on
                # supprime ce recours non livré : on_member_ban pourra tenter le fallback
                # historique après le ban au lieu de réutiliser un token jamais reçu.
                await bot.db.execute("DELETE FROM ban_appeals WHERE id=?", (appeal_id,))
                return normal_sent

            await runtime_service.infra.mirror_event(
                "ban_appeal_created_preban",
                ctx.guild.id,
                {"appeal_id": appeal_id, "user_id": target.id, "case_number": None},
                now(),
            )
            return True
        except Exception as exc:
            try:
                await runtime_service._record_error(ctx.guild.id, "appeal:preban_dm", exc)
            except Exception:
                logger.exception("Impossible de journaliser l'échec du recours pré-ban.")
            return normal_sent

    send_sanction_dm_with_appeal._sentrix_preban_appeal = True
    send_sanction_dm_with_appeal._sentrix_original = original
    cls._send_sanction_dm = send_sanction_dm_with_appeal
    logger.info("Recours de bannissement : lien MP pré-ban activé sur ban/tempban.")


async def _install_preban_appeal_reuse(service) -> None:
    """Empêche on_member_ban de créer un deuxième recours juste après le MP pré-ban."""
    cls = type(service)
    current = cls.create_appeal_for_ban
    if getattr(current, "_sentrix_preban_reuse", False):
        return

    original = current

    async def create_appeal_for_ban_reusing_preban(self, guild, user):
        cutoff = now() - _PREBAN_REUSE_SECONDS
        recent = await self.bot.db.fetchone(
            "SELECT id,user_id,ban_reason,case_number,created_at FROM ban_appeals "
            "WHERE guild_id=? AND user_id=? AND status='awaiting_user' AND created_at>=? "
            "ORDER BY id DESC LIMIT 1",
            (guild.id, user.id, cutoff),
        )
        if recent:
            # log_sanction() s'exécute juste après guild.ban(). À l'arrivée de cet event,
            # on récupère donc le vrai dossier si disponible et on complète le recours
            # déjà remis au membre, sans remplacer son token.
            case_number, latest_reason = await self._latest_ban_case(guild.id, user.id)
            if case_number is not None:
                await self.bot.db.execute(
                    "UPDATE ban_appeals SET case_number=?, ban_reason=? WHERE id=?",
                    (
                        case_number,
                        str(latest_reason or recent["ban_reason"] or "Aucune raison fournie")[:1500],
                        int(recent["id"]),
                    ),
                )
            payload = {
                "appeal_id": int(recent["id"]),
                "user_id": user.id,
                "case_number": case_number,
                "preban_delivered": True,
            }
            await self.infra.mirror_event("ban_appeal_reconciled", guild.id, payload, now())
            return payload
        return await original(self, guild, user)

    create_appeal_for_ban_reusing_preban._sentrix_preban_reuse = True
    create_appeal_for_ban_reusing_preban._sentrix_original = original
    cls.create_appeal_for_ban = create_appeal_for_ban_reusing_preban
    logger.info("Recours de bannissement : déduplication pré-ban/on_member_ban activée.")


async def install(bot: commands.Bot):
    service = bot.get_cog("EnterpriseSuite")

    if service is None:
        from . import enterprise_suite as module

        async def ready(self):
            try:
                await self.bot.wait_until_ready()
            except RuntimeError:
                # Bot construit hors connexion (audits CI) : aucune boucle de fond ne doit
                # exécuter son premier tick contre un client Discord jamais démarré.
                raise asyncio.CancelledError

        async def ready_backup(self):
            try:
                await self.bot.wait_until_ready()
            except RuntimeError:
                raise asyncio.CancelledError
            await asyncio.sleep(90)

        if not getattr(module.EnterpriseSuite, "_sentrix_safe_before_loops", False):
            module.EnterpriseSuite.metrics_loop.before_loop(ready)
            module.EnterpriseSuite.automation_loop.before_loop(ready)
            module.EnterpriseSuite.analytics_loop.before_loop(ready)
            module.EnterpriseSuite.backup_loop.before_loop(ready_backup)
            module.EnterpriseSuite._sentrix_safe_before_loops = True

        await module.setup(bot)
        service = bot.get_cog("EnterpriseSuite")

    if service is not None:
        await _install_preban_appeal_reuse(service)
        await _install_preban_appeal_delivery(bot, service)
    return service
