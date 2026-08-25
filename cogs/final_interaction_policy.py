"""Politique finale des réponses Discord SentriX.

Contrat runtime :
- les réponses de commandes préfixées et slash sont toujours des ``discord.Embed`` ;
- les clics, recherches, paginations et modifications gardent l'embed du même message ;
- les anciens wrappers qui transformaient des embeds en texte sont contournés ;
- les fichiers et médias restent envoyables ;
- les grands logs gardent leur protection zéro-ping.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from . import permission_guard
from utils import embeds as sentrix_embeds

logger = logging.getLogger("bot.final-interaction-policy")

_URL_RE = re.compile(r"^https?://\S+$", flags=re.IGNORECASE)
_IMAGE_URL_RE = re.compile(r"^https?://\S+\.(?:png|jpe?g|gif|webp)(?:\?\S*)?$", flags=re.IGNORECASE)


def _unwrap(callable_obj):
    """Retrouve la méthode Discord d'origine derrière les anciens monkey-patches."""
    seen: set[int] = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _disable_known_flatteners() -> None:
    """Neutralise les anciennes fonctions V3.x qui convertissaient un embed en texte."""
    try:
        from . import community_v32
        community_v32.simple_embed_text = lambda *_args, **_kwargs: None
    except Exception:
        pass
    try:
        from . import community_v33
        community_v33._simple_embed_to_text = lambda *_args, **_kwargs: None
    except Exception:
        pass
    try:
        from . import community_v34
        community_v34._embed_to_text = lambda *_args, **_kwargs: None
    except Exception:
        pass


def _clean_embed(embed: discord.Embed | None) -> discord.Embed | None:
    if not isinstance(embed, discord.Embed):
        return embed

    embed.title = sentrix_embeds.clean_ui_text(
        embed.title or "Information",
        90,
        "Information",
    )
    embed.colour = discord.Colour(sentrix_embeds.SENTRIX_COLOR)

    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=sentrix_embeds.clean_ui_text(field.name, 256, "Information"),
            value=str(field.value or "—")[:1024],
            inline=bool(field.inline),
        )

    footer = getattr(embed.footer, "text", None)
    if not footer or str(footer).startswith("SentriX"):
        embed.set_footer(text=str(footer or "SentriX")[:2048])
    return embed


def _style_view(view: discord.ui.View | None) -> discord.ui.View | None:
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
                option.label = sentrix_embeds.clean_ui_text(option.label, 100, "Option")
                if option.description:
                    option.description = sentrix_embeds.clean_ui_text(option.description, 100, "") or None
    return view


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
        "ajouté", "ajoute", "créé", "cree", "terminé", "termine", "activé", "active",
    )):
        return "Action effectuée"
    return "Information"


def _text_embeds(text: str) -> list[discord.Embed]:
    """Transforme même une longue réponse texte en une ou plusieurs vraies cartes."""
    text = str(text or "").strip()
    if not text:
        return [sentrix_embeds.standard("Information", "Aucune information à afficher.")]

    if _IMAGE_URL_RE.match(text):
        panel = sentrix_embeds.standard("Résultat", "Image générée.")
        panel.set_image(url=text)
        return [panel]

    if _URL_RE.match(text):
        return [sentrix_embeds.standard("Lien", f"[Ouvrir le lien]({text})")]

    chunks: list[str] = []
    remaining = text
    while remaining and len(chunks) < 10:
        if len(remaining) <= 3900:
            chunks.append(remaining)
            remaining = ""
            break
        cut = remaining.rfind("\n", 0, 3900)
        if cut < 1000:
            cut = remaining.rfind(" ", 0, 3900)
        if cut < 1000:
            cut = 3900
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining and chunks:
        chunks[-1] = (chunks[-1][:3700] + "\n\nRéponse tronquée : contenu trop long.")[:3900]

    total = len(chunks)
    result: list[discord.Embed] = []
    for index, chunk in enumerate(chunks, start=1):
        title = _content_title(chunk) if total == 1 else f"Réponse {index}/{total}"
        result.append(sentrix_embeds.standard(title, chunk))
    return result


