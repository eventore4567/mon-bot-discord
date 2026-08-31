"""SentriX V86 — fiabilise la livraison des logs dans les salons configurés.

Le renderer Components V2 joint une bannière PNG à CHAQUE log. Un salon qui autorise
l'envoi de messages mais refuse ``attach_files`` paraît donc correctement configuré dans
+setup, alors que le transport refuse ensuite d'y envoyer quoi que ce soit.

V86 :
- répare les permissions du bot sur tous les salons de logs déjà configurés ;
- répare immédiatement le salon choisi depuis +setup ;
- effectue le même pré-vol avant chaque envoi de log ;
- ne modifie jamais les permissions de @everyone ni celles du staff.
"""
from __future__ import annotations

import asyncio
import functools
import logging

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.logs-delivery-v86")

_REQUIRED = {
    "view_channel": True,
    "send_messages": True,
    "embed_links": True,
    "attach_files": True,
    "read_message_history": True,
}


def _missing_permissions(channel: discord.abc.GuildChannel, member: discord.Member) -> list[str]:
    perms = channel.permissions_for(member)
    return [name for name, wanted in _REQUIRED.items() if wanted and not getattr(perms, name, False)]


async def ensure_log_channel_permissions(
    guild: discord.Guild,
    channel: discord.abc.GuildChannel,
    *,
    reason: str = "SentriX : permissions nécessaires aux logs Components V2",
) -> tuple[bool, str]:
    """Garantit uniquement les droits du bot, sans toucher aux autres overwrites."""
    me = guild.me
    if me is None:
        return False, "membre bot introuvable"

    missing = _missing_permissions(channel, me)
    if not missing:
        return True, "ok"

    # Si le bot possède Administrateur, permissions_for devrait déjà retourner True.
    # Sinon il doit pouvoir modifier les overwrites pour se réparer lui-même.
    can_edit = bool(me.guild_permissions.manage_channels or me.guild_permissions.administrator)
    if not can_edit:
        return False, "permissions manquantes : " + ", ".join(missing)

    try:
        overwrite = channel.overwrites_for(me)
        for name, value in _REQUIRED.items():
            setattr(overwrite, name, value)
        await channel.set_permissions(me, overwrite=overwrite, reason=reason)
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning(
            "Impossible de réparer les permissions logs guild=%s channel=%s: %s",
            guild.id,
            channel.id,
            exc,
        )
        return False, "Discord refuse la modification des permissions"
    except Exception:
        logger.exception(
            "Erreur de réparation permissions logs guild=%s channel=%s",
            guild.id,
            channel.id,
        )
        return False, "erreur interne pendant la réparation"

    remaining = _missing_permissions(channel, me)
    if remaining:
        # Le cache Discord peut être légèrement en retard. On relit directement
        # l'overwrite que nous venons d'écrire afin d'éviter un faux négatif immédiat.
        overwrite = channel.overwrites_for(me)
        still_missing = [
            name for name in remaining
            if getattr(overwrite, name, None) is not True
        ]
        if still_missing:
            return False, "permissions toujours manquantes : " + ", ".join(still_missing)

    logger.warning(
        "Permissions logs réparées guild=%s channel=%s (%s)",
        guild.id,
        channel.id,
        ", ".join(missing),
    )
    return True, "réparé"


async def repair_guild_log_channels(bot: commands.Bot, guild: discord.Guild) -> int:
    repaired = 0
    seen: set[int] = set()
    for log_type, meta in list(log_service.LOG_TYPES.items()):
        if not meta.get("emits"):
            continue
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
        except Exception:
            logger.exception("Lecture route log impossible guild=%s type=%s", guild.id, log_type)
            continue
        if not setting.get("enabled") or not setting.get("channel_id"):
            continue
        channel_id = int(setting["channel_id"])
        if channel_id in seen:
            continue
        seen.add(channel_id)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        before = bool(_missing_permissions(channel, guild.me)) if guild.me else False
        ok, _reason = await ensure_log_channel_permissions(guild, channel)
        if ok and before:
            repaired += 1
    return repaired


