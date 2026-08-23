"""SentriX V16 — amélioration transversale de toutes les commandes Discord.

Cette couche n'ajoute aucune fonctionnalité métier et ne touche pas au dashboard. Elle
améliore automatiquement le registre de commandes existant :
- syntaxe uniforme et lisible dans les erreurs ;
- alias compacts sans tiret quand ils ne créent aucun conflit ;
- résolution des membres par ID/mention avec fetch Discord en repli ;
- messages d'erreur précis pour rôles manquants, concurrence, mauvais arguments, DM, etc. ;
- suggestions de fautes de frappe propres et compatibles avec le +help racine ;
- erreurs HTTP Discord traduites en explications utiles plutôt qu'en erreur technique vague.

Toutes les permissions/checks historiques restent la source de vérité. Aucun fuzzy-match
n'exécute automatiquement une commande : une faute ne fait que proposer des suggestions.
"""
from __future__ import annotations

import logging
import re
import sys
from types import MethodType
from typing import Any

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.v16-commands")


def _state(bot: commands.Bot) -> dict[str, Any]:
    state = getattr(bot, "_sentrix_v16_state", None)
    if not isinstance(state, dict):
        state = {
            "metadata_passes": 0,
            "compact_aliases": set(),
            "member_converter_patched": False,
            "prefix_error_target": None,
            "slash_error_target": None,
            "unknown_listener_installed": False,
            "old_unknown_listener_removed": False,
            "usage_patched": False,
        }
        bot._sentrix_v16_state = state
    return state


def _runtime_main():
    return sys.modules.get("main") or sys.modules.get("__main__")


def _preferred_name(command: commands.Command) -> str:
    try:
        from .common_command_names import preferred_name
        value = preferred_name(command)
        if value:
            return str(value)
    except Exception:
        pass
    return str(getattr(command, "qualified_name", "") or getattr(command, "name", "commande"))


def _friendly_usage(ctx: commands.Context) -> str | None:
    command = getattr(ctx, "command", None)
    if command is None:
        return None
    prefix = str(getattr(ctx, "clean_prefix", None) or "+")
    display = _preferred_name(command)
    explicit = str(getattr(command, "usage", "") or "").strip()
    if explicit:
        return f"{prefix}{display} {explicit}".strip()

    parts: list[str] = []
    for name, param in getattr(command, "clean_params", {}).items():
        required = bool(getattr(param, "required", False))
        greedy = bool(getattr(param, "kind", None) in {
            getattr(__import__("inspect"), "Parameter").VAR_POSITIONAL,
            getattr(__import__("inspect"), "Parameter").VAR_KEYWORD,
        })
        shown = f"{name}..." if greedy else name
        parts.append(f"<{shown}>" if required else f"[{shown}]")
    return " ".join([f"{prefix}{display}", *parts]).strip()


def _install_usage_formatter(bot: commands.Bot) -> None:
    state = _state(bot)
    if state["usage_patched"]:
        return
    main = _runtime_main()
    if main is None:
        return
    current = getattr(main, "command_usage", None)
    if current is None:
        return

    def command_usage_v16(ctx: commands.Context) -> str | None:
        return _friendly_usage(ctx)

    command_usage_v16._sentrix_v16 = True
    command_usage_v16._sentrix_original = current
    main.command_usage = command_usage_v16
    state["usage_patched"] = True


def _register_compact_aliases(bot: commands.Bot) -> int:
    """Ajoute +ticketreopen pour +ticket-reopen, uniquement quand le nom est libre."""
    state = _state(bot)
    added = 0
    for command in list(bot.commands):
        if command.parent is not None or not getattr(command, "enabled", True):
            continue
        name = str(getattr(command, "name", "") or "").casefold()
        if "-" not in name:
            continue
        compact = name.replace("-", "")
        if not compact or compact == name:
            continue
        existing = bot.all_commands.get(compact)
        if existing is not None and existing is not command:
            continue
        aliases = getattr(command, "aliases", None)
        if isinstance(aliases, list) and compact not in aliases:
            aliases.append(compact)
        bot.all_commands[compact] = command
        if compact not in state["compact_aliases"]:
            state["compact_aliases"].add(compact)
            added += 1
    state["metadata_passes"] += 1
    return added


def _install_member_converter(bot: commands.Bot) -> None:
    state = _state(bot)
    if state["member_converter_patched"]:
        return
    current = commands.MemberConverter.convert
    if getattr(current, "_sentrix_v16_fetch_member", False):
        state["member_converter_patched"] = True
        return

    async def member_convert_v16(self, ctx: commands.Context, argument: str):
        try:
            return await current(self, ctx, argument)
        except commands.MemberNotFound as original:
            guild = getattr(ctx, "guild", None)
            if guild is None:
                raise
            text = str(argument or "").strip()
            match = re.fullmatch(r"<@!?(\d{15,25})>", text) or re.fullmatch(r"(\d{15,25})", text)
            if not match:
                raise
            user_id = int(match.group(1))
            cached = guild.get_member(user_id)
            if cached is not None:
                return cached
            try:
                return await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                raise original

    member_convert_v16._sentrix_v16_fetch_member = True
    member_convert_v16._sentrix_original = current
    commands.MemberConverter.convert = member_convert_v16
    state["member_converter_patched"] = True


