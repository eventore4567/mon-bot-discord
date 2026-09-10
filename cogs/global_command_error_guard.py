"""Garde finale des erreurs d'arguments SentriX.

Cette couche est volontairement installée APRES tous les wrappers runtime. Elle ne change
jamais l'exécution d'une commande : elle possède uniquement le rendu des erreurs de parsing
préfixées et slash afin qu'aucun détail Python interne (ctx/self/interaction/*args/**kwargs)
ne soit présenté comme un argument utilisateur.
"""
from __future__ import annotations

import inspect
import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.command-error-guard")

_INTERNAL_NAMES = {
    "self",
    "cog",
    "_cog",
    "ctx",
    "context",
    "interaction",
    "args",
    "kwargs",
}
_PARAM_LABELS = {
    "member": "membre",
    "membre": "membre",
    "user": "utilisateur",
    "utilisateur": "utilisateur",
    "target": "cible",
    "cible": "cible",
    "role": "rôle",
    "rôle": "rôle",
    "channel": "salon",
    "salon": "salon",
    "reason": "raison",
    "raison": "raison",
    "duration": "durée",
    "duree": "durée",
    "durée": "durée",
    "amount": "montant",
    "montant": "montant",
    "number": "nombre",
    "nombre": "nombre",
    "message": "message",
    "text": "texte",
    "texte": "texte",
    "query": "recherche",
    "name": "nom",
    "action": "action",
}


def _normalise_name(value: object) -> str:
    return str(value or "").strip().casefold().lstrip("*_")


def _is_internal_name(value: object) -> bool:
    return _normalise_name(value) in _INTERNAL_NAMES


def _friendly_name(value: object) -> str:
    raw = str(value or "argument").strip().lstrip("*_") or "argument"
    key = raw.casefold()
    if key in _INTERNAL_NAMES:
        return "argument"
    return _PARAM_LABELS.get(key, raw.replace("_", " "))


def _sanitize_usage_text(raw: object) -> str:
    """Nettoie un usage écrit à la main sans laisser fuiter les paramètres techniques."""
    tokens: list[str] = []
    for token in str(raw or "").split():
        probe = token.strip("<[]>(),=* ").replace("...", "")
        # Gère aussi des formes comme [args...] ou <kwargs>.
        if _is_internal_name(probe):
            continue
        tokens.append(token)
    return " ".join(tokens).strip()


def _prefix_parameter_tokens(command: commands.Command) -> list[str]:
    """Construit l'usage depuis les paramètres que discord.py expose à l'utilisateur.

    ``clean_params`` est préféré à ``callback.__signature__`` : les wrappers runtime ont
    précisément tendance à transformer la signature Python en (ctx, *args, **kwargs).
    """
    params = getattr(command, "clean_params", None)
    if not params:
        return []

    rendered: list[str] = []
    for fallback_name, param in params.items():
        name = str(
            getattr(param, "displayed_name", None)
            or getattr(param, "name", None)
            or fallback_name
        )
        if _is_internal_name(name):
            continue

        kind = getattr(param, "kind", None)
        if kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        label = _friendly_name(name)
        required = getattr(param, "required", None)
        if required is None:
            default = getattr(param, "default", inspect.Parameter.empty)
            required = default is inspect.Parameter.empty
        rendered.append(f"<{label}>" if required else f"[{label}]")
    return rendered


def safe_prefix_usage(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    prefix = str(getattr(ctx, "clean_prefix", None) or "+")
    if command is None:
        return f"{prefix}help"

    base = f"{prefix}{command.qualified_name}"

    # Un usage explicitement défini par le développeur décrit souvent mieux la commande
    # (ex. <add|del> <rôle>). On l'accepte seulement après nettoyage complet.
    explicit = _sanitize_usage_text(getattr(command, "usage", None))
    if explicit:
        return f"{base} {explicit}".strip()

    tokens = _prefix_parameter_tokens(command)
    if tokens:
        return f"{base} {' '.join(tokens)}"

    # Dernier fallback pour de vieilles commandes qui n'exposent pas clean_params.
    legacy = _sanitize_usage_text(getattr(command, "signature", None))
    return f"{base} {legacy}".strip() if legacy else base


def _app_parameter_tokens(command) -> list[str]:
    rendered: list[str] = []
    for param in list(getattr(command, "parameters", None) or []):
        name = str(
            getattr(param, "display_name", None)
            or getattr(param, "name", None)
            or ""
        )
        if not name or _is_internal_name(name):
            continue
        required = bool(getattr(param, "required", False))
        label = _friendly_name(name)
        rendered.append(f"<{label}>" if required else f"[{label}]")
    return rendered


def safe_slash_usage(interaction: discord.Interaction) -> str:
    command = getattr(interaction, "command", None)
    if command is None:
        return "/help"
    name = str(getattr(command, "qualified_name", None) or getattr(command, "name", "commande"))
    tokens = _app_parameter_tokens(command)
    return f"/{name} {' '.join(tokens)}".strip()


def _missing_label(error: BaseException) -> str:
    param = getattr(error, "param", None)
    name = getattr(param, "displayed_name", None) or getattr(param, "name", None)
    return _friendly_name(name)


async def _send_prefix_error(ctx: commands.Context, error: commands.CommandError) -> bool:
    base = getattr(error, "original", error)
    usage = safe_prefix_usage(ctx)

    if isinstance(base, commands.MissingRequiredArgument):
        label = _missing_label(base)
        # Même si un wrapper cassé remonte encore ``ctx`` comme paramètre manquant, le
        # membre ne verra jamais ce nom interne. On donne la syntaxe réellement nettoyée.
        description = f"Il manque **{label}**.\n\nUtilisation : `{usage}`"
        await ctx.send(embed=embeds.warning(description, title="Argument manquant"))
        return True

    if isinstance(base, commands.TooManyArguments):
        await ctx.send(embed=embeds.warning(f"Utilisation : `{usage}`", title="Trop d'arguments"))
        return True

    if isinstance(base, (commands.MemberNotFound, commands.UserNotFound)):
        await ctx.send(embed=embeds.error(
            f"Vérifiez la mention, le nom ou l'ID de l'utilisateur.\n\nUtilisation : `{usage}`",
            title="Utilisateur introuvable",
        ))
        return True

    if isinstance(base, commands.RoleNotFound):
        await ctx.send(embed=embeds.error(
            f"Vérifiez la mention, le nom ou l'ID du rôle.\n\nUtilisation : `{usage}`",
            title="Rôle introuvable",
        ))
        return True

    if isinstance(base, commands.ChannelNotFound):
        await ctx.send(embed=embeds.error(
            f"Vérifiez la mention, le nom ou l'ID du salon.\n\nUtilisation : `{usage}`",
            title="Salon introuvable",
        ))
        return True

    if isinstance(base, commands.MessageNotFound):
        await ctx.send(embed=embeds.error(
            f"Vérifiez l'ID ou le lien du message.\n\nUtilisation : `{usage}`",
            title="Message introuvable",
        ))
        return True

    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError)):
        await ctx.send(embed=embeds.warning(
            f"Une valeur fournie n'est pas valide.\n\nUtilisation : `{usage}`",
            title="Argument invalide",
        ))
        return True

    return False