def _install_send_preflight() -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_delivery_v86", False):
        return

    @functools.wraps(current)
    async def send_log_v86(
        bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
        *,
        view: discord.ui.View | None = None,
        event_key: str | None = None,
        identity_name: str | None = None,
        identity_id: int | None = None,
        identity_icon: str | None = None,
    ) -> bool:
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
            if setting.get("enabled") and setting.get("channel_id"):
                channel = guild.get_channel(int(setting["channel_id"]))
                if isinstance(channel, discord.TextChannel):
                    await ensure_log_channel_permissions(
                        guild,
                        channel,
                        reason="SentriX : réparation automatique avant envoi d'un log",
                    )
        except Exception:
            # Le transport officiel garde la décision finale et ses logs d'erreur.
            logger.exception("Pré-vol V86 impossible guild=%s type=%s", guild.id, log_type)

        return await current(
            bot,
            guild,
            log_type,
            embed,
            file,
            view=view,
            event_key=event_key,
            identity_name=identity_name,
            identity_id=identity_id,
            identity_icon=identity_icon,
        )

    send_log_v86._sentrix_delivery_v86 = True
    send_log_v86._sentrix_previous = current
    log_service.send_log = send_log_v86
    logger.info("Pré-vol de livraison Logs V86 installé.")


def _install_setup_permission_guard() -> None:
    try:
        from . import setup_control_center as setup_ui
    except Exception:
        logger.exception("Setup Logs indisponible pour V86.")
        return

    current = setup_ui.LogChannelSelect.callback
    if getattr(current, "_sentrix_delivery_v86", False):
        return

    @functools.wraps(current)
    async def callback_v86(self, interaction: discord.Interaction):
        if self.values:
            channel = self.values[0]
            if interaction.guild is None or not isinstance(channel, discord.TextChannel):
                return await interaction.response.send_message(
                    "Choisissez un salon textuel valide pour les logs.",
                    ephemeral=True,
                )
            ok, reason = await ensure_log_channel_permissions(
                interaction.guild,
                channel,
                reason="SentriX : salon choisi dans +setup → Logs",
            )
            if not ok:
                return await interaction.response.send_message(
                    "Je ne peux pas utiliser ce salon pour les logs : " + reason
                    + ". Donnez-moi **Gérer les salons** ou autorisez Voir le salon, "
                      "Envoyer des messages, Intégrer des liens, Joindre des fichiers et Lire l'historique.",
                    ephemeral=True,
                )
        return await current(self, interaction)

    callback_v86._sentrix_delivery_v86 = True
    callback_v86._sentrix_previous = current
    setup_ui.LogChannelSelect.callback = callback_v86
    logger.info("Garde permissions +setup Logs V86 installé.")


class LogsDeliveryV86(commands.Cog, name="LogsDeliveryV86"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="logsdiag")
    async def logsdiag(self, ctx: commands.Context):
        """Diagnostic administrateur des routes réellement utilisables."""
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return
        if not (ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.manage_guild):
            return await ctx.send("Cette commande est réservée aux administrateurs.")

        lines: list[str] = []
        for log_type, meta in list(log_service.LOG_TYPES.items()):
            if not meta.get("emits"):
                continue
            try:
                setting = await log_service.get_log_setting(self.bot, ctx.guild.id, log_type)
                channel_id = setting.get("channel_id")
                channel = ctx.guild.get_channel(int(channel_id)) if channel_id else None
                if not setting.get("enabled"):
                    state = "INACTIF"
                elif not isinstance(channel, discord.TextChannel):
                    state = "SALON INTROUVABLE"
                else:
                    ok, reason = await ensure_log_channel_permissions(ctx.guild, channel)
                    state = "OK" if ok else reason.upper()
                destination = channel.mention if isinstance(channel, discord.TextChannel) else "aucun"
                lines.append(f"**{meta.get('label', log_type)}** — {state} — {destination}")
            except Exception as exc:
                lines.append(f"**{meta.get('label', log_type)}** — ERREUR `{type(exc).__name__}`")

        text = "\n".join(lines)
        embed = discord.Embed(
            title="Diagnostic des logs SentriX",
            description=text[:4000] or "Aucune route de logs.",
            colour=discord.Colour.green() if all("— OK —" in line or "INACTIF" in line for line in lines) else discord.Colour.orange(),
        )
        await ctx.send(embed=embed)


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    # V85 se pose à ~6 s après READY. V86 arrive ensuite et reste l'autorité de livraison.
    await asyncio.sleep(9)
    _install_send_preflight()
    _install_setup_permission_guard()

    total = 0
    for guild in list(bot.guilds):
        try:
            total += await repair_guild_log_channels(bot, guild)
        except Exception:
            logger.exception("Réparation V86 impossible guild=%s", guild.id)

    if bot.get_cog("LogsDeliveryV86") is None:
        await bot.add_cog(LogsDeliveryV86(bot))
    logger.warning("Logs Delivery V86 actif — %s salon(s) réparé(s).", total)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_logs_delivery_v86", False):
        return
    bot._sentrix_logs_delivery_v86 = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-logs-delivery-v86")
