"""V5 — autorité finale des erreurs utilisateur SentriX.

Une commande qui a déjà produit une réponse ne doit pas recevoir une deuxième carte
d'erreur. Les erreurs remplacent donc la réponse existante lorsque c'est possible ; un
follow-up n'est utilisé que lorsqu'aucune réponse originale exploitable n'existe.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord

import config as _config
from discord.ext import commands

from . import final_interaction_policy as policy

logger = logging.getLogger("bot.final-error-embed-v5")

BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# Ces deux couleurs etaient figees en dur et datent d'avant l'unification de la
# palette. Comme ce module rend TOUS les messages d'erreur du bot, chaque refus,
# chaque cooldown et chaque erreur interne sortait encore a l'ancienne teinte
# pendant que le reste du bot affichait la nouvelle. Source unique desormais.
ERROR_COLOR = int(_config.COLOR_ERROR)
WARNING_COLOR = int(_config.COLOR_WARNING)
FOOTER = "SentriX • Réponse rapide et sécurisée"
_ALLOWED = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)


def _clip(value: object, limit: int = 3900) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _panel(title: str, description: str, *, warning: bool = False) -> discord.Embed:
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


def _libelles(permissions) -> str:
    """Noms de permissions en francais.

    discord.py renvoie « ban_members » ; l'afficher tel quel oblige le lecteur a
    traduire lui-meme. access_matrix.permission_label porte deja les libelles utilises
    partout ailleurs dans SentriX : on les reutilise au lieu d'en inventer d'autres.
    """
    from utils.access_matrix import permission_label

    noms = [permission_label(str(p)) for p in (permissions or ())]
    if not noms:
        return "une permission supplémentaire"
    if len(noms) == 1:
        return noms[0]
    return ", ".join(noms[:-1]) + f" et {noms[-1]}"


def _prefix_error_panel(ctx: commands.Context, error: commands.CommandError) -> discord.Embed:
    base = getattr(error, "original", error)
    prefix = _prefix(ctx)

    if isinstance(base, commands.CommandNotFound):
        typed = str(getattr(ctx, "invoked_with", "") or "").strip()
        # Renvoyer l'utilisateur vers +help alors qu'on CONNAIT les commandes proches
        # n'aide personne : taper "+sticky" doit proposer sticky-set / sticky-off.
        # La recherche vit dans command_response_guard ; on la reutilise au lieu d'en
        # ecrire une seconde.
        suggestions: list[str] = []
        try:
            from . import command_response_guard as guard

            suggestions = guard._command_suggestions(getattr(ctx, "bot", None), ctx, typed)
        except Exception:
            logger.debug("Suggestions de commandes indisponibles.", exc_info=True)

        if suggestions:
            lignes = "\n".join(f"• `{prefix}{name}`" for name in suggestions[:3])
            description = (
                f"La commande `{prefix}{typed}` n’existe pas.\n\n"
                f"**Vouliez-vous dire :**\n{lignes}\n\n"
                f"`{prefix}help {suggestions[0]}` donne la syntaxe exacte."
            )
        else:
            description = (
                f"La commande `{prefix}{typed}` n’existe pas.\n\n"
                f"Utilisez `{prefix}help` pour consulter les commandes disponibles."
            )
        return _panel("Commande introuvable", description)
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
        required = _libelles(base.missing_permissions)
        return _panel(
            "Permission insuffisante",
            f"Il vous faut la permission **{required}** pour utiliser cette commande.\n"
            "Un administrateur peut vous l'accorder dans les paramètres du serveur, "
            "ou vous autoriser via `Setup > Permissions`.",
        )
    if isinstance(base, commands.BotMissingPermissions):
        required = _libelles(base.missing_permissions)
        return _panel(
            "SentriX n'a pas les permissions",
            f"SentriX a besoin de **{required}** pour faire cela.\n"
            "Accordez-la au rôle **SentriX** dans "
            "Paramètres du serveur > Rôles, puis réessayez.",
        )
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
            "Discord a refusé l'action",
            "Deux causes possibles :\n"
            "• le rôle **SentriX** est placé **en dessous** du rôle ou du membre visé ;\n"
            "• il lui manque une permission sur ce salon ou sur le serveur.\n\n"
            "Remontez le rôle **SentriX** dans Paramètres du serveur > Rôles, "
            "puis réessayez.",
        )
    return _panel(
        "Erreur de commande",
        "Une erreur technique a interrompu la commande. Elle a été enregistrée "
        "et n'a rien modifié sur le serveur.\n"
        f"Vérifiez les paramètres avec `{_usage(ctx)}` puis réessayez.",
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
        sent = await raw_send(ctx.channel, **kwargs)
    except discord.HTTPException:
        kwargs.pop("reference", None)
        kwargs.pop("mention_author", None)
        sent = await raw_send(ctx.channel, **kwargs)
    ctx._sentrix_response_sent = True
    if sent is not None:
        ctx._sentrix_last_response = sent


async def _replace_prefix_response(ctx: commands.Context, panel: discord.Embed) -> bool:
    """Remplace la dernière réponse d'une commande au lieu d'en créer une deuxième."""
    message = getattr(ctx, "_sentrix_last_response", None)
    if not isinstance(message, discord.Message):
        return False
    raw_edit = policy._unwrap(discord.Message.edit)
    try:
        await raw_edit(message, content=None, embed=panel, attachments=[])
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        logger.debug("Impossible de remplacer la réponse préfixée existante.", exc_info=True)
        return False


async def _raw_slash_send(interaction: discord.Interaction, panel: discord.Embed) -> None:
    response_type = getattr(interaction.response, "type", None)
    deferred = response_type in {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }
    raw_edit = policy._unwrap(discord.Interaction.edit_original_response)

    if interaction.response.is_done() and deferred:
        await raw_edit(interaction, content=None, embed=panel, attachments=[], view=None)
        return

    if not interaction.response.is_done():
        raw_response = policy._unwrap(discord.InteractionResponse.send_message)
        await raw_response(interaction.response, embed=panel, ephemeral=True, allowed_mentions=_ALLOWED)
        return

    # Une réponse normale existe déjà. La remplacer évite le couple « résultat + erreur »
    # qui faisait croire à une double réponse de SentriX.
    try:
        await raw_edit(interaction, content=None, embed=panel, attachments=[])
        return
    except discord.NotFound:
        # Pas de message original : dans ce cas seulement, un follow-up ne duplique rien.
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
            if getattr(ctx, "_sentrix_response_sent", False):
                replaced = await _replace_prefix_response(ctx, panel)
                if not replaced:
                    logger.warning(
                        "Erreur après réponse pour +%s : deuxième message supprimé pour éviter un doublon.",
                        getattr(getattr(ctx, "command", None), "qualified_name", "commande"),
                    )
                return
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
    logger.info("V5 erreurs actif : réponse existante remplacée, aucune carte d'erreur en doublon.")


__all__ = [
    "install",
    "_panel",
    "_prefix_error_panel",
    "_slash_error_panel",
    "_replace_prefix_response",
]