async def _send_interaction(interaction: discord.Interaction, embed: discord.Embed) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def _send_slash_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> bool:
    original = getattr(error, "original", error)
    usage = safe_slash_usage(interaction)

    # Les commandes hybrides peuvent remonter une erreur commands.* à travers
    # CommandInvokeError. On la traite ici sans jamais afficher sa signature Python.
    if isinstance(original, commands.MissingRequiredArgument):
        label = _missing_label(original)
        await _send_interaction(
            interaction,
            embeds.warning(
                f"Il manque **{label}**.\n\nUtilisation : `{usage}`",
                title="Argument manquant",
            ),
        )
        return True

    if isinstance(original, (commands.BadArgument, commands.BadUnionArgument, commands.ConversionError)):
        await _send_interaction(
            interaction,
            embeds.warning(
                f"Une valeur fournie n'est pas valide.\n\nUtilisation : `{usage}`",
                title="Argument invalide",
            ),
        )
        return True

    if isinstance(error, app_commands.TransformerError):
        await _send_interaction(
            interaction,
            embeds.warning(
                f"Une valeur sélectionnée n'est pas valide.\n\nUtilisation : `{usage}`",
                title="Argument invalide",
            ),
        )
        return True

    if isinstance(error, app_commands.CommandSignatureMismatch):
        # Ici l'erreur signifie que Discord et le code chargé n'ont pas la même version.
        # Inventer un paramètre manquant serait trompeur ; on donne une consigne propre.
        await _send_interaction(
            interaction,
            embeds.warning(
                "La définition de cette commande Discord n'est plus synchronisée avec la version chargée de SentriX. "
                "Réessayez après la prochaine synchronisation des commandes.",
                title="Commande à resynchroniser",
            ),
        )
        return True

    return False


def install(bot: commands.Bot) -> None:
    """Installe le dernier propriétaire du rendu des erreurs d'arguments."""
    if getattr(bot, "_sentrix_global_command_error_guard", False):
        return

    previous_prefix = getattr(bot, "on_command_error", None)
    previous_slash = getattr(bot.tree, "on_error", None)

    if callable(previous_prefix):
        async def final_prefix_error(self, ctx: commands.Context, error: commands.CommandError):
            try:
                if await _send_prefix_error(ctx, error):
                    return
            except Exception:
                logger.exception("Garde finale d'erreur préfixée en échec ; fallback précédent.")
            result = previous_prefix(ctx, error)
            if inspect.isawaitable(result):
                return await result
            return result

        final_prefix_error._sentrix_global_argument_guard = True
        final_prefix_error._sentrix_previous_error_handler = previous_prefix
        bot.on_command_error = MethodType(final_prefix_error, bot)

    if callable(previous_slash):
        async def final_slash_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            try:
                if await _send_slash_error(interaction, error):
                    return
            except Exception:
                logger.exception("Garde finale d'erreur slash en échec ; fallback précédent.")
            result = previous_slash(interaction, error)
            if inspect.isawaitable(result):
                return await result
            return result

        final_slash_error._sentrix_global_argument_guard = True
        final_slash_error._sentrix_previous_error_handler = previous_slash
        bot.tree.on_error = final_slash_error

    bot._sentrix_global_command_error_guard = True
    logger.info(
        "Garde finale erreurs commandes active : ctx/self/interaction/args/kwargs ne sont jamais exposés."
    )


__all__ = ["install", "safe_prefix_usage", "safe_slash_usage"]
