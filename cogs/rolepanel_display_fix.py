"""Correction d'affichage des panneaux de rôles SentriX.

Le style global peut remplacer les footers des embeds. Ce module détecte donc les
panneaux grâce à leur titre + custom_id des boutons, supprime les doublons et garantit
que le panneau Notifications est installé avant la migration de +create-server.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.rolepanel.display-fix")
_INSTALLED = False


def _component_custom_ids(message: discord.Message) -> set[str]:
    result: set[str] = set()
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            custom_id = getattr(child, "custom_id", None)
            if custom_id:
                result.add(str(custom_id))
    return result


def _is_choice_panel(message: discord.Message, bot_user_id: int) -> bool:
    if message.author.id != bot_user_id or not message.embeds:
        return False
    embed = message.embeds[0]
    if (embed.title or "").strip().casefold() != "choix des rôles".casefold():
        return False
    custom_ids = _component_custom_ids(message)
    return any(value.startswith("sentrix:selfroles:open:") for value in custom_ids)


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

        candidates: list[discord.Message] = []
        try:
            async for candidate in channel.history(limit=100):
                if _is_choice_panel(candidate, bot_user.id):
                    candidates.append(candidate)
        except (discord.Forbidden, discord.HTTPException):
            return await original_publish(bot_obj, channel)

        view = server_choice_roles.ServerSelfRoleView()
        if candidates:
            # history() renvoie du plus récent au plus ancien : on garde le plus récent.
            message = candidates[0]
            try:
                await message.edit(embed=server_choice_roles.build_embed(), view=view)
            except discord.HTTPException:
                pass

            # Nettoie les anciens doublons créés quand le footer était remplacé par le style global.
            for duplicate in candidates[1:]:
                try:
                    await duplicate.delete(reason="Nettoyage d'un panneau Choix des rôles SentriX en double")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass
            return message

        return await channel.send(embed=server_choice_roles.build_embed(), view=view)

    async def ensure_role_panels_fixed(
        bot_obj: commands.Bot,
        guild: discord.Guild,
        channel: discord.TextChannel,
        creator_id: int,
    ) -> str:
        await _ensure_notification_cog(bot_obj)
        result = await original_ensure_role_panels(bot_obj, guild, channel, creator_id)

        # Vérifie visuellement que le panneau Notifications existe bien dans ce salon.
        notification_found = False
        try:
            async for message in channel.history(limit=100):
                if message.author.id != (guild.me.id if guild.me else 0) or not message.embeds:
                    continue
                if (message.embeds[0].title or "").strip().casefold() == "notifications":
                    custom_ids = _component_custom_ids(message)
                    if "sentrix:notification-open:add" in custom_ids:
                        notification_found = True
                        break
        except (discord.Forbidden, discord.HTTPException):
            pass

        if not notification_found:
            cog = bot_obj.get_cog("NotificationRolePanels")
            if cog is not None:
                from . import rolepanel_notifications
                roles = await cog._ensure_roles(guild)
                role_ids = [role.id for role in roles]
                view = rolepanel_notifications.NotificationRoleView(guild, role_ids)
                message = await channel.send(
                    embed=rolepanel_notifications._panel_embed(guild, role_ids),
                    view=view,
                )
                await cog._save_panel(message, creator_id, role_ids)
                bot_obj.add_view(
                    rolepanel_notifications.NotificationRoleView(guild, role_ids),
                    message_id=message.id,
                )
                result = f"{result} + panneau notifications réparé"
        return result

    server_choice_roles.publish_or_refresh = publish_or_refresh_fixed
    server_builder_ready_setup._ensure_role_panels = ensure_role_panels_fixed
    _INSTALLED = True
    logger.info("Correction anti-doublon et affichage Notifications des rolepanels activée.")
