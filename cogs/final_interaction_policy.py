"""Politique finale et unique des réponses Discord SentriX.

Le runtime possède désormais un seul renderer : ``utils.embeds``.
Cette couche ne crée aucun second design system. Elle garantit seulement que les anciens
handlers encore actifs respectent le contrat final :
- un embed existant conserve ses données mais reçoit le style SentriX officiel ;
- un petit texte libre de commande devient une petite box SentriX ;
- un message contenant une mention volontaire, un fichier, un poll ou une URL brute reste
  du contenu normal afin de ne pas casser les fonctions de notification ;
- les composants perdent leurs emojis décoratifs ;
- les erreurs slash restent éphémères et utilisent une vraie box.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from . import community_v32, community_v33, community_v34, permission_guard
from utils import embeds as sentrix_embeds

logger = logging.getLogger("bot.final-interaction-policy")

_MENTION_RE = re.compile(r"<@!?&?\d+>|@everyone|@here")
_URL_ONLY_RE = re.compile(r"^https?://\S+$", flags=re.IGNORECASE)


def _disable_legacy_embed_flattening() -> None:
    """Neutralise définitivement les couches qui transformaient un embed en texte."""
    def keep_embed(*_args, **_kwargs):
        return None

    community_v32.simple_embed_text = keep_embed
    community_v33._simple_embed_to_text = keep_embed
    community_v34._embed_to_text = keep_embed


def _install_v34_runtime_only(bot: commands.Bot) -> None:
    """Conserve le watchdog slash et le routage IA rapide, jamais son ancien renderer."""
    try:
        community_v34._install_slash_watchdog_policy(bot)
        community_v34._install_fast_ai(bot)
    except Exception:
        logger.exception("Impossible d'installer les briques runtime utiles de V3.4.")


def _unwrap(callable_obj):
    seen: set[int] = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _clean_embed(embed: discord.Embed | None) -> discord.Embed | None:
    """Harmonise une ancienne carte sans altérer ses valeurs métier ou utilisateur."""
    if not isinstance(embed, discord.Embed):
        return embed

    embed.title = sentrix_embeds.clean_ui_text(
        embed.title or "Information",
        90,
        "Information",
    )
    # Une seule couleur officielle pour les surfaces de commandes normales.
    embed.colour = discord.Colour(sentrix_embeds.SENTRIX_COLOR)

    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=sentrix_embeds.clean_ui_text(field.name, 256, "Information"),
            value=str(field.value or "—")[:1024],
            inline=bool(field.inline),
        )

    # Les anciens footers de version/slogan ne doivent plus créer plusieurs identités.
    current_footer = getattr(embed.footer, "text", None)
    if not current_footer or str(current_footer).startswith("SentriX"):
        embed.set_footer(text="SentriX")
    return embed


def _style_view(view: discord.ui.View | None) -> discord.ui.View | None:
    """Retire uniquement la décoration ; ne change jamais le comportement d'un composant."""
    if view is None:
        return None
    for item in getattr(view, "children", []):
        if isinstance(item, discord.ui.Button):
            item.emoji = None
            if item.label:
                item.label = sentrix_embeds.clean_ui_text(item.label, 80, "Action")
        elif isinstance(item, discord.ui.Select):
            if item.placeholder:
                item.placeholder = sentrix_embeds.clean_ui_text(
                    item.placeholder,
                    150,
                    "Sélectionnez une option",
                )
            for option in list(getattr(item, "options", []) or []):
                option.emoji = None
                option.label = sentrix_embeds.clean_ui_text(
                    option.label,
                    100,
                    "Option",
                )
                if option.description:
                    option.description = sentrix_embeds.clean_ui_text(
                        option.description,
                        100,
                        "",
                    ) or None
    return view


