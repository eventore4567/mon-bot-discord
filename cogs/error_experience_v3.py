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


async def _send_plain(ctx: commands.Context, text: str):
    """Envoie du vrai texte Discord sans passer par la conversion globale en embed.

    La politique visuelle finale remplace Context.send et convertit normalement tout texte
    de commande en carte SentriX. Une commande inconnue n'a volontairement pas de carte :
    on appelle donc le transport Discord original conservé par le wrapper final.
    """
    sender = getattr(commands.Context.send, "_sentrix_original", commands.Context.send)
    return await sender(ctx, text)


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
        await _send_plain(ctx, text)
        return True

    if isinstance(base, commands.MissingRequiredArgument):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"Il manque **{_param_label(getattr(base, 'param', None))}**.\n\nUtilisation : `{_safe_usage(ctx)}`", title='Argument manquant')))
        return True

    if isinstance(base, commands.TooManyArguments):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Utilisation : `{_safe_usage(ctx)}`', title='Trop d’arguments')))
        return True

    if isinstance(base, (commands.MemberNotFound, commands.UserNotFound)):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vérifiez la mention, le nom ou l’ID.', title='Utilisateur introuvable')))
        return True
    if isinstance(base, commands.RoleNotFound):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vérifiez la mention, le nom ou l’ID du rôle.', title='Rôle introuvable')))
        return True
    if isinstance(base, commands.ChannelNotFound):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vérifiez la mention, le nom ou l’ID du salon.', title='Salon introuvable')))
        return True
    if isinstance(base, commands.MessageNotFound):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vérifiez l’ID ou le lien du message.', title='Message introuvable')))
        return True

    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError)):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Utilisation : `{_safe_usage(ctx)}`', title='Argument invalide')))
        return True

    if isinstance(base, commands.CommandOnCooldown):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Réessayez dans **{base.retry_after:.1f} s**.', title='Commande en cooldown')))
        return True

    if isinstance(base, commands.MissingPermissions):
        required = ", ".join(permission.replace("_", " ") for permission in base.missing_permissions)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Permission requise : **{required}**.', title='Permission insuffisante')))
        return True

    if isinstance(base, commands.BotMissingPermissions):
        required = ", ".join(permission.replace("_", " ") for permission in base.missing_permissions)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'SentriX a besoin de : **{required}**.', title='Permission du bot insuffisante')))
        return True

    if isinstance(base, commands.NoPrivateMessage):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Cette commande doit être utilisée dans un serveur.', title='Serveur requis')))
        return True

    if isinstance(base, commands.PrivateMessageOnly):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Cette commande doit être utilisée en message privé.', title='Message privé requis')))
        return True

    if isinstance(base, commands.CheckFailure):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous n’êtes pas autorisé à utiliser cette commande.', title='Accès refusé')))
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