def _role_text(role) -> str:
    if isinstance(role, int):
        return f"le rôle avec l'ID `{role}`"
    value = str(role or "rôle requis").strip()
    return f"le rôle **{value}**"


def _roles_text(roles) -> str:
    values = list(roles or ())
    if not values:
        return "un rôle autorisé"
    return ", ".join(_role_text(role) for role in values[:6])


async def _send_prefix_error(ctx: commands.Context, title: str, description: str, *, warning: bool = False):
    if getattr(ctx, "_sentrix_v16_error_sent", False):
        return None
    ctx._sentrix_v16_error_sent = True
    builder = embeds.warning if warning else embeds.error
    return await ctx.send(embed=builder(description, title=title))


def _prefix_special_error(error: commands.CommandError):
    raw = getattr(error, "original", error)

    if isinstance(raw, commands.TooManyArguments):
        return "Trop d'arguments", "Tu as ajouté trop d'informations à la commande."
    if isinstance(raw, commands.MaxConcurrencyReached):
        return "Commande déjà en cours", "Cette commande est déjà en cours d'exécution. Attends qu'elle se termine puis réessaie."
    if isinstance(raw, commands.NoPrivateMessage):
        return "Serveur requis", "Cette commande doit être utilisée dans un serveur Discord, pas en message privé."
    if isinstance(raw, commands.PrivateMessageOnly):
        return "Message privé requis", "Cette commande doit être utilisée en message privé avec SentriX."
    if isinstance(raw, commands.DisabledCommand):
        return "Commande désactivée", "Cette commande est temporairement désactivée."
    if isinstance(raw, commands.NotOwner):
        return "Accès refusé", "Cette commande est réservée au propriétaire du bot."
    if isinstance(raw, commands.MissingRole):
        return "Rôle requis", f"Il te manque {_role_text(raw.missing_role)} pour utiliser cette commande."
    if isinstance(raw, commands.MissingAnyRole):
        return "Rôle requis", f"Il te faut au moins un de ces rôles : {_roles_text(raw.missing_roles)}."
    if isinstance(raw, commands.BotMissingRole):
        return "Rôle du bot manquant", f"SentriX doit posséder {_role_text(raw.missing_role)} pour terminer cette action."
    if isinstance(raw, commands.BotMissingAnyRole):
        return "Rôle du bot manquant", f"SentriX doit posséder au moins un de ces rôles : {_roles_text(raw.missing_roles)}."
    if isinstance(raw, commands.BadBoolArgument):
        return "Valeur invalide", "Cette option attend une valeur du type `oui/non`, `on/off` ou `true/false`."

    bad_literal = getattr(commands, "BadLiteralArgument", None)
    if bad_literal is not None and isinstance(raw, bad_literal):
        literals = list(getattr(raw, "literals", ()) or ())
        shown = ", ".join(f"`{value}`" for value in literals[:10]) or "une des valeurs proposées"
        return "Choix invalide", f"Cette option accepte uniquement : {shown}."

    if isinstance(raw, discord.NotFound):
        return "Élément introuvable", "Le membre, rôle, salon ou message visé n'existe plus. Actualise la cible puis réessaie."

    if isinstance(raw, discord.HTTPException) and not isinstance(raw, discord.Forbidden):
        status = int(getattr(raw, "status", 0) or 0)
        code = int(getattr(raw, "code", 0) or 0)
        if status == 429:
            return "Discord est occupé", "Discord limite temporairement les requêtes. Attends quelques secondes puis réessaie."
        if status >= 500:
            return "Discord indisponible", "Discord rencontre une erreur temporaire. Aucune nouvelle action n'est nécessaire pour le moment ; réessaie dans quelques instants."
        if code in {10003, 10007, 10008, 10011, 10013}:
            return "Élément introuvable", "La cible de la commande a été supprimée ou n'est plus accessible."
        if code == 50035:
            return "Valeur refusée par Discord", "Une valeur n'est plus valide pour cette action. Vérifie le membre, le rôle, le salon ou le texte fourni."
    return None


def _install_prefix_error_handler(bot: commands.Bot) -> None:
    state = _state(bot)
    current = bot.on_command_error
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_v16_command_errors", False):
        state["prefix_error_target"] = id(function)
        return
    if state.get("prefix_error_target") == id(function):
        return

    async def on_command_error_v16(_bot, ctx: commands.Context, error: commands.CommandError):
        special = _prefix_special_error(error)
        if special is not None:
            title, description = special
            usage = _friendly_usage(ctx)
            if usage and not isinstance(getattr(error, "original", error), (
                commands.NoPrivateMessage,
                commands.PrivateMessageOnly,
                commands.DisabledCommand,
                commands.NotOwner,
                commands.MaxConcurrencyReached,
            )):
                description += f"\n\nSyntaxe : `{usage}`"
            return await _send_prefix_error(ctx, title, description)
        return await current(ctx, error)

    on_command_error_v16._sentrix_v16_command_errors = True
    on_command_error_v16._sentrix_original = function
    bot.on_command_error = MethodType(on_command_error_v16, bot)
    state["prefix_error_target"] = id(getattr(bot.on_command_error, "__func__", bot.on_command_error))