def _can_wrap_content(content: Any, kwargs: dict[str, Any]) -> bool:
    if content is None:
        return False
    text = str(content).strip()
    if not text or len(text) > 3900:
        return False
    if kwargs.get("embed") is not None or kwargs.get("embeds"):
        return False
    if any(key in kwargs for key in ("file", "files", "stickers", "poll")):
        return False
    # Une mention dans le contenu peut être volontaire (notifications, tickets, annonces).
    # On ne la déplace jamais dans un embed, sinon Discord ne notifierait plus.
    if _MENTION_RE.search(text):
        return False
    if _URL_ONLY_RE.match(text):
        return False
    return True


def _content_title(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in (
        "erreur", "introuvable", "impossible", "refusé", "refuse", "interdit",
        "permission", "échoué", "echoue", "indisponible",
    )):
        return "Erreur"
    if any(word in lowered for word in (
        "attention", "attendre", "déjà", "deja", "recharge", "cooldown",
    )):
        return "Vérification nécessaire"
    if any(word in lowered for word in (
        "réussi", "reussi", "effectué", "effectue", "enregistré", "enregistre",
        "ajouté", "ajoute", "créé", "cree", "terminé", "termine",
    )):
        return "Action effectuée"
    return "Information"


def _normalize_payload(args: tuple, kwargs: dict, *, editing: bool = False):
    new_args = list(args)
    new_kwargs = dict(kwargs)

    if isinstance(new_kwargs.get("embed"), discord.Embed):
        new_kwargs["embed"] = _clean_embed(new_kwargs["embed"])
    if new_kwargs.get("embeds"):
        new_kwargs["embeds"] = [
            _clean_embed(item) if isinstance(item, discord.Embed) else item
            for item in new_kwargs["embeds"]
        ]

    content = new_kwargs.get("content")
    if content is None and new_args:
        content = new_args[0]

    if _can_wrap_content(content, new_kwargs):
        text = str(content).strip()
        new_kwargs["embed"] = sentrix_embeds.standard(_content_title(text), text)
        if new_args:
            new_args[0] = None
            new_kwargs.pop("content", None)
        else:
            new_kwargs["content"] = None
        if editing:
            new_kwargs.pop("embeds", None)

    if "view" in new_kwargs:
        new_kwargs["view"] = _style_view(new_kwargs.get("view"))

    if editing and (new_kwargs.get("embed") is not None or new_kwargs.get("embeds")):
        # Évite de conserver un ancien texte public au-dessus d'une carte après edit.
        new_kwargs.setdefault("content", None)

    return tuple(new_args), new_kwargs


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_official_embed_transport", False):
        return
    base = _unwrap(current)

    async def send_final(self: commands.Context, *args, **kwargs):
        args, kwargs = _normalize_payload(args, kwargs)
        return await base(self, *args, **kwargs)

    send_final._sentrix_official_embed_transport = True
    send_final._sentrix_original = base
    commands.Context.send = send_final


def _install_interaction_response() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_official_embed_transport", False):
        base_send = _unwrap(current_send)

        async def response_send(self, *args, **kwargs):
            args, kwargs = _normalize_payload(args, kwargs)
            return await base_send(self, *args, **kwargs)

        response_send._sentrix_official_embed_transport = True
        response_send._sentrix_original = base_send
        discord.InteractionResponse.send_message = response_send

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_official_embed_transport", False):
        base_edit = _unwrap(current_edit)

        async def response_edit(self, *args, **kwargs):
            args, kwargs = _normalize_payload(args, kwargs, editing=True)
            return await base_edit(self, *args, **kwargs)

        response_edit._sentrix_official_embed_transport = True
        response_edit._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = response_edit


def _install_original_response_edit() -> None:
    current = discord.Interaction.edit_original_response
    if getattr(current, "_sentrix_official_embed_transport", False):
        return
    base = _unwrap(current)

    async def edit_original(self: discord.Interaction, *args, **kwargs):
        args, kwargs = _normalize_payload(args, kwargs, editing=True)
        return await base(self, *args, **kwargs)

    edit_original._sentrix_official_embed_transport = True
    edit_original._sentrix_original = base
    discord.Interaction.edit_original_response = edit_original


