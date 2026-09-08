"""SentriX V100 — garde-fous runtime pour interactions et panneaux Discord.

Ce correctif est volontairement central :
- une interaction déjà defer/acknowledge n'est plus répondue une seconde fois ;
- un ancien callback ``edit_message(embed=..., view=...)`` reste compatible quand le
  message d'origine est déjà un panneau Components V2 ;
- les paramètres internes ``ctx`` ne sont jamais exposés comme options slash.

Il s'installe avant la construction V98 afin que la signature slash soit saine, puis les
wrappers Discord restent compatibles avec les couches visuelles chargées avant ou après.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

import discord
from discord.ext import commands

import sentrix_grouped_slash_fix as grouped_fix
import sentrix_v95_runtime as v95
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.v100-runtime")

_INSTALLED = False
_COMPONENTS_V2_FLAG = 1 << 15
_INTERNAL_OPTION_NAMES = frozenset({"ctx"})


def _is_components_v2(message: Any) -> bool:
    if message is None:
        return False
    flags = getattr(message, "flags", None)
    if flags is None:
        return False
    if bool(getattr(flags, "components_v2", False)):
        return True
    try:
        return bool(int(getattr(flags, "value", flags)) & _COMPONENTS_V2_FLAG)
    except (TypeError, ValueError):
        return False


def _looks_like_banner_header(embed: discord.Embed) -> bool:
    if not isinstance(embed, discord.Embed):
        return False
    image = str(getattr(getattr(embed, "image", None), "url", None) or "")
    if not image:
        return False
    if not ("banner_source_" in image or "sentrix" in image.casefold()):
        return False
    return not any(
        (
            embed.title,
            embed.description,
            embed.fields,
            getattr(getattr(embed, "author", None), "name", None),
            getattr(getattr(embed, "footer", None), "text", None),
        )
    )


def _embed_from_edit(kwargs: dict[str, Any]) -> discord.Embed | None:
    single = kwargs.get("embed")
    if isinstance(single, discord.Embed):
        return single

    values = [item for item in list(kwargs.get("embeds") or ()) if isinstance(item, discord.Embed)]
    if not values:
        return None
    meaningful = [item for item in values if not _looks_like_banner_header(item)]
    # Les panneaux interactifs SentriX historiques utilisent un seul embed métier. Si une
    # couche a ajouté un header décoratif devant, on prend l'embed métier, jamais le header.
    return meaningful[-1] if meaningful else values[-1]


def _components_v2_edit_payload(message: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Convertit au dernier moment un ancien edit embed vers un vrai panneau V2.

    Discord interdit définitivement ``embed``/``content`` après qu'un message a reçu le
    flag IS_COMPONENTS_V2. On ne tente donc pas de revenir en arrière : on transpose
    l'embed et la View historique dans un LayoutView, ce qui conserve les callbacks.
    """
    if not _is_components_v2(message):
        return kwargs

    embed = _embed_from_edit(kwargs)
    content = kwargs.get("content")
    if embed is None and content is not None and str(content).strip():
        embed = discord.Embed(title="SentriX", description=str(content)[:4000])
    if embed is None:
        # Un edit purement structurel V2 (ex. désactiver une LayoutView) est déjà valide.
        return kwargs

    try:
        panel = panels.depuis_embed(embed)
        source_view = kwargs.get("view")
        if isinstance(source_view, discord.ui.View) and not isinstance(source_view, discord.ui.LayoutView):
            panel = panels.avec_composants(panel, source_view)

        output = dict(kwargs)
        for key in ("content", "embed", "embeds", "file", "files"):
            output.pop(key, None)
        output["view"] = panel

        # Un panneau V2 pointe vers sa bannière attachment:// ; la réattacher à chaque
        # remplacement évite une galerie cassée quand l'intention/couleur change.
        files = panel.fichiers() if hasattr(panel, "fichiers") else []
        if files:
            output["attachments"] = files
        elif "attachments" in output and output["attachments"] is None:
            output.pop("attachments", None)

        logger.debug("V100: edit legacy converti vers Components V2.")
        return output
    except Exception:
        logger.exception("V100: conversion d'un edit legacy vers Components V2 impossible.")
        raise


