"""Final interaction policy for SentriX.

This module is intentionally installed LAST by cogs/__init__.py. It owns the final user-
visible response policy after every historical runtime wrapper has finished installing:
- ordinary command replies are native Discord text instead of embeds when practical;
- real control panels keep their card UI;
- slash errors and permission denials are text, private and deterministic;
- direct interaction replies, edits after defer and application-webhook followups all use
  the same conversion policy;
- the final slash watchdog from V3.4 is re-applied after legacy runtimes.

It does not touch server log embeds: logs are records, not conversational replies.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from . import community_v34, permission_guard

logger = logging.getLogger("bot.final-interaction-policy")

# Only genuine dashboards/panels stay as cards. Everything else is eligible for plain text.
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


def _clean(value: Any) -> str:
    try:
        from . import community_v32
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
    if not isinstance(embed, discord.Embed):
        return None
    if root in RICH_ROOTS or _has_media(embed):
        return None

    title = _clean(embed.title)
    description = _clean(embed.description)
    lines: list[str] = []

    if title and not title.casefold().startswith("sentrix /") and title.casefold() not in _GENERIC_TITLES:
        lines.append(f"**{title}**")
    if description:
        lines.append(description)

    for field in list(embed.fields):
        name = _clean(field.name)
        value = _clean(field.value)
        if not value:
            continue
        if name and name.casefold() not in {"information", "detail", "détail"}:
            lines.append(f"**{name} :** {value}")
        else:
            lines.append(value)

    text = "\n".join(part for part in lines if part).strip()
    # Never silently truncate a rich result. Long cards remain cards because Discord text
    # messages have a 2,000 character limit.
    if not text or len(text) > 1900:
        return None
    return text


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


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_final_plain", False):
        return
    base = _unwrap(current)

    async def send_plain(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        if self.interaction is not None and root and root not in community_v34.SHARED_SLASH_ROOTS:
            kwargs["ephemeral"] = True
        args, kwargs = _convert_kwargs(args, kwargs, root=root)
        return await base(self, *args, **kwargs)

    send_plain._sentrix_final_plain = True
    send_plain._sentrix_original = base
    commands.Context.send = send_plain


def _install_interaction_response() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_final_plain", False):
        base_send = _unwrap(current_send)

        async def response_send(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction)
            args, kwargs = _convert_kwargs(args, kwargs, root=root)
            if root and root not in community_v34.SHARED_SLASH_ROOTS:
                kwargs.setdefault("ephemeral", True)
            return await base_send(self, *args, **kwargs)

        response_send._sentrix_final_plain = True
        response_send._sentrix_original = base_send
        discord.InteractionResponse.send_message = response_send

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_final_plain", False):
        base_edit = _unwrap(current_edit)

        async def response_edit(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction)
            args, kwargs = _convert_kwargs(args, kwargs, root=root, editing=True)
            return await base_edit(self, *args, **kwargs)

        response_edit._sentrix_final_plain = True
        response_edit._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = response_edit


def _install_original_response_edit() -> None:
    current = discord.Interaction.edit_original_response
    if getattr(current, "_sentrix_final_plain", False):
        return
    base = _unwrap(current)

    async def edit_original(self: discord.Interaction, *args, **kwargs):
        root = _root_from_interaction(self)
        args, kwargs = _convert_kwargs(args, kwargs, root=root, editing=True)
        return await base(self, *args, **kwargs)

    edit_original._sentrix_final_plain = True
    edit_original._sentrix_original = base
    discord.Interaction.edit_original_response = edit_original


def _install_followup_send() -> None:
    current = discord.Webhook.send
    if getattr(current, "_sentrix_final_plain", False):
        return
    base = _unwrap(current)

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        # Only interaction followups. Normal server webhooks/log webhooks are untouched.
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = _convert_kwargs(args, kwargs, root="")
        return await base(self, *args, **kwargs)

    webhook_send._sentrix_final_plain = True
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
    """Re-apply the final interaction policy after every legacy runtime installer."""
    # V3.4 owns the fast AI and slash defer cleanup. Re-applying it here makes the final
    # order deterministic even if runtime_quality_v25 is not loaded by a particular boot.
    community_v34.install(bot)

    _install_context_send()
    _install_interaction_response()
    _install_original_response_edit()
    _install_followup_send()
    _install_permission_denial()
    _install_tree_error(bot)

    bot._sentrix_final_interaction_policy = True
    logger.info("Politique finale SentriX active : slash texte natif, réponses privées et aucun vieux runtime après elle.")
