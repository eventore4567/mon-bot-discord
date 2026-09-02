"""SentriX V18 — intégrité finale du registre de commandes.

Cette couche est volontairement transversale et sans nouvelle commande publique. Elle
s'exécute après les runtimes historiques et protège tout le registre actif :
- retire les alias compacts ajoutés dynamiquement par V16 afin qu'ils ne puissent jamais
  réserver le nom d'une vraie commande chargée plus tard ;
- répare les collisions alias -> nom canonique en donnant toujours priorité à la vraie
  commande ;
- vérifie callbacks, signatures, groupes, sous-commandes et registre slash ;
- détecte les signatures cassées qui exposeraient `ctx`, `self`, `bot` ou `interaction`
  comme argument utilisateur ;
- centralise le dernier filet d'erreur inattendue avec le vrai type/traceback au lieu du
  faux `NoneType: None` produit par traceback.format_exc() hors bloc except ;
- évite les doubles réponses d'erreur lorsqu'une couche précédente a déjà répondu.

Aucune logique métier de modération, tickets, économie ou IA n'est remplacée ici.
"""
from __future__ import annotations

import inspect
import logging
from types import MethodType
from typing import Any

import discord
from discord.ext import commands

from database.db import PRIMARY_CREATOR_ID
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.command-integrity-v18")

_RESERVED_USER_PARAMS = frozenset({"self", "ctx", "context", "interaction", "bot", "_bot"})
# Chaque commande essentielle, avec l'extension qui la fournit. Sans ce lien,
# l'audit signalait +create-server absente a chaque passe intermediaire, alors
# que cogs.server_builder n'etait tout simplement pas encore charge.
_CREATE_REQUIRED = {
    "create": "cogs.create_command_router",
    "create sentrix": "cogs.create_command_router",
    "create server": "cogs.create_command_router",
    "create-server": "cogs.server_builder",
}


def _state(bot: commands.Bot) -> dict[str, Any]:
    current = getattr(bot, "_sentrix_command_integrity_v18", None)
    if isinstance(current, dict):
        return current
    current = {
        "error_handler_installed": False,
        "v16_alias_patch_installed": False,
        "audits": 0,
        "last_report": {},
    }
    bot._sentrix_command_integrity_v18 = current
    return current


def _disable_v16_runtime_aliases(bot: commands.Bot) -> int:
    """Supprime uniquement les alias que V16 a ajoutés dynamiquement.

    Les alias déclarés dans le code source des commandes ne sont jamais touchés. Le vieux
    système V16 était exécuté après chaque extension : un alias synthétique pouvait donc
    occuper un nom avant qu'une vraie commande portant ce nom ne soit chargée.
    """
    try:
        from . import bot_v16_commands as v16
    except Exception:
        return 0

    v16_state = getattr(bot, "_sentrix_v16_state", None)
    synthetic = set(v16_state.get("compact_aliases", set()) if isinstance(v16_state, dict) else set())
    removed = 0

    for alias in synthetic:
        key = str(alias).casefold().strip()
        if not key:
            continue
        command = bot.all_commands.get(key)
        if command is None:
            continue
        expected = str(getattr(command, "name", "") or "").casefold().replace("-", "")
        if "-" not in str(getattr(command, "name", "") or "") or expected != key:
            continue

        aliases = getattr(command, "aliases", None)
        if isinstance(aliases, list):
            command.aliases = [item for item in aliases if str(item).casefold() != key]
        if bot.all_commands.get(key) is command:
            bot.all_commands.pop(key, None)
        removed += 1

    if isinstance(v16_state, dict):
        v16_state["compact_aliases"] = set()

    current = getattr(v16, "_register_compact_aliases", None)
    if current is not None and not getattr(current, "_sentrix_v18_disabled", False):
        def no_dynamic_aliases(_bot: commands.Bot) -> int:
            return 0

        no_dynamic_aliases._sentrix_v18_disabled = True
        no_dynamic_aliases._sentrix_original = current
        v16._register_compact_aliases = no_dynamic_aliases
        _state(bot)["v16_alias_patch_installed"] = True

    return removed


def _mapping_for(command: commands.Command):
    parent = getattr(command, "parent", None)
    if isinstance(parent, commands.Group):
        return parent.all_commands
    return getattr(getattr(command, "cog", None), "bot", None)