def _extract_content(args: tuple, kwargs: dict[str, Any]):
    if kwargs.get("content") is not None:
        return kwargs.get("content"), False
    if args:
        return args[0], True
    return None, False


def _normalize_payload(
    args: tuple,
    kwargs: dict,
    *,
    editing: bool = False,
    force_embed: bool = True,
):
    new_args = list(args)
    new_kwargs = dict(kwargs)

    if isinstance(new_kwargs.get("embed"), discord.Embed):
        new_kwargs["embed"] = _clean_embed(new_kwargs["embed"])
    if new_kwargs.get("embeds"):
        new_kwargs["embeds"] = [
            _clean_embed(item) if isinstance(item, discord.Embed) else item
            for item in new_kwargs["embeds"]
        ]

    content, positional = _extract_content(tuple(new_args), new_kwargs)
    has_embed = new_kwargs.get("embed") is not None or bool(new_kwargs.get("embeds"))
    has_files = any(new_kwargs.get(key) is not None for key in ("file", "files", "stickers", "poll"))

    if force_embed and content is not None and str(content).strip() and not has_embed and not has_files:
        cards = _text_embeds(str(content))
        if len(cards) == 1:
            new_kwargs["embed"] = cards[0]
        else:
            new_kwargs["embeds"] = cards
        if positional and new_args:
            new_args[0] = None
            new_kwargs.pop("content", None)
        else:
            new_kwargs["content"] = None

    if "view" in new_kwargs:
        new_kwargs["view"] = _style_view(new_kwargs.get("view"))

    if editing and (new_kwargs.get("embed") is not None or new_kwargs.get("embeds")):
        new_kwargs["content"] = None

    return tuple(new_args), new_kwargs


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_final_embed_v2", False):
        return
    base = _unwrap(current)

    async def send_final(self: commands.Context, *args, **kwargs):
        args, kwargs = _normalize_payload(args, kwargs, force_embed=True)
        return await base(self, *args, **kwargs)

    send_final._sentrix_final_embed_v2 = True
    send_final._sentrix_original = base
    commands.Context.send = send_final


def _install_interaction_response() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_final_embed_v2", False):
        base_send = _unwrap(current_send)

        async def response_send(self, *args, **kwargs):
            args, kwargs = _normalize_payload(args, kwargs, force_embed=True)
            return await base_send(self, *args, **kwargs)

        response_send._sentrix_final_embed_v2 = True
        response_send._sentrix_original = base_send
        discord.InteractionResponse.send_message = response_send

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_final_embed_v2", False):
        base_edit = _unwrap(current_edit)

        async def response_edit(self, *args, **kwargs):
            args, kwargs = _normalize_payload(args, kwargs, editing=True, force_embed=True)
            return await base_edit(self, *args, **kwargs)

        response_edit._sentrix_final_embed_v2 = True
        response_edit._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = response_edit


def _install_original_response_edit() -> None:
    current = discord.Interaction.edit_original_response
    if getattr(current, "_sentrix_final_embed_v2", False):
        return
    base = _unwrap(current)

    async def edit_original(self: discord.Interaction, *args, **kwargs):
        args, kwargs = _normalize_payload(args, kwargs, editing=True, force_embed=True)
        return await base(self, *args, **kwargs)

    edit_original._sentrix_final_embed_v2 = True
    edit_original._sentrix_original = base
    discord.Interaction.edit_original_response = edit_original


def _install_followup_send() -> None:
    current = discord.Webhook.send
    if getattr(current, "_sentrix_final_embed_v2", False):
        return
    base = _unwrap(current)

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = _normalize_payload(args, kwargs, force_embed=True)
        return await base(self, *args, **kwargs)

    webhook_send._sentrix_final_embed_v2 = True
    webhook_send._sentrix_original = base
    discord.Webhook.send = webhook_send