def _edit_payload_after_ack(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Transforme un send_message tardif en payload edit_original_response compatible."""
    if len(args) > 1:
        return None
    output = dict(kwargs)
    if args:
        output.setdefault("content", args[0])

    # Ces options appartiennent à send_message/followup mais pas à l'édition de la réponse
    # différée. Le caractère éphémère est déjà fixé au moment du defer.
    for key in ("ephemeral", "silent", "tts", "delete_after", "wait", "username", "avatar_url"):
        output.pop(key, None)

    attachments = list(output.pop("attachments", None) or [])
    one = output.pop("file", None)
    many = list(output.pop("files", None) or [])
    if one is not None:
        attachments.append(one)
    attachments.extend(many)
    if attachments:
        output["attachments"] = attachments
    return output


async def _send_after_ack(response: discord.InteractionResponse, args: tuple[Any, ...], kwargs: dict[str, Any]):
    interaction = getattr(response, "_parent", None)
    if interaction is None:
        raise discord.InteractionResponded(response)

    response_type = getattr(response, "type", None)
    deferred_types = {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }
    if response_type in deferred_types:
        payload = _edit_payload_after_ack(args, kwargs)
        if payload is not None:
            try:
                return await interaction.edit_original_response(**payload)
            except (discord.NotFound, TypeError):
                logger.debug("V100: réponse différée non éditable, bascule followup.", exc_info=True)

    followup_kwargs = dict(kwargs)
    # Webhook.send renvoie le message avec wait=True ; plusieurs commandes historiques
    # utilisent le retour (edit/delete/id), donc on conserve ce contrat.
    followup_kwargs.setdefault("wait", True)
    return await interaction.followup.send(*args, **followup_kwargs)


def _install_send_guard() -> None:
    current = discord.InteractionResponse.send_message
    if getattr(current, "_sentrix_v100_ack_guard", False):
        return

    async def guarded_send(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
        if self.is_done():
            logger.warning("V100: double acknowledgement évité ; réponse routée après defer/ack.")
            return await _send_after_ack(self, args, kwargs)
        try:
            return await current(self, *args, **kwargs)
        except discord.InteractionResponded:
            logger.warning("V100: course d'acknowledgement évitée (InteractionResponded).")
            return await _send_after_ack(self, args, kwargs)
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 40060:
                logger.warning("V100: Discord 40060 intercepté ; bascule réponse différée/followup.")
                return await _send_after_ack(self, args, kwargs)
            raise

    guarded_send._sentrix_v100_ack_guard = True
    guarded_send._sentrix_v100_original = current
    discord.InteractionResponse.send_message = guarded_send


def _install_v2_edit_guards() -> None:
    current_response_edit = discord.InteractionResponse.edit_message
    if not getattr(current_response_edit, "_sentrix_v100_v2_guard", False):
        async def guarded_response_edit(self: discord.InteractionResponse, *args: Any, **kwargs: Any):
            interaction = getattr(self, "_parent", None)
            message = getattr(interaction, "message", None)
            kwargs = _components_v2_edit_payload(message, dict(kwargs))
            return await current_response_edit(self, *args, **kwargs)

        guarded_response_edit._sentrix_v100_v2_guard = True
        guarded_response_edit._sentrix_v100_original = current_response_edit
        discord.InteractionResponse.edit_message = guarded_response_edit

    current_original_edit = discord.Interaction.edit_original_response
    if not getattr(current_original_edit, "_sentrix_v100_v2_guard", False):
        async def guarded_original_edit(self: discord.Interaction, *args: Any, **kwargs: Any):
            kwargs = _components_v2_edit_payload(getattr(self, "message", None), dict(kwargs))
            return await current_original_edit(self, *args, **kwargs)

        guarded_original_edit._sentrix_v100_v2_guard = True
        guarded_original_edit._sentrix_v100_original = current_original_edit
        discord.Interaction.edit_original_response = guarded_original_edit

    current_message_edit = discord.Message.edit
    if not getattr(current_message_edit, "_sentrix_v100_v2_guard", False):
        async def guarded_message_edit(self: discord.Message, *args: Any, **kwargs: Any):
            kwargs = _components_v2_edit_payload(self, dict(kwargs))
            return await current_message_edit(self, *args, **kwargs)

        guarded_message_edit._sentrix_v100_v2_guard = True
        guarded_message_edit._sentrix_v100_original = current_message_edit
        discord.Message.edit = guarded_message_edit


def _clean_params(command: commands.Command) -> list[tuple[str, Any]]:
    try:
        values = list(command.clean_params.items())
    except Exception:
        return []
    return [(name, parameter) for name, parameter in values if str(name).casefold() not in _INTERNAL_OPTION_NAMES]


def _install_slash_signature_guard() -> None:
    current_build = v95._build_signature
    if not getattr(current_build, "_sentrix_v100_ctx_guard", False):
        def safe_build_signature(command: commands.Command):
            signature, native, names = current_build(command)
            bad = {name for name in names if str(name).casefold() in _INTERNAL_OPTION_NAMES}
            if not bad:
                return signature, native, names
            params = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.name == "interaction" or parameter.name not in bad
            ]
            clean_names = tuple(name for name in names if name not in bad)
            logger.warning(
                "V100: option slash interne retirée command=%s options=%s",
                command.qualified_name,
                sorted(bad),
            )
            return inspect.Signature(params), native, clean_names

        safe_build_signature._sentrix_v100_ctx_guard = True
        safe_build_signature._sentrix_v100_original = current_build
        v95._build_signature = safe_build_signature

    current_bind = grouped_fix._bind_native_arguments
    if not getattr(current_bind, "_sentrix_v100_ctx_guard", False):
        async def safe_bind(command, ctx, option_names, values):
            params = _clean_params(command)
            if len(params) == len(command.clean_params):
                return await current_bind(command, ctx, option_names, values)
            if len(params) != len(option_names):
                raise commands.BadArgument("La signature slash ne correspond plus à la commande d'origine.")

            args = [ctx] if command.cog is None else [command.cog, ctx]
            call_kwargs: dict[str, Any] = {}
            for (original_name, parameter), exposed_name in zip(params, option_names):
                if exposed_name in values:
                    value = values[exposed_name]
                elif bool(getattr(parameter, "required", False)):
                    raise commands.MissingRequiredArgument(parameter)
                else:
                    value = await grouped_fix._default_for(parameter, ctx)

                kind = parameter.kind
                if kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                    args.append(value)
                elif kind == inspect.Parameter.KEYWORD_ONLY:
                    call_kwargs[original_name] = value
                else:
                    raise commands.BadArgument("Cette forme de paramètres doit utiliser le parseur historique.")
            return args, call_kwargs

        safe_bind._sentrix_v100_ctx_guard = True
        safe_bind._sentrix_v100_original = current_bind
        grouped_fix._bind_native_arguments = safe_bind


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_slash_signature_guard()
    _install_send_guard()
    _install_v2_edit_guards()
    _INSTALLED = True
    logger.info(
        "SentriX V100 installé : ack unique, compatibilité Components V2 et options slash internes filtrées."
    )


__all__ = ["install"]
