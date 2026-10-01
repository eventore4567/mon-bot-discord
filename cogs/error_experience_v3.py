"""Gestionnaire officiel des erreurs des commandes préfixées SentriX."""
from __future__ import annotations

import difflib
import inspect
import logging
import time
from types import MethodType

from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from cogs.command_response_guard import _command_suggestions

logger = logging.getLogger("bot.errors")
_TECHNICAL_PARAMS = {"ctx", "context", "interaction", "self", "cog"}
_UNKNOWN_REPLY_COOLDOWN = 2.0
_PARAM_LABELS = {
    "member": "membre", "user": "utilisateur", "target": "cible", "role": "rôle",
    "channel": "salon", "reason": "raison", "duration": "durée", "time": "durée",
    "amount": "montant", "number": "nombre", "message": "message", "text": "texte",
    "commande": "commande", "command": "commande", "query": "recherche", "name": "nom",
}


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


def _param_label(param: commands.Parameter | None) -> str:
    if param is None:
        return "argument"
    name = str(getattr(param, "displayed_name", None) or getattr(param, "name", "argument")).casefold()
    return _PARAM_LABELS.get(name, name.replace("_", " "))


def _command_candidates(bot: commands.Bot) -> tuple[list[str], dict[str, str]]:
    candidates: list[str] = []
    canonical: dict[str, str] = {}
    for command in bot.walk_commands():
        if getattr(command, "hidden", False):
            continue
        for value in (command.qualified_name, command.name, *(getattr(command, "aliases", ()) or ())):
            key = str(value or "").casefold().strip()
            if key:
                candidates.append(key)
                canonical[key] = command.qualified_name
    return list(dict.fromkeys(candidates)), canonical


def _suggestions(bot: commands.Bot, typed: str, *, limit: int = 2) -> list[str]:
    typed = str(typed or "").casefold().strip()
    if not typed:
        return []
    candidates, canonical = _command_candidates(bot)
    matches = difflib.get_close_matches(typed, candidates, n=max(limit * 2, 4), cutoff=0.56)
    result: list[str] = []
    for match in matches:
        name = canonical.get(match, match)
        if name not in result:
            result.append(name)
        if len(result) >= limit:
            break
    return result


def _can_reply_unknown(bot: commands.Bot, ctx: commands.Context) -> bool:
    now = time.monotonic()
    state = getattr(bot, "_sentrix_unknown_command_replies", None)
    if not isinstance(state, dict):
        state = {}
        bot._sentrix_unknown_command_replies = state
    user_id = int(getattr(getattr(ctx, "author", None), "id", 0) or 0)
    previous = float(state.get(user_id, 0.0))
    if now - previous < _UNKNOWN_REPLY_COOLDOWN:
        return False
    state[user_id] = now
    return True


async def _send_plain(ctx: commands.Context, text: str, *, delete_after: float | None = None):
    """Envoie du vrai texte Discord sans passer par la conversion globale en embed.

    La politique visuelle finale remplace Context.send et convertit normalement tout texte
    de commande en carte SentriX. Une commande inconnue n'a volontairement pas de carte :
    on appelle donc le transport Discord original conservé par le wrapper final.
    """
    sender = getattr(commands.Context.send, "_sentrix_original", commands.Context.send)
    kwargs = {"delete_after": float(delete_after)} if delete_after is not None else {}
    return await sender(ctx, text, **kwargs)