def _install_messageable_guard() -> None:
    """Empêche une ancienne couche globale de ré-aplatir les embeds après Context.send."""
    current = discord.abc.Messageable.send
    if getattr(current, "_sentrix_final_embed_v2", False):
        return
    base = _unwrap(current)

    async def messageable_send(self, *args, **kwargs):
        embed = kwargs.get("embed")
        embeds_arg = kwargs.get("embeds") or []
        if isinstance(embed, discord.Embed):
            kwargs["embed"] = _clean_embed(embed)
        if embeds_arg:
            kwargs["embeds"] = [
                _clean_embed(item) if isinstance(item, discord.Embed) else item
                for item in embeds_arg
            ]

        official_log = sentrix_embeds.is_official_log_embed(kwargs.get("embed"))
        if not official_log and kwargs.get("embeds"):
            official_log = any(sentrix_embeds.is_official_log_embed(item) for item in kwargs["embeds"])
        if official_log:
            from utils import log_service
            kwargs["allowed_mentions"] = log_service.LOG_ALLOWED_MENTIONS
            if kwargs.get("view") is None and isinstance(kwargs.get("embed"), discord.Embed):
                try:
                    from utils.helpers import _derive_log_view
                    derived = _derive_log_view(kwargs["embed"])
                    if derived is not None:
                        kwargs["view"] = derived
                except Exception:
                    pass

        return await base(self, *args, **kwargs)

    messageable_send._sentrix_final_embed_v2 = True
    messageable_send._sentrix_original = base
    discord.abc.Messageable.send = messageable_send


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
        return sentrix_embeds.error(str(getattr(original, "message", None) or "Vous n'avez pas accès à cette commande."))
    if name == "BotBlacklistedError":
        reason = str(getattr(original, "reason", None) or "Non précisée")
        return sentrix_embeds.error(f"Vous n'êtes pas autorisé à utiliser SentriX.\nRaison : {reason}")
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return sentrix_embeds.warning(f"Cette commande est en recharge. Réessayez dans {max(1, round(error.retry_after))} s.")
    if isinstance(error, discord.app_commands.MissingPermissions):
        return sentrix_embeds.error("Vous n'avez pas les permissions nécessaires pour cette commande.")
    if isinstance(error, discord.app_commands.BotMissingPermissions):
        return sentrix_embeds.error("SentriX n'a pas les permissions nécessaires pour terminer cette action.")
    if isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
        return sentrix_embeds.error("Une option de cette commande n'est plus valide. Relancez la commande.")
    if isinstance(original, discord.Forbidden):
        return sentrix_embeds.error("Discord a refusé cette action. Vérifiez les permissions et la position du rôle SentriX.")
    if isinstance(error, discord.app_commands.CheckFailure):
        return sentrix_embeds.error("Vous n'avez pas accès à cette commande.")
    return sentrix_embeds.error("Cette commande a rencontré un problème technique. Réessayez dans quelques instants.")


def _install_tree_error(bot: commands.Bot) -> None:
    async def final_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        panel = _slash_error_embed(error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=panel, ephemeral=True)
            else:
                await interaction.response.send_message(embed=panel, ephemeral=True)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
            logger.warning("Impossible d'envoyer l'erreur slash finale.")

    bot.tree.on_error = final_tree_error
    bot._sentrix_final_tree_error = True


def install(bot: commands.Bot) -> None:
    _disable_known_flatteners()
    _install_context_send()
    _install_interaction_response()
    _install_original_response_edit()
    _install_followup_send()
    _install_messageable_guard()
    _install_permission_denial()
    _install_tree_error(bot)

    bot._sentrix_final_interaction_policy = True
    bot._sentrix_official_embed_transport = True
    logger.info("Politique SentriX active : réponses de commandes et pages interactives forcées en embeds.")
