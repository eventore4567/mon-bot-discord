"""Chemin canonique unique pour les réponses Discord de SentriX.

Ce module est chargé en dernier sur Railway. Il remplace l'empilement historique de
wrappers d'interactions par une politique simple :
- texte Discord natif pour les réponses ordinaires ;
- cartes uniquement pour les vrais panneaux ;
- réponses slash personnelles privées par défaut ;
- premier ctx.send() après defer remplit la réponse originale ;
- erreurs slash et refus de permissions en texte ;
- aucun watchdog slash supplémentaire.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from . import permission_guard

logger = logging.getLogger("bot.canonical-interactions")

# Vrais panneaux qui gagnent à rester en embed. Les réponses conversationnelles,
# confirmations, erreurs, IA, économie, modération simple, etc. deviennent du texte.
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

# Commandes dont la réponse slash est naturellement destinée au salon.
PUBLIC_SLASH_ROOTS = frozenset({
    "poll", "say", "announce", "suggest",
    "giveaway-create", "giveaway-list", "event-create", "event-join", "event-leave",
    "event-list", "tournament-create", "tournament-start", "tournament-join",
    "tournament-list", "rolepanel", "verify-panel",
    "play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "volume",
    "loop", "shuffle", "remove-from-queue", "clear-queue",
    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",
    "blackjack", "slots", "coinflip", "dice", "luckyroll", "highlow", "memory",
    "reaction", "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype",
    "duel", "connect4", "numberduel", "reactionduel", "quizduel", "triviastart",
    "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage", "emoji-race",
})

RICH_TITLE_HINTS = (
    "configuration", "setup", "profil", "profile", "aide", "help",
    "ticket panel", "panel", "journal", "logs", "classement",
)


def _clean(value: Any) -> str:
    try:
        from .community_v32 import strip_decorative_emoji
        return strip_decorative_emoji(value or "").strip()
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


def _private_slash(root: str) -> bool:
    return bool(root and root not in PUBLIC_SLASH_ROOTS)


def _is_rich_embed(embed: discord.Embed, root: str) -> bool:
    if root in RICH_ROOTS:
        return True
    title = _clean(embed.title).casefold()
    # Pour les Message.edit sans contexte de commande, on conserve uniquement les vrais
    # panneaux identifiables par leur titre. Une simple miniature n'impose plus un carré.
    if not root and title and any(hint in title for hint in RICH_TITLE_HINTS):
        return True
    return False


def _embed_to_text(embed: discord.Embed | None, *, root: str = "") -> str | None:
    if not isinstance(embed, discord.Embed) or _is_rich_embed(embed, root):
        return None

    title = _clean(embed.title)
    description = _clean(embed.description)
    generic_titles = {
        "information", "erreur", "erreur ia", "succès", "succes", "avertissement",
        "action terminée", "action terminee", "action impossible",
    }
    lines: list[str] = []
    if title and not title.casefold().startswith("sentrix /") and title.casefold() not in generic_titles:
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

    text = "\n".join(lines).strip()
    return text if text and len(text) <= 1950 else None


def _convert(args: tuple, kwargs: dict, *, root: str = "", editing: bool = False):
    kwargs = dict(kwargs)
    embed = kwargs.get("embed")
    text = _embed_to_text(embed, root=root)
    if text:
        kwargs.pop("embed", None)
        if editing:
            kwargs["embeds"] = []
        if args:
            mutable = list(args)
            current = str(mutable[0] or "").strip()
            mutable[0] = f"{current}\n{text}".strip() if current else text
            args = tuple(mutable)
            kwargs.pop("content", None)
        else:
            current = str(kwargs.get("content") or "").strip()
            kwargs["content"] = f"{current}\n{text}".strip() if current else text
        return args, kwargs

    embeds = kwargs.get("embeds")
    if isinstance(embeds, (list, tuple)) and len(embeds) == 1:
        text = _embed_to_text(embeds[0], root=root)
        if text:
            kwargs.pop("embeds", None)
            if editing:
                kwargs["embeds"] = []
            if args:
                mutable = list(args)
                current = str(mutable[0] or "").strip()
                mutable[0] = f"{current}\n{text}".strip() if current else text
                args = tuple(mutable)
                kwargs.pop("content", None)
            else:
                current = str(kwargs.get("content") or "").strip()
                kwargs["content"] = f"{current}\n{text}".strip() if current else text
    return args, kwargs


def _unwrap(func):
    seen: set[int] = set()
    current = func
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _filled_set(bot: commands.Bot) -> set[int]:
    value = getattr(bot, "_sentrix_canonical_filled_interactions", None)
    if not isinstance(value, set):
        value = set()
        bot._sentrix_canonical_filled_interactions = value
    return value


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_canonical", False):
        return
    base = _unwrap(current)

    async def canonical_send(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        args, kwargs = _convert(args, kwargs, root=root)
        interaction = getattr(self, "interaction", None)
        if interaction is not None:
            if _private_slash(root):
                kwargs["ephemeral"] = True

            response_type = getattr(interaction.response, "type", None)
            deferred = response_type in {
                discord.InteractionResponseType.deferred_channel_message,
                discord.InteractionResponseType.deferred_message_update,
            }
            bot = getattr(self, "bot", None)
            filled = _filled_set(bot) if isinstance(bot, commands.Bot) else set()
            if deferred and int(interaction.id) not in filled:
                # Un seul chemin après defer : on remplit la réponse originale au lieu de
                # créer un follow-up et de laisser « thinking » bloqué.
                edit_kwargs = dict(kwargs)
                edit_kwargs.pop("ephemeral", None)
                edit_kwargs.pop("wait", None)
                if args:
                    edit_kwargs["content"] = str(args[0])
                message = await interaction.edit_original_response(**edit_kwargs)
                filled.add(int(interaction.id))
                return message
        return await base(self, *args, **kwargs)

    canonical_send._sentrix_canonical = True
    canonical_send._sentrix_original = base
    commands.Context.send = canonical_send


def _install_context_defer() -> None:
    current = getattr(commands.Context, "defer", None)
    if current is None or getattr(current, "_sentrix_canonical", False):
        return
    base = _unwrap(current)

    async def canonical_defer(self: commands.Context, *args, **kwargs):
        if self.interaction is not None and _private_slash(_root_from_ctx(self)):
            kwargs.setdefault("ephemeral", True)
        return await base(self, *args, **kwargs)

    canonical_defer._sentrix_canonical = True
    canonical_defer._sentrix_original = base
    commands.Context.defer = canonical_defer


def _install_interaction_methods() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_canonical", False):
        base_send = _unwrap(current_send)

        async def send_message(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction)
            args, kwargs = _convert(args, kwargs, root=root)
            if _private_slash(root):
                kwargs.setdefault("ephemeral", True)
            return await base_send(self, *args, **kwargs)

        send_message._sentrix_canonical = True
        send_message._sentrix_original = base_send
        discord.InteractionResponse.send_message = send_message

    current_edit = discord.Interaction.edit_original_response
    if not getattr(current_edit, "_sentrix_canonical", False):
        base_edit = _unwrap(current_edit)

        async def edit_original(self: discord.Interaction, *args, **kwargs):
            root = _root_from_interaction(self)
            args, kwargs = _convert(args, kwargs, root=root, editing=True)
            result = await base_edit(self, *args, **kwargs)
            client = getattr(self, "client", None)
            if isinstance(client, commands.Bot):
                _filled_set(client).add(int(self.id))
            return result

        edit_original._sentrix_canonical = True
        edit_original._sentrix_original = base_edit
        discord.Interaction.edit_original_response = edit_original

    current_component_edit = discord.InteractionResponse.edit_message
    if not getattr(current_component_edit, "_sentrix_canonical", False):
        base_component_edit = _unwrap(current_component_edit)

        async def edit_message(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            args, kwargs = _convert(args, kwargs, root=_root_from_interaction(interaction), editing=True)
            return await base_component_edit(self, *args, **kwargs)

        edit_message._sentrix_canonical = True
        edit_message._sentrix_original = base_component_edit
        discord.InteractionResponse.edit_message = edit_message


def _install_message_edit() -> None:
    current = discord.Message.edit
    if getattr(current, "_sentrix_canonical", False):
        return
    base = _unwrap(current)

    async def message_edit(self: discord.Message, *args, **kwargs):
        # Couvre notamment +ai : son message « SentriX réfléchit… » est ensuite édité.
        args, kwargs = _convert(args, kwargs, root="", editing=True)
        return await base(self, *args, **kwargs)

    message_edit._sentrix_canonical = True
    message_edit._sentrix_original = base
    discord.Message.edit = message_edit


def _install_followups() -> None:
    current = discord.Webhook.send
    if getattr(current, "_sentrix_canonical", False):
        return
    base = _unwrap(current)

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        if getattr(self, "type", None) == discord.WebhookType.application:
            args, kwargs = _convert(args, kwargs, root="")
        return await base(self, *args, **kwargs)

    webhook_send._sentrix_canonical = True
    webhook_send._sentrix_original = base
    discord.Webhook.send = webhook_send


async def _plain_denial(interaction: discord.Interaction, decision) -> None:
    text = _clean(getattr(decision, "reason", None) or "Tu n'as pas accès à cette commande.")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except (discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        pass


def _install_plain_errors(bot: commands.Bot) -> None:
    permission_guard._send_interaction_denial = _plain_denial

    async def on_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        original = getattr(error, "original", error)
        if type(original).__name__ == "BotPermissionError":
            text = _clean(getattr(original, "message", None) or "Tu n'as pas accès à cette commande.")
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            text = f"Cette commande est en recharge. Réessaie dans {max(1, round(error.retry_after))} s."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            text = "Tu n'as pas les permissions nécessaires pour cette commande."
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            text = "SentriX n'a pas les permissions nécessaires pour terminer cette action."
        elif isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
            text = "Une option de cette commande n'est plus valide. Relance la commande et sélectionne-la à nouveau."
        elif isinstance(error, discord.app_commands.CheckFailure):
            text = "Tu n'as pas accès à cette commande."
        else:
            logger.error("Erreur slash canonique : %s", type(original).__name__, exc_info=original)
            text = "Cette commande a rencontré un problème technique. Réessaie dans quelques instants."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
            pass

    bot.tree.on_error = on_error


def _remove_old_slash_listeners(bot: commands.Bot) -> int:
    """Neutralise le dernier watchdog V7 installé par l'ancien bootstrap des cogs."""
    removed = 0
    blocked_modules = {
        "cogs.slash_reliability_v7",
        "cogs.deferred_context_response_guard",
        "cogs.slash_error_completion_guard",
    }
    extra_events = getattr(bot, "extra_events", {})
    for event_name, listeners in list(extra_events.items()):
        for callback in list(listeners):
            if getattr(callback, "__module__", "") in blocked_modules:
                try:
                    bot.remove_listener(callback, event_name)
                    removed += 1
                except Exception:
                    pass

    for attr in ("_sentrix_slash_relay_task", "_sentrix_slash_startup_task"):
        task = getattr(bot, attr, None)
        if task is not None and hasattr(task, "cancel") and not task.done():
            task.cancel()
    return removed


def _apply(bot: commands.Bot) -> None:
    _install_context_send()
    _install_context_defer()
    _install_interaction_methods()
    _install_message_edit()
    _install_followups()
    _install_plain_errors(bot)
    removed = _remove_old_slash_listeners(bot)
    bot._sentrix_canonical_interactions = True
    bot._sentrix_canonical_removed_listeners = removed


async def setup(bot: commands.Bot) -> None:
    _apply(bot)

    async def apply_when_ready():
        # on_ready arrive après le chargement de tous les runtimes historiques : on reprend
        # donc définitivement la main à cet instant.
        _apply(bot)
        logger.info(
            "Interactions canoniques actives : texte libre, slash privés, %s ancien(s) listener(s) retiré(s).",
            getattr(bot, "_sentrix_canonical_removed_listeners", 0),
        )

    bot.add_listener(apply_when_ready, "on_ready")
