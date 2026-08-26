"""V5 — autorité finale des erreurs utilisateur SentriX.

Les erreurs ne passent plus par les monkey-patches visuels successifs. On construit un vrai
``discord.Embed`` et on appelle le transport discord.py d'origine. Cela garantit le bloc
embed Discord (barre colorée + carte) même si une ancienne couche de rendu est encore
chargée ailleurs dans le runtime.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord.ext import commands

from . import final_interaction_policy as policy

logger = logging.getLogger("bot.final-error-embed-v5")

BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ERROR_COLOR = 0xED4245
WARNING_COLOR = 0xF0B232
FOOTER = "SentriX • Réponse rapide et sécurisée"
_ALLOWED = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)


def _clip(value: object, limit: int = 3900) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _panel(title: str, description: str, *, warning: bool = False) -> discord.Embed:
    # Ne PAS utiliser utils.embeds ici : le but de cette couche est précisément de sortir
    # du pipeline de renderers et d'envoyer une carte Discord native, sans transformation.
    embed = discord.Embed(
        title=_clip(title, 256) or "Erreur de commande",
        description=f"{BAR}\n{_clip(description)}",
        colour=discord.Colour(WARNING_COLOR if warning else ERROR_COLOR),
    )
    embed.set_footer(text=FOOTER)
    return embed


def _prefix(ctx: commands.Context) -> str:
    return str(getattr(ctx, "clean_prefix", None) or "+")


def _usage(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return f"{_prefix(ctx)}help"
    signature = str(getattr(command, "signature", "") or "").strip()
    base = f"{_prefix(ctx)}{command.qualified_name}"
    return f"{base} {signature}".strip()


def _prefix_error_panel(ctx: commands.Context, error: commands.CommandError) -> discord.Embed:
    base = getattr(error, "original", error)
    prefix = _prefix(ctx)

    if isinstance(base, commands.CommandNotFound):
        typed = str(getattr(ctx, "invoked_with", "") or "").strip()
        return _panel(
            "Commande introuvable",
            f"La commande `{prefix}{typed}` n’existe pas.\n\nUtilisez `{prefix}help` pour consulter les commandes disponibles.",
        )
    if isinstance(base, commands.MissingRequiredArgument):
        name = str(getattr(getattr(base, "param", None), "name", "argument") or "argument")
        return _panel(
            "Argument manquant",
            f"L’argument **{name}** est obligatoire.\n\nUtilisation : `{_usage(ctx)}`",
            warning=True,
        )
    if isinstance(base, commands.TooManyArguments):
        return _panel("Trop d’arguments", f"Utilisation : `{_usage(ctx)}`", warning=True)
    if isinstance(base, (commands.MemberNotFound, commands.UserNotFound)):
        return _panel("Utilisateur introuvable", "Vérifiez la mention, le nom ou l’ID.")
    if isinstance(base, commands.RoleNotFound):
        return _panel("Rôle introuvable", "Vérifiez la mention, le nom ou l’ID du rôle.")
    if isinstance(base, commands.ChannelNotFound):
        return _panel("Salon introuvable", "Vérifiez la mention, le nom ou l’ID du salon.")
    if isinstance(base, commands.MessageNotFound):
        return _panel("Message introuvable", "Vérifiez l’ID ou le lien du message.")
    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError)):
        return _panel("Argument invalide", f"Utilisation : `{_usage(ctx)}`", warning=True)
    if isinstance(base, commands.CommandOnCooldown):
        return _panel(
            "Commande en cooldown",
            f"Réessayez dans **{max(0.1, float(base.retry_after)):.1f} s**.",
            warning=True,
        )
    if isinstance(base, commands.MissingPermissions):
        required = ", ".join(str(p).replace("_", " ") for p in base.missing_permissions)
        return _panel("Permission insuffisante", f"Permission requise : **{required}**.")
    if isinstance(base, commands.BotMissingPermissions):
        required = ", ".join(str(p).replace("_", " ") for p in base.missing_permissions)
        return _panel("Permission du bot insuffisante", f"SentriX a besoin de : **{required}**.")
    if isinstance(base, commands.NoPrivateMessage):
        return _panel("Serveur requis", "Cette commande doit être utilisée dans un serveur.", warning=True)
    if isinstance(base, commands.PrivateMessageOnly):
        return _panel("Message privé requis", "Cette commande doit être utilisée en message privé.", warning=True)

    cls = type(base).__name__
    if cls == "BotBlacklistedError":
        reason = str(getattr(base, "reason", "Aucune raison fournie") or "Aucune raison fournie")
        return _panel("Accès refusé", f"Vous n’êtes pas autorisé à utiliser SentriX.\nRaison : {reason}")
    if cls == "BotPermissionError" or isinstance(base, commands.CheckFailure):
        message = str(getattr(base, "message", "") or "Vous n’êtes pas autorisé à utiliser cette commande.")
        return _panel("Accès refusé", message)

    if isinstance(base, discord.Forbidden):
        return _panel(
            "Permission du bot insuffisante",
            "Discord a refusé cette action. Vérifiez les permissions et la position du rôle SentriX.",
        )
    return _panel(
        "Erreur de commande",
        "Une erreur technique inattendue a interrompu la commande. Réessayez après avoir vérifié les paramètres.",
    )


def _slash_error_panel(error: discord.app_commands.AppCommandError) -> discord.Embed:
    original = getattr(error, "original", error)
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return _panel(
            "Commande en cooldown",
            f"Réessayez dans **{max(0.1, float(error.retry_after)):.1f} s**.",
            warning=True,
        )
    if isinstance(error, discord.app_commands.MissingPermissions):
        required = ", ".join(str(p).replace("_", " ") for p in error.missing_permissions)
        return _panel("Permission insuffisante", f"Permission requise : **{required}**.")
    if isinstance(error, discord.app_commands.BotMissingPermissions):
        required = ", ".join(str(p).replace("_", " ") for p in error.missing_permissions)
        return _panel("Permission du bot insuffisante", f"SentriX a besoin de : **{required}**.")
    if isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
        return _panel("Argument invalide", "Une valeur fournie n’est pas valide pour cette commande.", warning=True)

    cls = type(original).__name__
    if cls == "BotBlacklistedError":
        reason = str(getattr(original, "reason", "Aucune raison fournie") or "Aucune raison fournie")
        return _panel("Accès refusé", f"Vous n’êtes pas autorisé à utiliser SentriX.\nRaison : {reason}")
    if cls == "BotPermissionError" or isinstance(error, discord.app_commands.CheckFailure):
        message = str(getattr(original, "message", "") or "Vous n’êtes pas autorisé à utiliser cette commande.")
        return _panel("Accès refusé", message)
    if isinstance(original, discord.Forbidden):
        return _panel(
            "Permission du bot insuffisante",
            "Discord a refusé cette action. Vérifiez les permissions et la position du rôle SentriX.",
        )
    return _panel(
        "Erreur de commande",
        "Une erreur technique inattendue a interrompu la commande. Réessayez après avoir vérifié les paramètres.",
    )


async def _raw_prefix_send(ctx: commands.Context, panel: discord.Embed) -> None:
    raw_send = policy._unwrap(discord.abc.Messageable.send)
    kwargs = {"embed": panel, "allowed_mentions": _ALLOWED}
    message = getattr(ctx, "message", None)
    if message is not None:
        kwargs["reference"] = discord.MessageReference(
            message_id=message.id,
            channel_id=ctx.channel.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            fail_if_not_exists=False,
        )
        kwargs["mention_author"] = False
    try:
        await raw_send(ctx.channel, **kwargs)
    except discord.HTTPException:
        kwargs.pop("reference", None)
        kwargs.pop("mention_author", None)
        await raw_send(ctx.channel, **kwargs)


async def _raw_slash_send(interaction: discord.Interaction, panel: discord.Embed) -> None:
    # Un slash différé possède déjà un message original vide : le remplir en embed natif.
    response_type = getattr(interaction.response, "type", None)
    deferred = response_type in {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }
    if interaction.response.is_done() and deferred:
        raw_edit = policy._unwrap(discord.Interaction.edit_original_response)
        await raw_edit(interaction, content=None, embed=panel, attachments=[], view=None)
        return

    if not interaction.response.is_done():
        raw_response = policy._unwrap(discord.InteractionResponse.send_message)
        await raw_response(interaction.response, embed=panel, ephemeral=True, allowed_mentions=_ALLOWED)
        return

    raw_webhook = policy._unwrap(discord.Webhook.send)
    await raw_webhook(
        interaction.followup,
        embed=panel,
        ephemeral=True,
        allowed_mentions=_ALLOWED,
        wait=True,
    )


def install(bot: commands.Bot) -> None:
    async def prefix_error(self: commands.Bot, ctx: commands.Context, error: commands.CommandError):
        panel = _prefix_error_panel(ctx, error)
        try:
            await _raw_prefix_send(ctx, panel)
        except Exception:
            logger.exception("V5 : impossible d’envoyer l’erreur préfixée en embed natif.")

    prefix_error._sentrix_final_error_embed_v5 = True
    bot.on_command_error = MethodType(prefix_error, bot)

    async def slash_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        panel = _slash_error_panel(error)
        try:
            await _raw_slash_send(interaction, panel)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException):
            logger.exception("V5 : impossible d’envoyer l’erreur slash en embed natif.")

    slash_error._sentrix_final_error_embed_v5 = True
    bot.tree.on_error = slash_error
    logger.info("V5 erreurs actif : transport Discord brut, embed natif obligatoire.")


__all__ = ["install", "_panel", "_prefix_error_panel", "_slash_error_panel"]