async def _handle_user_error(bot: commands.Bot, ctx: commands.Context, error: commands.CommandError) -> bool:
    base = getattr(error, "original", error)
    prefix = _prefix(ctx)

    # +logsdiag doit exposer l'erreur brute au lieu de la masquer derrière le fallback.
    command = getattr(ctx, "command", None)
    command_name = str(
        getattr(command, "qualified_name", "") or getattr(ctx, "invoked_with", "")
    ).casefold()
    if command_name == "logsdiag":
        detail = str(base).replace("```", "'''").replace("\n", " ")[:1500]
        await ctx.send(
            "```text\n"
            f"LOGSDIAG COMMAND ERROR\nTYPE={type(base).__name__}\nDETAIL={detail or '(aucun message)'}\n"
            "```"
        )
        logger.error(
            "+logsdiag a échoué: %s: %s",
            type(base).__name__,
            detail,
        )
        return True

    if isinstance(base, commands.CommandNotFound):
        if not _can_reply_unknown(bot, ctx):
            return True
        typed = str(getattr(ctx, "invoked_with", "") or "").casefold().strip()
        suggestions = _command_suggestions(bot, ctx, typed)
        if suggestions:
            rendered = " ou ".join(f"`{prefix}{name}`" for name in suggestions[:2])
            text = f"Commande introuvable. Essayez {rendered}."
        else:
            text = "Commande introuvable. Utilisez `/help` pour voir les commandes disponibles."
        await _send_plain(ctx, text, delete_after=5)
        return True

    if isinstance(base, commands.MissingRequiredArgument):
        label = _param_label(getattr(base, "param", None))
        await _send_plain(ctx, f"Il manque `{label}`. Utilise `{_safe_usage(ctx)}`.")
        return True

    if isinstance(base, commands.TooManyArguments):
        await _send_plain(ctx, f"Trop d'arguments. Utilise `{_safe_usage(ctx)}`.")
        return True

    if isinstance(base, (commands.MemberNotFound, commands.UserNotFound)):
        await _send_plain(ctx, "Utilisateur introuvable. Vérifie la mention, le nom ou l'ID.")
        return True
    if isinstance(base, commands.RoleNotFound):
        await _send_plain(ctx, "Rôle introuvable. Vérifie la mention, le nom ou l'ID.")
        return True
    if isinstance(base, commands.ChannelNotFound):
        await _send_plain(ctx, "Salon introuvable. Vérifie la mention, le nom ou l'ID.")
        return True
    if isinstance(base, commands.MessageNotFound):
        await _send_plain(ctx, "Message introuvable. Vérifie l'ID ou le lien.")
        return True

    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError)):
        await _send_plain(ctx, f"Valeur invalide. Utilise `{_safe_usage(ctx)}`.")
        return True

    if isinstance(base, commands.CommandOnCooldown):
        await _send_plain(ctx, f"Réessaie dans `{base.retry_after:.1f}s`.")
        return True

    if isinstance(base, commands.MissingPermissions):
        required = ", ".join(permission.replace("_", " ") for permission in base.missing_permissions)
        await _send_plain(ctx, f"Permission(s) manquante(s) : `{required}`.")
        return True

    if isinstance(base, commands.BotMissingPermissions):
        required = ", ".join(permission.replace("_", " ") for permission in base.missing_permissions)
        await _send_plain(ctx, f"SentriX n'a pas la permission : `{required}`.")
        return True

    if isinstance(base, commands.NoPrivateMessage):
        await _send_plain(ctx, "Cette commande doit être utilisée dans un serveur.")
        return True

    if isinstance(base, commands.PrivateMessageOnly):
        await _send_plain(ctx, "Cette commande doit être utilisée en message privé.")
        return True

    if isinstance(base, commands.CheckFailure):
        await _send_plain(ctx, "Tu n'as pas la permission d'utiliser cette commande.")
        return True

    return False


def install(bot: commands.Bot) -> None:
    current = getattr(bot, "on_command_error", None)
    if not callable(current) or getattr(current, "_sentrix_official_errors", False):
        return
    original = current

    async def improved_on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        try:
            if await _handle_user_error(self, ctx, error):
                return
        except Exception:
            logger.exception("Erreur du gestionnaire officiel ; utilisation du fallback historique.")
        result = original(ctx, error)
        if inspect.isawaitable(result):
            return await result
        return result

    improved_on_command_error._sentrix_official_errors = True
    improved_on_command_error._sentrix_previous_error_handler = original
    bot.on_command_error = MethodType(improved_on_command_error, bot)
    logger.info("Gestionnaire officiel des erreurs préfixées actif.")


__all__ = ["install", "_safe_usage"]
