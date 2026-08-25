"""Gestionnaire d'erreurs canonique des commandes SentriX.

Une seule source possède les erreurs utilisateur pour + et /. Les observateurs peuvent
mesurer les erreurs mais ne répondent jamais eux-mêmes. Les erreurs slash restent privées ;
les erreurs préfixées utilisent le même vocabulaire et le même moteur visuel.
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

import discord
from discord.ext import commands

from database.db import PRIMARY_CREATOR_ID
from utils import command_ui_policy
from utils.checks import BotBlacklistedError, BotPermissionError

logger = logging.getLogger("bot.command-error-policy")
_TECHNICAL_PARAMS = {"ctx", "context", "interaction", "self", "cog"}


def _prefix(ctx: commands.Context) -> str:
    return str(getattr(ctx, "clean_prefix", None) or "+")


def _safe_usage(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return f"{_prefix(ctx)}help"
    usage = str(getattr(command, "usage", None) or getattr(command, "signature", None) or "").strip()
    parts = [part for part in usage.split() if part.strip("<[]>*=").casefold() not in _TECHNICAL_PARAMS]
    suffix = " ".join(parts).strip()
    base = f"{_prefix(ctx)}{command.qualified_name}"
    return f"{base} {suffix}".strip()


def _error_embed(text: str, *, command=None, guild=None, requester=None, bot_user=None, kind: str = "danger") -> discord.Embed:
    title = "À vérifier" if kind == "warning" else "Action impossible"
    embed = discord.Embed(title=title, description=text, colour=discord.Colour(0xF0B232 if kind == "warning" else 0xED4245))
    return command_ui_policy.style_embed(
        embed,
        command=command,
        guild=guild,
        requester=requester,
        bot_user=bot_user,
        kind=kind,
    )


def _permission_labels(names) -> str:
    labels = {
        "administrator": "Administrateur",
        "manage_guild": "Gérer le serveur",
        "manage_channels": "Gérer les salons",
        "manage_roles": "Gérer les rôles",
        "manage_messages": "Gérer les messages",
        "manage_nicknames": "Gérer les pseudos",
        "moderate_members": "Exclure temporairement des membres",
        "kick_members": "Expulser des membres",
        "ban_members": "Bannir des membres",
        "move_members": "Déplacer des membres",
        "manage_emojis_and_stickers": "Gérer les expressions",
    }
    return ", ".join(labels.get(name, str(name).replace("_", " ").capitalize()) for name in names)


def _prefix_error_text(bot: commands.Bot, ctx: commands.Context, error: BaseException) -> tuple[str | None, str]:
    base = getattr(error, "original", error)
    if isinstance(base, commands.CommandNotFound):
        typed = str(getattr(ctx, "invoked_with", "") or "").strip()
        try:
            from .command_response_guard import _command_suggestions
            suggestions = _command_suggestions(bot, ctx, typed)
        except Exception:
            suggestions = []
        if suggestions:
            proposed = ", ".join(f"`{_prefix(ctx)}{name}`" for name in suggestions[:2])
            return f"`{_prefix(ctx)}{typed}` n'existe pas. Essaie {proposed}.", "warning"
        return f"`{_prefix(ctx)}{typed}` n'existe pas. Ouvre `{_prefix(ctx)}help` pour rechercher une commande.", "warning"
    if isinstance(base, BotPermissionError):
        return str(base.message), "danger"
    if isinstance(base, BotBlacklistedError):
        return f"Tu n'es pas autorisé à utiliser SentriX. Raison : {base.reason}", "danger"
    if isinstance(base, commands.CommandOnCooldown):
        return f"Cette commande est en recharge. Réessaie dans {max(1, round(base.retry_after))} s.", "warning"
    if isinstance(base, commands.MissingPermissions):
        return f"Permissions requises : **{_permission_labels(base.missing_permissions)}**.", "danger"
    if isinstance(base, commands.BotMissingPermissions):
        return f"SentriX n'a pas les permissions nécessaires : **{_permission_labels(base.missing_permissions)}**.", "danger"
    if isinstance(base, commands.MissingRequiredArgument):
        label = str(getattr(base.param, "displayed_name", None) or getattr(base.param, "name", "argument")).replace("_", " ")
        return f"Il manque **{label}**. Utilise : `{_safe_usage(ctx)}`", "warning"
    if isinstance(base, commands.TooManyArguments):
        return f"Trop d'arguments. Utilise : `{_safe_usage(ctx)}`", "warning"
    if isinstance(base, (commands.MemberNotFound, commands.UserNotFound, commands.RoleNotFound, commands.ChannelNotFound, commands.MessageNotFound)):
        return f"Cible introuvable. Vérifie la mention, le nom ou l'ID.\nUtilise : `{_safe_usage(ctx)}`", "warning"
    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError)):
        return f"Argument invalide. Utilise : `{_safe_usage(ctx)}`", "warning"
    if isinstance(base, discord.Forbidden):
        return "Discord a refusé cette action. Vérifie les permissions et la position du rôle SentriX.", "danger"
    if isinstance(base, commands.CheckFailure):
        return "Tu n'as pas accès à cette commande.", "danger"
    return None, "danger"


def _slash_error_text(error: BaseException) -> tuple[str, str, bool]:
    original = getattr(error, "original", error)
    if isinstance(original, BotPermissionError):
        return str(original.message), "danger", True
    if isinstance(original, BotBlacklistedError):
        return f"Tu n'es pas autorisé à utiliser SentriX. Raison : {original.reason}", "danger", True
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return f"Cette commande est en recharge. Réessaie dans {max(1, round(error.retry_after))} s.", "warning", True
    if isinstance(error, discord.app_commands.MissingPermissions):
        return f"Permissions requises : **{_permission_labels(error.missing_permissions)}**.", "danger", True
    if isinstance(error, discord.app_commands.BotMissingPermissions):
        return f"SentriX n'a pas les permissions nécessaires : **{_permission_labels(error.missing_permissions)}**.", "danger", True
    if isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
        return "Une option n'est plus valide. Relance la commande et sélectionne les options à nouveau.", "warning", True
    if isinstance(original, discord.Forbidden):
        return "Discord a refusé cette action. Vérifie les permissions et la position du rôle SentriX.", "danger", True
    if isinstance(error, discord.app_commands.CheckFailure):
        return "Tu n'as pas accès à cette commande.", "danger", True
    return "Cette commande a rencontré un problème technique. Réessaie dans quelques instants.", "danger", False


async def prefix_error_handler(bot: commands.Bot, ctx: commands.Context, error: commands.CommandError) -> None:
    if getattr(ctx, "_sentrix_error_answered", False):
        return
    text, kind = _prefix_error_text(bot, ctx, error)
    if text is None:
        original = getattr(error, "original", error)
        logger.error(
            "Erreur préfixée non gérée dans +%s : %s\n%s",
            getattr(getattr(ctx, "command", None), "qualified_name", "inconnue"),
            type(original).__name__,
            "".join(traceback.format_exception(type(original), original, original.__traceback__)),
        )
        if getattr(getattr(ctx, "author", None), "id", None) == PRIMARY_CREATOR_ID:
            text = f"Erreur technique : {type(original).__name__}\n{str(original).strip()[:700] or 'aucun détail'}"
        else:
            reference = getattr(getattr(ctx, "message", None), "id", "indisponible")
            text = f"Une erreur technique a interrompu la commande. Référence : `{reference}`."
    ctx._sentrix_error_answered = True
    await ctx.send(embed=_error_embed(
        text,
        command=getattr(ctx, "command", None), guild=getattr(ctx, "guild", None),
        requester=getattr(ctx, "author", None), bot_user=getattr(bot, "user", None), kind=kind,
    ))


async def slash_error_handler(bot: commands.Bot, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
    marker = "_sentrix_error_answered"
    if getattr(interaction, marker, False):
        return
    setattr(interaction, marker, True)
    try:
        from .command_hardening_v41 import release_slash
        release_slash(interaction)
    except Exception:
        pass

    text, kind, known = _slash_error_text(error)
    original = getattr(error, "original", error)
    if not known:
        logger.error(
            "Erreur slash non gérée dans /%s : %s\n%s",
            getattr(getattr(interaction, "command", None), "qualified_name", "inconnue"),
            type(original).__name__,
            "".join(traceback.format_exception(type(original), original, original.__traceback__)),
        )
        if getattr(getattr(interaction, "user", None), "id", None) == PRIMARY_CREATOR_ID:
            text = f"Erreur technique : {type(original).__name__}\n{str(original).strip()[:700] or 'aucun détail'}"

    embed = _error_embed(
        text,
        command=getattr(interaction, "command", None), guild=getattr(interaction, "guild", None),
        requester=getattr(interaction, "user", None), bot_user=getattr(getattr(interaction, "client", None), "user", None), kind=kind,
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        logger.warning("Impossible d'envoyer l'erreur slash interaction=%s.", getattr(interaction, "id", None))


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_command_error_policy", False):
        return

    async def on_prefix_error(ctx: commands.Context, error: commands.CommandError):
        await prefix_error_handler(bot, ctx, error)

    async def on_slash_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        await slash_error_handler(bot, interaction, error)

    on_prefix_error._sentrix_command_error_policy = True
    on_slash_error._sentrix_command_error_policy = True
    bot.on_command_error = on_prefix_error
    bot.tree.on_error = on_slash_error
    bot._sentrix_command_error_policy = True
    bot._sentrix_error_policy_owner = "cogs.command_error_policy"
    logger.info("Gestionnaire d'erreurs canonique actif pour + et /.")


__all__ = ["install", "prefix_error_handler", "slash_error_handler", "_safe_usage"]
