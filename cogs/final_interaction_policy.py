"""Politique finale des interactions SentriX.

Cette couche possède l'unique transport final des réponses de commandes :
- les embeds utilisent le même moteur visuel pour + et / ;
- les réponses slash normales sont publiques par défaut ;
- ``ephemeral=True`` explicite reste privé ;
- erreurs et refus de permission restent privés ;
- éditions après defer et followups passent dans le même moteur.

Les anciens transports V3.2/V3.3/V3.4 ne sont plus réinstallés avant cette politique. De
V3.4, seuls le watchdog slash et le routage IA rapide sont conservés.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from . import community_v32, community_v33, community_v34, permission_guard
from utils import premium_style

logger = logging.getLogger("bot.final-interaction-policy")

RICH_ROOTS = frozenset({
    "help",
    "profile",
    "setup",
    "ticketsetup",
    "logsetup",
    "aisetup",
    "designsetup",
    "embed",
    "shoppanel",
    "rolepanel",
    "verify-panel",
})

_GENERIC_TITLES = frozenset({
    "information",
    "action terminee",
    "action terminée",
    "action impossible",
    "a verifier",
    "à vérifier",
    "verification necessaire",
    "vérification nécessaire",
    "erreur",
    "erreur ia",
    "succes",
    "succès",
    "avertissement",
    "termine",
    "terminé",
})


def _disable_legacy_embed_flattening() -> None:
    """Neutralise les anciennes couches qui transformaient les cartes en texte."""
    def keep_embed(*_args, **_kwargs):
        return None

    community_v32.simple_embed_text = keep_embed
    community_v33._simple_embed_to_text = keep_embed
    community_v34._embed_to_text = keep_embed


def _install_v34_runtime_only(bot: commands.Bot) -> None:
    """Conserve les briques utiles de V3.4 sans ses anciens transports visuels."""
    try:
        community_v34._install_slash_watchdog_policy(bot)
        community_v34._install_fast_ai(bot)
    except Exception:
        logger.exception("Impossible d'installer les briques runtime utiles de V3.4.")


def _clean(value: Any) -> str:
    try:
        return community_v32.strip_decorative_emoji(value or "").strip()
    except Exception:
        return str(value or "").strip()


def _root_from_command(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _root_from_ctx(ctx: commands.Context) -> str:
    return _root_from_command(getattr(ctx, "command", None))


def _root_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is None:
        return ""
    command = getattr(interaction, "command", None)
    if command is not None:
        return _root_from_command(command)
    data = getattr(interaction, "data", None)
    return str(data.get("name") or "").casefold() if isinstance(data, dict) else ""


def _has_media(embed: discord.Embed) -> bool:
    image = getattr(embed, "image", None)
    thumbnail = getattr(embed, "thumbnail", None)
    return bool(
        (image and getattr(image, "url", None))
        or (thumbnail and getattr(thumbnail, "url", None))
    )


def _embed_to_plain(embed: discord.Embed | None, *, root: str = "") -> str | None:
    """Les embeds de commandes ne sont plus convertis en texte simple."""
    del embed, root
    return None


def _merge_content(args: tuple, kwargs: dict, text: str) -> tuple[tuple, dict]:
    mutable = list(args)
    if mutable:
        current = str(mutable[0] or "").strip()
        combined = f"{current}\n{text}".strip() if current else text
        if len(combined) > 1950:
            return args, kwargs
        mutable[0] = combined
        kwargs.pop("content", None)
        return tuple(mutable), kwargs

    current = str(kwargs.get("content") or "").strip()
    combined = f"{current}\n{text}".strip() if current else text
    if len(combined) <= 1950:
        kwargs["content"] = combined
    return tuple(mutable), kwargs


def _convert_kwargs(args: tuple, kwargs: dict, *, root: str, editing: bool = False):
    kwargs = dict(kwargs)
    embed = kwargs.get("embed")
    text = _embed_to_plain(embed, root=root)
    if text:
        kwargs.pop("embed", None)
        if editing:
            kwargs["embeds"] = []
        args, kwargs = _merge_content(args, kwargs, text)
        return args, kwargs

    embeds = kwargs.get("embeds")
    if isinstance(embeds, (list, tuple)) and len(embeds) == 1:
        text = _embed_to_plain(embeds[0], root=root)
        if text:
            kwargs.pop("embeds", None)
            if editing:
                kwargs["embeds"] = []
            args, kwargs = _merge_content(args, kwargs, text)
    return args, kwargs


def _unwrap(callable_obj):
    seen: set[int] = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _style_context_payload(ctx: commands.Context, args: tuple, kwargs: dict):
    return premium_style.style_kwargs(
        args,
        kwargs,
        command=getattr(ctx, "command", None),
        guild=getattr(ctx, "guild", None),
        requester=getattr(ctx, "author", None),
        bot_user=getattr(getattr(ctx, "bot", None), "user", None),
        allow_content_wrap=True,
        include_brand_asset=True,
    )


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_final_plain_v35", False):
        return
    base = _unwrap(current)

    async def send_final(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        args, kwargs = _style_context_payload(self, args, kwargs)
        args, kwargs = _convert_kwargs(args, kwargs, root=root)
        return await base(self, *args, **kwargs)

    send_final._sentrix_final_plain = True
    send_final._sentrix_final_plain_v35 = True
    send_final._sentrix_original = base
    commands.Context.send = send_final


def _install_interaction_response() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_final_public_v35", False):
        base_send = _unwrap(current_send)

        async def response_send(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction)
            args, kwargs = premium_style.style_kwargs(
                args,
                kwargs,
                command=getattr(interaction, "command", None),
                guild=getattr(interaction, "guild", None),
                requester=getattr(interaction, "user", None),
                bot_user=getattr(getattr(interaction, "client", None), "user", None),
                allow_content_wrap=True,
                include_brand_asset=True,
            )
            args, kwargs = _convert_kwargs(args, kwargs, root=root)
            return await base_send(self, *args, **kwargs)

        response_send._sentrix_final_plain = True
        response_send._sentrix_final_public_v35 = True
        response_send._sentrix_original = base_send
        discord.InteractionResponse.send_message = response_send

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_final_public_v35", False):
        base_edit = _unwrap(current_edit)

        async def response_edit(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction)
            args, kwargs = premium_style.style_kwargs(
                args,
                kwargs,
                command=getattr(interaction, "command", None),
                guild=getattr(interaction, "guild", None),
                requester=getattr(interaction, "user", None),
                bot_user=getattr(getattr(interaction, "client", None), "user", None),
                allow_content_wrap=True,
            )
            if kwargs.get("embed") is not None or kwargs.get("embeds"):
                kwargs.setdefault("content", None)
            args, kwargs = _convert_kwargs(args, kwargs, root=root, editing=True)
            return await base_edit(self, *args, **kwargs)

        response_edit._sentrix_final_plain = True
        response_edit._sentrix_final_public_v35 = True
        response_edit._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = response_edit


def _install_original_response_edit() -> None:
    current = discord.Interaction.edit_original_response
    if getattr(current, "_sentrix_final_public_v35", False):
        return
    base = _unwrap(current)

    async def edit_original(self: discord.Interaction, *args, **kwargs):
        root = _root_from_interaction(self)
        args, kwargs = premium_style.style_kwargs(
            args,
            kwargs,
            command=getattr(self, "command", None),
            guild=getattr(self, "guild", None),
            requester=getattr(self, "user", None),
            bot_user=getattr(getattr(self, "client", None), "user", None),
            allow_content_wrap=True,
        )
        if kwargs.get("embed") is not None or kwargs.get("embeds"):
            kwargs.setdefault("content", None)
        args, kwargs = _convert_kwargs(args, kwargs, root=root, editing=True)
        return await base(self, *args, **kwargs)

    edit_original._sentrix_final_plain = True
    edit_original._sentrix_final_public_v35 = True
    edit_original._sentrix_original = base
    discord.Interaction.edit_original_response = edit_original


def _install_followup_send() -> None:
    current = discord.Webhook.send
    if getattr(current, "_sentrix_final_public_v35", False):
        return
    base = _unwrap(current)

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = premium_style.style_kwargs(
                args,
                kwargs,
                allow_content_wrap=True,
                include_brand_asset=True,
            )
            args, kwargs = _convert_kwargs(args, kwargs, root="")
        return await base(self, *args, **kwargs)

    webhook_send._sentrix_final_plain = True
    webhook_send._sentrix_final_public_v35 = True
    webhook_send._sentrix_original = base
    discord.Webhook.send = webhook_send


async def _plain_permission_denial(interaction: discord.Interaction, decision) -> None:
    text = _clean(getattr(decision, "reason", None) or "Tu n'as pas accès à cette commande.")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except (discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer le refus slash final.", exc_info=True)


def _install_permission_denial() -> None:
    permission_guard._send_interaction_denial = _plain_permission_denial


def _slash_error_text(error: BaseException) -> str:
    original = getattr(error, "original", error)
    name = type(original).__name__
    if name == "BotPermissionError":
        return _clean(getattr(original, "message", None) or "Tu n'as pas accès à cette commande.")
    if name == "BotBlacklistedError":
        return f"Tu n'es pas autorisé à utiliser SentriX. Raison : {_clean(getattr(original, 'reason', None) or 'Aucune raison fournie')}"
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return f"Cette commande est en recharge. Réessaie dans {max(1, round(error.retry_after))} s."
    if isinstance(error, discord.app_commands.MissingPermissions):
        return "Tu n'as pas les permissions nécessaires pour cette commande."
    if isinstance(error, discord.app_commands.BotMissingPermissions):
        return "SentriX n'a pas les permissions nécessaires pour terminer cette action."
    if isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
        return "Une option de cette commande n'est plus valide. Relance la commande et sélectionne les options à nouveau."
    if isinstance(original, discord.Forbidden):
        return "Discord a refusé cette action. Vérifie les permissions et la position du rôle SentriX."
    if isinstance(error, discord.app_commands.CheckFailure):
        return "Tu n'as pas accès à cette commande."
    return "Cette commande a rencontré un problème technique. Réessaie dans quelques instants."


def _install_tree_error(bot: commands.Bot) -> None:
    async def final_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        command_name = str(getattr(getattr(interaction, "command", None), "qualified_name", "inconnue"))
        original = getattr(error, "original", error)
        known = isinstance(error, (
            discord.app_commands.CommandOnCooldown,
            discord.app_commands.MissingPermissions,
            discord.app_commands.BotMissingPermissions,
            discord.app_commands.TransformerError,
            discord.app_commands.CommandSignatureMismatch,
            discord.app_commands.CheckFailure,
        )) or type(original).__name__ in {"BotPermissionError", "BotBlacklistedError"}
        if not known:
            logger.error("Erreur slash finale dans /%s : %s", command_name, type(original).__name__, exc_info=original)
        text = _slash_error_text(error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
            logger.warning("Impossible d'envoyer l'erreur slash finale pour /%s.", command_name)

    bot.tree.on_error = final_tree_error
    bot._sentrix_final_tree_error = True


def install(bot: commands.Bot) -> None:
    """Installe directement la politique finale, sans réempiler les transports V3.4."""
    _disable_legacy_embed_flattening()
    _install_v34_runtime_only(bot)

    _install_context_send()
    _install_interaction_response()
    _install_original_response_edit()
    _install_followup_send()
    _install_permission_denial()
    _install_tree_error(bot)

    bot._sentrix_final_interaction_policy = True
    bot._sentrix_slash_public_v35 = True
    logger.info(
        "Politique finale SentriX active : un seul transport +/slash, réponses normales publiques, erreurs privées."
    )
