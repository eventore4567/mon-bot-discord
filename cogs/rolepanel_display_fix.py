"""Correction anti-doublon des panneaux de rôles SentriX.

Les panneaux sont désormais reconnus grâce à leurs custom_id Discord et non grâce au titre
de l'embed. Le style global peut transformer « Choix des rôles » en « SENTRIX / CONFIGURATION »
ou « Notifications » en « SENTRIX / UTILITAIRES » ; se baser sur le titre recréait donc un
nouveau panneau à chaque +create-server.

Ce module :
- réutilise toujours le panneau Choix des rôles déjà présent ;
- réutilise toujours le panneau Notifications déjà présent ;
- supprime les anciens doublons créés par les précédentes exécutions ;
- nettoie les entrées SQL des panneaux Notifications supprimés ;
- effectue aussi un nettoyage unique au démarrage du bot.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.rolepanel.display-fix")
_INSTALLED = False


CHOICE_OPEN_IDS = {
    "sentrix:selfroles:open:games",
    "sentrix:selfroles:open:languages",
    "sentrix:selfroles:open:colors",
}
NOTIFICATION_OPEN_IDS = {
    "sentrix:notification-open:add",
    "sentrix:notification-open:remove",
}


def _component_custom_ids(message: discord.Message) -> set[str]:
    result: set[str] = set()
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            custom_id = getattr(child, "custom_id", None)
            if custom_id:
                result.add(str(custom_id))
    return result


def _is_choice_panel(message: discord.Message, bot_user_id: int) -> bool:
    """Détecte le panneau même si le style global a remplacé son titre/footer."""
    if message.author.id != bot_user_id:
        return False
    custom_ids = _component_custom_ids(message)
    if custom_ids & CHOICE_OPEN_IDS:
        return True
    # Compatibilité avec de très vieux messages dont les composants peuvent être absents.
    if not message.embeds:
        return False
    title = (message.embeds[0].title or "").strip().casefold()
    return title == "choix des rôles".casefold()


def _is_notification_panel(message: discord.Message, bot_user_id: int) -> bool:
    """Détecte le panneau Notifications indépendamment du titre premium appliqué."""
    if message.author.id != bot_user_id:
        return False
    custom_ids = _component_custom_ids(message)
    if custom_ids & NOTIFICATION_OPEN_IDS:
        return True
    if not message.embeds:
        return False
    title = (message.embeds[0].title or "").strip().casefold()
    return title == "notifications"


async def _history_panels(
    channel: discord.TextChannel,
    bot_user_id: int,
    *,
    limit: int = 200,
) -> tuple[list[discord.Message], list[discord.Message]]:
    choices: list[discord.Message] = []
    notifications: list[discord.Message] = []
    async for candidate in channel.history(limit=limit):
        if _is_choice_panel(candidate, bot_user_id):
            choices.append(candidate)
        elif _is_notification_panel(candidate, bot_user_id):
            notifications.append(candidate)
    # Discord renvoie l'historique du plus récent au plus ancien.
    return choices, notifications


async def _delete_messages(messages: list[discord.Message], reason: str) -> int:
    deleted = 0
    for message in messages:
        try:
            await message.delete(reason=reason)
            deleted += 1
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
    return deleted


async def _cleanup_notification_rows(
    bot: commands.Bot,
    guild_id: int,
    channel_id: int,
    keep_message_id: int | None,
) -> None:
    try:
        if keep_message_id is None:
            await bot.db.execute(
                "DELETE FROM notification_role_panels WHERE guild_id = ? AND channel_id = ?",
                (guild_id, channel_id),
            )
        else:
            await bot.db.execute(
                "DELETE FROM notification_role_panels "
                "WHERE guild_id = ? AND channel_id = ? AND message_id != ?",
                (guild_id, channel_id, keep_message_id),
            )
    except Exception:
        logger.exception(
            "Nettoyage SQL des panneaux Notifications impossible sur %s/%s.",
            guild_id,
            channel_id,
        )


async def _dedupe_channel(
    bot: commands.Bot,
    channel: discord.TextChannel,
    *,
    preferred_notification_id: int | None = None,
) -> tuple[int, int]:
    """Garde un seul panneau de chaque type dans le salon."""
    bot_user = bot.user or channel.guild.me
    if bot_user is None:
        return 0, 0

    try:
        choices, notifications = await _history_panels(channel, bot_user.id)
    except (discord.Forbidden, discord.HTTPException):
        return 0, 0

    choice_deleted = 0
    notification_deleted = 0

    if choices:
        # Le plus récent est conservé, tous les anciens clones disparaissent.
        choice_deleted = await _delete_messages(
            choices[1:],
            "Nettoyage des panneaux Choix des rôles SentriX en double",
        )

    keep_notification: discord.Message | None = None
    if notifications:
        if preferred_notification_id is not None:
            keep_notification = next(
                (message for message in notifications if message.id == preferred_notification_id),
                None,
            )
        if keep_notification is None:
            keep_notification = notifications[0]

        notification_deleted = await _delete_messages(
            [message for message in notifications if message.id != keep_notification.id],
            "Nettoyage des panneaux Notifications SentriX en double",
        )
        await _cleanup_notification_rows(
            bot,
            channel.guild.id,
            channel.id,
            keep_notification.id,
        )

    if choice_deleted or notification_deleted:
        logger.info(
            "Rolepanels nettoyés dans %s (%s) : %s choix + %s notifications supprimés.",
            channel.guild.name,
            channel.id,
            choice_deleted,
            notification_deleted,
        )
    return choice_deleted, notification_deleted


async def _ensure_notification_cog(bot: commands.Bot) -> None:
    from . import rolepanel_notifications

    # L'installation normale dépend de l'ordre de chargement de l'ancien +rolepanel.
    # On la tente d'abord, puis on force uniquement le cog si nécessaire.
    await rolepanel_notifications.install(bot)
    if bot.get_cog("NotificationRolePanels") is not None:
        return

    await bot.db.execute(rolepanel_notifications._SCHEMA)
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_role_panels_guild "
        "ON notification_role_panels (guild_id, created_at)"
    )

    if bot.get_command("rolepanel") is not None:
        bot.remove_command("rolepanel")
    if bot.get_command("rolepanel-refresh") is not None:
        bot.remove_command("rolepanel-refresh")

    await bot.add_cog(rolepanel_notifications.NotificationRolePanels(bot))
    rolepanel_notifications._INSTALLED = True
    logger.info("Panneau Notifications forcé après chargement tardif des cogs.")


async def _startup_cleanup(bot: commands.Bot) -> None:
    """Supprime une seule fois les clones déjà présents avant ce correctif."""
    if getattr(bot, "_sentrix_rolepanel_cleanup_done", False):
        return
    bot._sentrix_rolepanel_cleanup_done = True

    channel_ids_by_guild: dict[int, set[int]] = {}
    try:
        rows = await bot.db.fetchall(
            "SELECT guild_id, channel_id FROM notification_role_panels"
        )
        for row in rows:
            channel_ids_by_guild.setdefault(int(row["guild_id"]), set()).add(int(row["channel_id"]))
    except Exception:
        logger.exception("Lecture des panneaux Notifications pour nettoyage initial impossible.")

    total_choice = 0
    total_notifications = 0
    for guild in bot.guilds:
        candidate_ids = set(channel_ids_by_guild.get(guild.id, set()))
        # +create-server place les deux panneaux dans choix-des-rôles. On ajoute aussi ce
        # salon même s'il n'existe plus dans la base, afin de réparer les vieux doublons.
        for channel in guild.text_channels:
            plain = channel.name.casefold().replace("_", "-")
            if "choix" in plain and ("rôle" in plain or "role" in plain):
                candidate_ids.add(channel.id)

        for channel_id in candidate_ids:
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            choice_deleted, notification_deleted = await _dedupe_channel(bot, channel)
            total_choice += choice_deleted
            total_notifications += notification_deleted

    logger.info(
        "Nettoyage initial rolepanels terminé : %s choix + %s notifications supprimés.",
        total_choice,
        total_notifications,
    )


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import server_choice_roles
    from . import server_builder_ready_setup

    original_publish = server_choice_roles.publish_or_refresh
    original_ensure_role_panels = server_builder_ready_setup._ensure_role_panels

    async def publish_or_refresh_fixed(bot_obj: commands.Bot, channel: discord.TextChannel) -> discord.Message:
        bot_user = bot_obj.user or channel.guild.me
        if bot_user is None:
            return await original_publish(bot_obj, channel)

        try:
            candidates, _notifications = await _history_panels(channel, bot_user.id)
        except (discord.Forbidden, discord.HTTPException):
            return await original_publish(bot_obj, channel)

        view = server_choice_roles.ServerSelfRoleView()
        if candidates:
            # On réutilise toujours le message le plus récent, quel que soit son titre actuel.
            message = candidates[0]
            try:
                await panels.editer(message, panels.avec_composants(panels.depuis_embed(server_choice_roles.build_embed()), view))
            except discord.HTTPException:
                pass
            await _delete_messages(
                candidates[1:],
                "Nettoyage des panneaux Choix des rôles SentriX en double",
            )
            return message

        return await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(server_choice_roles.build_embed()), view))

    async def ensure_role_panels_fixed(
        bot_obj: commands.Bot,
        guild: discord.Guild,
        channel: discord.TextChannel,
        creator_id: int,
    ) -> str:
        await _ensure_notification_cog(bot_obj)

        # Nettoie d'abord les clones existants : l'ancienne fonction peut ainsi retrouver
        # proprement son message SQL au lieu d'empiler encore un panneau.
        await _dedupe_channel(bot_obj, channel)
        result = await original_ensure_role_panels(bot_obj, guild, channel, creator_id)

        # Le panneau Notifications est désormais détecté par ses custom_id. Le titre peut
        # donc être SENTRIX / UTILITAIRES sans déclencher une nouvelle publication.
        bot_user = bot_obj.user or guild.me
        notification_found = False
        preferred_notification_id: int | None = None
        row = await bot_obj.db.fetchone(
            "SELECT * FROM notification_role_panels "
            "WHERE guild_id = ? AND channel_id = ? ORDER BY created_at DESC LIMIT 1",
            (guild.id, channel.id),
        )
        if row:
            preferred_notification_id = int(row["message_id"])

        if bot_user is not None:
            try:
                _choices, notifications = await _history_panels(channel, bot_user.id)
                notification_found = bool(notifications)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if not notification_found:
            cog = bot_obj.get_cog("NotificationRolePanels")
            if cog is not None:
                from . import rolepanel_notifications

                roles = await cog._ensure_roles(guild)
                role_ids = [role.id for role in roles]
                view = rolepanel_notifications.NotificationRoleView(guild, role_ids)
                message = await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(rolepanel_notifications._panel_embed(guild, role_ids)), view))
                await cog._save_panel(message, creator_id, role_ids)
                bot_obj.add_view(
                    rolepanel_notifications.NotificationRoleView(guild, role_ids),
                    message_id=message.id,
                )
                preferred_notification_id = message.id
                result = f"{result} + panneau notifications réparé"

        # Dernier filet : un seul Choix des rôles + un seul Notifications doivent rester.
        await _dedupe_channel(
            bot_obj,
            channel,
            preferred_notification_id=preferred_notification_id,
        )
        return result

    server_choice_roles.publish_or_refresh = publish_or_refresh_fixed
    server_builder_ready_setup._ensure_role_panels = ensure_role_panels_fixed

    async def cleanup_on_ready() -> None:
        try:
            await _startup_cleanup(bot)
        except Exception:
            logger.exception("Nettoyage initial des rolepanels impossible.")

    bot.add_listener(cleanup_on_ready, "on_ready")
    if bot.is_ready():
        try:
            asyncio.create_task(cleanup_on_ready(), name="sentrix-rolepanel-dedupe")
        except RuntimeError:
            pass

    _INSTALLED = True
    logger.info(
        "Correction rolepanel V2 activée : détection par custom_id + nettoyage automatique des doublons."
    )