def _repair_alias_collisions(bot: commands.Bot) -> int:
    """Une vraie commande gagne toujours contre l'alias d'une autre commande."""
    repaired = 0

    # Racine.
    canonical = {
        str(command.name).casefold(): command
        for command in bot.commands
        if getattr(command, "name", None)
    }
    for command in list(bot.commands):
        aliases = list(getattr(command, "aliases", ()) or ())
        keep: list[str] = []
        for alias in aliases:
            key = str(alias).casefold()
            real = canonical.get(key)
            if real is not None and real is not command:
                if bot.all_commands.get(key) is command:
                    bot.all_commands[key] = real
                repaired += 1
                logger.warning(
                    "V18 : alias racine `%s` retiré de +%s car +%s existe réellement.",
                    alias,
                    command.qualified_name,
                    real.qualified_name,
                )
                continue
            keep.append(alias)
        if isinstance(getattr(command, "aliases", None), list) and keep != aliases:
            command.aliases = keep

    # Sous-commandes de chaque groupe.
    for group in [item for item in bot.walk_commands() if isinstance(item, commands.Group)]:
        children = list(getattr(group, "commands", ()) or ())
        child_canonical = {
            str(child.name).casefold(): child
            for child in children
            if getattr(child, "name", None)
        }
        for child in children:
            aliases = list(getattr(child, "aliases", ()) or ())
            keep = []
            for alias in aliases:
                key = str(alias).casefold()
                real = child_canonical.get(key)
                if real is not None and real is not child:
                    if group.all_commands.get(key) is child:
                        group.all_commands[key] = real
                    repaired += 1
                    logger.warning(
                        "V18 : alias `%s` retiré de +%s car +%s existe réellement.",
                        alias,
                        child.qualified_name,
                        real.qualified_name,
                    )
                    continue
                keep.append(alias)
            if isinstance(getattr(child, "aliases", None), list) and keep != aliases:
                child.aliases = keep

    return repaired


def _callback_is_async(callback: Any) -> bool:
    if inspect.iscoroutinefunction(callback):
        return True
    call = getattr(callback, "__call__", None)
    return bool(call and inspect.iscoroutinefunction(call))


def _audit_registry(bot: commands.Bot) -> dict[str, Any]:
    commands_seen = list(bot.walk_commands())
    critical: list[str] = []
    warnings: list[str] = []
    names: dict[str, commands.Command] = {}
    aliases = 0
    groups = 0

    for command in commands_seen:
        qualified = str(getattr(command, "qualified_name", "") or "").strip()
        key = qualified.casefold()
        if not qualified:
            critical.append("commande sans nom qualifié")
            continue
        previous = names.get(key)
        if previous is not None and previous is not command:
            critical.append(f"nom dupliqué: {qualified}")
        names[key] = command

        callback = getattr(command, "callback", None)
        if callback is None or not callable(callback):
            critical.append(f"callback absent: {qualified}")
        elif not _callback_is_async(callback):
            critical.append(f"callback non async: {qualified}")

        try:
            clean_params = dict(getattr(command, "clean_params", {}) or {})
        except Exception as error:
            critical.append(f"signature illisible: {qualified} ({type(error).__name__})")
            clean_params = {}
        leaked = [name for name in clean_params if str(name).casefold() in _RESERVED_USER_PARAMS]
        if leaked:
            critical.append(f"paramètre interne exposé: {qualified} -> {', '.join(leaked)}")

        if isinstance(command, commands.Group):
            groups += 1
            for child in list(getattr(command, "commands", ()) or ()):
                if getattr(child, "parent", None) is not command:
                    critical.append(f"parent cassé: {getattr(child, 'qualified_name', child)}")

        aliases += len(list(getattr(command, "aliases", ()) or ()))

    chargees = set(getattr(bot, "extensions", {}) or {})
    for required, fournisseur in _CREATE_REQUIRED.items():
        if bot.get_command(required) is not None:
            continue
        # Absente parce que son module n'est pas encore la : ce n'est pas un
        # defaut, c'est l'ordre de chargement. L'audit final, lui, verra les
        # extensions au complet.
        if fournisseur not in chargees:
            continue
        critical.append(f"commande essentielle absente: {required}")

    try:
        app_commands = list(bot.tree.walk_commands())
    except AttributeError:
        app_commands = list(bot.tree.get_commands())
    app_names: set[str] = set()
    for command in app_commands:
        qualified = str(getattr(command, "qualified_name", getattr(command, "name", "")) or "")
        key = qualified.casefold()
        if key in app_names:
            critical.append(f"slash dupliqué: {qualified}")
        app_names.add(key)
        name = str(getattr(command, "name", "") or "")
        if not (1 <= len(name) <= 32):
            critical.append(f"nom slash invalide: {qualified}")

    if len(bot.tree.get_commands()) > 100:
        critical.append(f"budget slash dépassé: {len(bot.tree.get_commands())}/100")

    return {
        "text_commands": len(commands_seen),
        "top_level": len(list(bot.commands)),
        "aliases": aliases,
        "groups": groups,
        "app_commands": len(app_names),
        "critical": critical,
        "warnings": warnings,
    }


def _remove_duplicate_unknown_responders(bot: commands.Bot) -> int:
    """Garde au maximum un responder de faute de frappe.

    Les listeners d'observabilité/metrics restent tous intacts ; seuls les deux anciens
    responders utilisateur connus sont concernés.
    """
    listeners = list(getattr(bot, "extra_events", {}).get("on_command_error", []) or [])
    candidates = [
        listener
        for listener in listeners
        if getattr(listener, "__name__", "") in {"unknown_command_v16", "improve_prefix_command_error"}
    ]
    if len(candidates) <= 1:
        return 0

    # V16 est le responder final actuel ; conserver le plus récent évite de réintroduire
    # l'ancien texte +help <commande> qui n'est plus utilisé.
    keep = next((item for item in reversed(candidates) if getattr(item, "__name__", "") == "unknown_command_v16"), candidates[-1])
    removed = 0
    for listener in candidates:
        if listener is keep:
            continue
        bot.remove_listener(listener, "on_command_error")
        removed += 1
    return removed