def _install_followup_send() -> None:
    current = discord.Webhook.send
    if getattr(current, "_sentrix_official_embed_transport", False):
        return
    base = _unwrap(current)

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = _normalize_payload(args, kwargs)
        return await base(self, *args, **kwargs)

    webhook_send._sentrix_official_embed_transport = True
    webhook_send._sentrix_original = base
    discord.Webhook.send = webhook_send


async def _permission_denial(interaction: discord.Interaction, decision) -> None:
    text = str(getattr(decision, "reason", None) or "Vous n'avez pas accès à cette commande.").strip()
    panel = sentrix_embeds.error(text)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=panel, ephemeral=True)
        else:
            await interaction.response.send_message(embed=panel, ephemeral=True)
    except (discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer le refus slash final.", exc_info=True)


def _install_permission_denial() -> None:
    permission_guard._send_interaction_denial = _permission_denial


def _slash_error_embed(error: BaseException) -> discord.Embed:
    original = getattr(error, "original", error)
    name = type(original).__name__
    if name == "BotPermissionError":
        return sentrix_embeds.error(
            str(getattr(original, "message", None) or "Vous n'avez pas accès à cette commande.")
        )
    if name == "BotBlacklistedError":
        reason = str(getattr(original, "reason", None) or "Non précisée")
        return sentrix_embeds.error(f"Vous n'êtes pas autorisé à utiliser SentriX.\nRaison : {reason}")
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return sentrix_embeds.warning(
            f"Cette commande est en recharge. Réessayez dans {max(1, round(error.retry_after))} s."
        )
    if isinstance(error, discord.app_commands.MissingPermissions):
        return sentrix_embeds.error("Vous n'avez pas les permissions nécessaires pour cette commande.")
    if isinstance(error, discord.app_commands.BotMissingPermissions):
        return sentrix_embeds.error("SentriX n'a pas les permissions nécessaires pour terminer cette action.")
    if isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
        return sentrix_embeds.error(
            "Une option de cette commande n'est plus valide. Relancez la commande puis sélectionnez à nouveau les options."
        )
    if isinstance(original, discord.Forbidden):
        return sentrix_embeds.error(
            "Discord a refusé cette action. Vérifiez les permissions et la position du rôle SentriX."
        )
    if isinstance(error, discord.app_commands.CheckFailure):
        return sentrix_embeds.error("Vous n'avez pas accès à cette commande.")
    return sentrix_embeds.error(
        "Cette commande a rencontré un problème technique. Réessayez dans quelques instants."
    )


def _install_tree_error(bot: commands.Bot) -> None:
    async def final_tree_error(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        command_name = str(
            getattr(getattr(interaction, "command", None), "qualified_name", "inconnue")
        )
        original = getattr(error, "original", error)
        known = isinstance(
            error,
            (
                discord.app_commands.CommandOnCooldown,
                discord.app_commands.MissingPermissions,
                discord.app_commands.BotMissingPermissions,
                discord.app_commands.TransformerError,
                discord.app_commands.CommandSignatureMismatch,
                discord.app_commands.CheckFailure,
            ),
        ) or type(original).__name__ in {"BotPermissionError", "BotBlacklistedError"}
        if not known:
            logger.error(
                "Erreur slash finale dans /%s : %s",
                command_name,
                type(original).__name__,
                exc_info=original,
            )
        panel = _slash_error_embed(error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=panel, ephemeral=True)
            else:
                await interaction.response.send_message(embed=panel, ephemeral=True)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
            logger.warning("Impossible d'envoyer l'erreur slash finale pour /%s.", command_name)

    bot.tree.on_error = final_tree_error
    bot._sentrix_final_tree_error = True


def install(bot: commands.Bot) -> None:
    _disable_legacy_embed_flattening()
    _install_v34_runtime_only(bot)
    _install_context_send()
    _install_interaction_response()
    _install_original_response_edit()
    _install_followup_send()
    _install_permission_denial()
    _install_tree_error(bot)

    bot._sentrix_final_interaction_policy = True
    bot._sentrix_official_embed_transport = True
    logger.info(
        "Politique finale SentriX active : utils.embeds est l'unique renderer des réponses +/slash."
    )
