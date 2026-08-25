"""Erreurs de commandes SentriX : une seule réponse, courte et utile."""
from __future__ import annotations

import difflib
import inspect
import logging
import time
from types import MethodType

from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.error-experience-v3")
_TECHNICAL_PARAMS = {"ctx", "context", "interaction", "self", "cog"}
_UNKNOWN_REPLY_COOLDOWN = 2.0

_PARAM_LABELS = {
    "member": "membre",
    "user": "utilisateur",
    "target": "cible",
    "role": "rôle",
    "channel": "salon",
    "reason": "raison",
    "duration": "durée",
    "time": "durée",
    "amount": "montant",
    "number": "nombre",
    "message": "message",
    "text": "texte",
    "commande": "commande",
    "command": "commande",
    "query": "recherche",
    "name": "nom",
}


def _prefix(ctx: commands.Context) -> str:
    return str(getattr(ctx, "clean_prefix", None) or "+")


def _safe_usage(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return f"{_prefix(ctx)}help"

    usage = str(getattr(command, "usage", None) or getattr(command, "signature", None) or "").strip()
    parts = [
        part for part in usage.split()
        if part.strip("<[]>*=").casefold() not in _TECHNICAL_PARAMS
    ]
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
    for command in bot.commands:
        if getattr(command, "hidden", False):
            continue
        name = str(command.name).casefold()
        if name:
            candidates.append(name)
            canonical[name] = command.name
        for alias in getattr(command, "aliases", ()) or ():
            alias_name = str(alias).casefold()
            if alias_name:
                candidates.append(alias_name)
                canonical[alias_name] = command.name
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
    state = getattr(bot, "_sentrix_unknown_command_replies_v3", None)
    if not isinstance(state, dict):
        state = {}
        bot._sentrix_unknown_command_replies_v3 = state
    user_id = int(getattr(getattr(ctx, "author", None), "id", 0) or 0)
    previous = float(state.get(user_id, 0.0))
    if now - previous < _UNKNOWN_REPLY_COOLDOWN:
        return False
    state[user_id] = now
    if len(state) > 2000:
        cutoff = now - 60.0
        for key, stamp in list(state.items()):
            if stamp < cutoff:
                state.pop(key, None)
    return True


async def _handle_user_error(bot: commands.Bot, ctx: commands.Context, error: commands.CommandError) -> bool:
    base = getattr(error, "original", error)

    if isinstance(base, commands.CommandNotFound):
        if not _can_reply_unknown(bot, ctx):
            return True
        typed = str(getattr(ctx, "invoked_with", "") or "").strip()
        suggestions = _suggestions(bot, typed)
        prefix = _prefix(ctx)
        if suggestions:
            proposed = ", ".join(f"`{prefix}{name}`" for name in suggestions)
            text = f"`{prefix}{typed}` n'existe pas. Essaie {proposed}."
        else:
            text = f"`{prefix}{typed}` n'existe pas. Ouvre `{prefix}help` pour rechercher une commande."
        await ctx.send(embed=embeds.warning(text))
        return True

    if isinstance(base, commands.MissingRequiredArgument):
        label = _param_label(getattr(base, "param", None))
        await ctx.send(embed=embeds.warning(
            f"Il manque **{label}**. Utilise : `{_safe_usage(ctx)}`"
        ))
        return True

    if isinstance(base, commands.TooManyArguments):
        await ctx.send(embed=embeds.warning(
            f"Trop d'arguments. Utilise : `{_safe_usage(ctx)}`"
        ))
        return True

    target_errors = (
        commands.MemberNotFound,
        commands.UserNotFound,
        commands.RoleNotFound,
        commands.ChannelNotFound,
        commands.MessageNotFound,
    )
    if isinstance(base, target_errors):
        await ctx.send(embed=embeds.warning(
            f"Cible introuvable. Vérifie la mention, le nom ou l'ID.\nUtilise : `{_safe_usage(ctx)}`"
        ))
        return True

    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError)):
        await ctx.send(embed=embeds.warning(
            f"Argument invalide. Utilise : `{_safe_usage(ctx)}`"
        ))
        return True

    return False


def install(bot: commands.Bot) -> None:
    current = getattr(bot, "on_command_error", None)
    if not callable(current):
        return
    if getattr(current, "_sentrix_error_experience_v3", False):
        return

    original = current

    async def improved_on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        try:
            if await _handle_user_error(self, ctx, error):
                return
        except Exception:
            logger.exception("Erreur dans l'expérience d'erreur V3 ; fallback handler historique.")

        result = original(ctx, error)
        if inspect.isawaitable(result):
            return await result
        return result

    improved_on_command_error._sentrix_error_experience_v3 = True
    improved_on_command_error._sentrix_previous_error_handler = original
    bot.on_command_error = MethodType(improved_on_command_error, bot)
    bot._sentrix_error_experience_v3 = True
    logger.info("Erreurs V3 actives : une seule carte compacte par erreur utilisateur.")


__all__ = ["install", "_suggestions", "_safe_usage"]