def _install_unexpected_error_handler(bot: commands.Bot) -> None:
    state = _state(bot)
    if state["error_handler_installed"]:
        return

    current = bot.on_command_error
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_v18_unexpected_errors", False):
        state["error_handler_installed"] = True
        return

    async def on_command_error_v18(_bot: commands.Bot, ctx: commands.Context, error: commands.CommandError):
        raw = getattr(error, "original", error)

        # Les erreurs utilisateur/Discord attendues restent traitées par les couches
        # spécialisées existantes. V18 ne prend la main que sur une exception métier
        # inattendue réellement levée dans le callback.
        if not isinstance(error, commands.CommandInvokeError) or isinstance(raw, discord.HTTPException):
            return await current(ctx, error)

        command_name = str(getattr(getattr(ctx, "command", None), "qualified_name", "inconnue"))
        exc_info = None
        traceback_obj = getattr(raw, "__traceback__", None)
        if isinstance(raw, BaseException) and traceback_obj is not None:
            exc_info = (type(raw), raw, traceback_obj)
        logger.error(
            "Erreur réelle dans +%s : %s: %s",
            command_name,
            type(raw).__name__,
            str(raw)[:1000],
            exc_info=exc_info,
        )

        # Une commande peut avoir envoyé une réponse avant de planter sur une étape
        # secondaire. Dans ce cas on journalise mais on ne pollue pas le salon avec une
        # deuxième carte d'erreur.
        if getattr(ctx, "_sentrix_response_sent", False) or getattr(ctx, "_sentrix_v18_error_sent", False):
            return None

        ctx._sentrix_v18_error_sent = True
        reference = str(getattr(getattr(ctx, "message", None), "id", "indisponible"))
        if getattr(getattr(ctx, "author", None), "id", None) == PRIMARY_CREATOR_ID:
            detail = str(raw).strip() or "aucun détail fourni"
            description = (
                f"La commande `+{command_name}` a rencontré **{type(raw).__name__}**.\n"
                f"Détail : `{detail[:700]}`\n"
                f"Référence : `{reference}`"
            )
        else:
            description = (
                "Cette commande a rencontré un problème technique. L'erreur a été "
                f"journalisée avec la référence `{reference}`."
            )
        return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(description, title='Erreur de commande')))

    on_command_error_v18._sentrix_v18_unexpected_errors = True
    on_command_error_v18._sentrix_original = function
    bot.on_command_error = MethodType(on_command_error_v18, bot)
    state["error_handler_installed"] = True


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    state = _state(bot)

    removed_aliases = _disable_v16_runtime_aliases(bot)
    repaired_aliases = _repair_alias_collisions(bot)
    removed_responders = _remove_duplicate_unknown_responders(bot)
    _install_unexpected_error_handler(bot)

    report = _audit_registry(bot)
    report.update(
        {
            "removed_v16_aliases": removed_aliases,
            "repaired_alias_collisions": repaired_aliases,
            "removed_duplicate_error_responders": removed_responders,
        }
    )
    state["last_report"] = report
    state["audits"] = int(state.get("audits", 0)) + 1

    critical = list(report["critical"])
    # install() est rappele apres plusieurs vagues d'extensions. Une commande
    # « essentielle » peut donc manquer simplement parce que le module qui la
    # porte n'est pas encore charge : +create-server appartient a server_builder
    # et arrive plus tard. Signaler cet instantane en ERREUR remplissait le
    # journal d'alertes qui se resolvaient seules — un bruit permanent qui
    # aurait masque le prochain vrai probleme.
    #
    # Un probleme transitoire disparait a l'audit suivant ; un vrai persiste.
    # C'est donc la PERSISTANCE qui decide de la severite.
    precedents = set(state.get("critical_precedents") or ())
    state["critical_precedents"] = set(critical)
    persistants = [c for c in critical if c in precedents]

    if persistants:
        logger.error(
            "V18 audit commandes : %s problème(s) critique(s) persistant(s) — %s",
            len(persistants),
            " | ".join(persistants[:20]),
        )
    elif critical:
        logger.warning(
            "V18 audit commandes : %s problème(s) vu(s) pendant le chargement, "
            "à confirmer au prochain audit — %s",
            len(critical),
            " | ".join(critical[:20]),
        )
    elif state["audits"] == 1 or removed_aliases or repaired_aliases or removed_responders:
        logger.info(
            "V18 audit commandes OK : %s commandes texte, %s groupes, %s alias, %s slash ; "
            "alias V16 retirés=%s, collisions réparées=%s, responders doublons retirés=%s.",
            report["text_commands"],
            report["groups"],
            report["aliases"],
            report["app_commands"],
            removed_aliases,
            repaired_aliases,
            removed_responders,
        )


__all__ = ["install"]