def _remove_old_unknown_listener(bot: commands.Bot) -> None:
    state = _state(bot)
    if state["old_unknown_listener_removed"]:
        return
    listeners = list(getattr(bot, "extra_events", {}).get("on_command_error", []))
    for listener in listeners:
        if getattr(listener, "__name__", "") == "improve_prefix_command_error":
            bot.remove_listener(listener, "on_command_error")
    state["old_unknown_listener_removed"] = True


def _install_unknown_command_listener(bot: commands.Bot) -> None:
    state = _state(bot)
    if state["unknown_listener_installed"]:
        return

    async def unknown_command_v16(ctx: commands.Context, error: commands.CommandError):
        raw = getattr(error, "original", error)
        if not isinstance(raw, commands.CommandNotFound):
            return
        try:
            from . import command_response_guard as guard
            author = getattr(ctx, "author", None)
            if author is None or not guard._allow_unknown_reply(author.id):
                return
            typed = guard._typed_command_path(bot, ctx)
            if not typed:
                return
            suggestions = guard._command_suggestions(bot, ctx, typed)
        except Exception:
            suggestions = []
            content = str(getattr(getattr(ctx, "message", None), "content", "") or "")
            prefix = str(getattr(ctx, "clean_prefix", None) or "+")
            typed = content[len(prefix):].split(maxsplit=1)[0] if content.startswith(prefix) else content

        prefix = str(getattr(ctx, "clean_prefix", None) or "+")
        if suggestions:
            options = "\n".join(f"• `{prefix}{name}`" for name in suggestions[:3])
            text = (
                f"La commande `{prefix}{typed}` n'existe pas.\n\n"
                f"Tu voulais peut-être utiliser :\n{options}\n\n"
                f"Ouvre `{prefix}help` puis utilise **Rechercher** pour voir la syntaxe exacte."
            )
        else:
            text = (
                f"La commande `{prefix}{typed}` n'existe pas.\n"
                f"Ouvre `{prefix}help` pour voir les commandes disponibles."
            )
        try:
            await ctx.send(embed=embeds.warning(text, title="Commande introuvable"))
        except (discord.Forbidden, discord.HTTPException):
            pass

    bot.add_listener(unknown_command_v16, "on_command_error")
    state["unknown_listener_installed"] = True


def _install_slash_error_handler(bot: commands.Bot) -> None:
    state = _state(bot)
    current = bot.tree.on_error
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_v16_slash_errors", False):
        state["slash_error_target"] = id(function)
        return
    if state.get("slash_error_target") == id(function):
        return

    async def slash_error_v16(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        raw = getattr(error, "original", error)
        embed = None
        if isinstance(raw, discord.NotFound):
            embed = embeds.error(
                "Le membre, rôle, salon ou message visé n'existe plus. Actualise la cible puis réessaie.",
                title="Élément introuvable",
            )
        elif isinstance(raw, discord.HTTPException) and not isinstance(raw, discord.Forbidden):
            status = int(getattr(raw, "status", 0) or 0)
            code = int(getattr(raw, "code", 0) or 0)
            if status == 429:
                embed = embeds.warning("Discord limite temporairement les requêtes. Réessaie dans quelques secondes.", title="Discord est occupé")
            elif status >= 500:
                embed = embeds.warning("Discord rencontre une erreur temporaire. Réessaie dans quelques instants.", title="Discord indisponible")
            elif code == 50035:
                embed = embeds.error("Une valeur n'est plus valide. Vérifie les choix de la commande puis réessaie.", title="Valeur refusée")

        if embed is None:
            return await current(interaction, error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            logger.debug("V16 : impossible d'envoyer l'erreur slash améliorée.", exc_info=True)

    slash_error_v16._sentrix_v16_slash_errors = True
    slash_error_v16._sentrix_original = function
    bot.tree.on_error = slash_error_v16
    state["slash_error_target"] = id(slash_error_v16)


def install(bot: commands.Bot) -> None:
    """Réapplique la couche après chaque extension ; toutes les opérations sont sûres/idempotentes."""
    state = _state(bot)
    _install_usage_formatter(bot)
    added = _register_compact_aliases(bot)
    _install_member_converter(bot)
    _remove_old_unknown_listener(bot)
    _install_unknown_command_listener(bot)
    _install_prefix_error_handler(bot)
    _install_slash_error_handler(bot)
    bot._sentrix_v16_commands_active = True
    if added:
        logger.info("V16 : %s alias compact(s) de commandes ajouté(s) sans conflit.", added)
    if state["metadata_passes"] == 1:
        logger.info("SentriX V16 Commandes actif : syntaxe, erreurs, membres et alias améliorés globalement.")


__all__ = ["install"]
