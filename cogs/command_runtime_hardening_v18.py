"""Durcissement V18 du moteur de commandes SentriX.

Complète command_integrity_v18 avec trois corrections globales :
1. restaure la signature d'origine des callbacks enveloppés par les runtimes SentriX ;
2. classe la racine +create dans la politique de configuration ;
3. retente UNE fois le chargement d'une extension uniquement si discord.py signale une
   collision de commande, après nettoyage des alias synthétiques V16.

Le retry ne s'applique jamais aux SyntaxError/ImportError/bugs métier : ceux-ci restent
visibles et ne sont pas masqués.
"""
from __future__ import annotations

import inspect
import logging
from types import MethodType
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.command-runtime-hardening-v18")


def _state(bot: commands.Bot) -> dict[str, Any]:
    value = getattr(bot, "_sentrix_command_hardening_v18", None)
    if isinstance(value, dict):
        return value
    value = {
        "load_extension_patched": False,
        "signature_repairs": set(),
        "policy_registered": False,
    }
    bot._sentrix_command_hardening_v18 = value
    return value


def _original_callable(callback):
    """Retrouve l'original marqué par les runtimes sans dérouler une chaîne infinie."""
    seen: set[int] = set()
    current = callback
    best = None
    for _ in range(12):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        candidate = getattr(current, "_sentrix_original", None) or getattr(current, "__wrapped__", None)
        if candidate is None or not callable(candidate):
            break
        best = candidate
        current = candidate
    return best


def _signature_is_generic(signature: inspect.Signature) -> bool:
    params = list(signature.parameters.values())
    if not params:
        return False
    kinds = {param.kind for param in params}
    return bool(
        inspect.Parameter.VAR_POSITIONAL in kinds
        or inspect.Parameter.VAR_KEYWORD in kinds
    )


def repair_wrapped_signatures(bot: commands.Bot) -> int:
    """Restaure seulement les métadonnées de signature, jamais le callback lui-même."""
    repaired = 0
    state = _state(bot)
    repaired_keys: set[str] = state["signature_repairs"]

    for command in list(bot.walk_commands()):
        callback = getattr(command, "callback", None)
        if callback is None or not callable(callback):
            continue
        original = _original_callable(callback)
        if original is None:
            continue
        try:
            current_signature = inspect.signature(callback)
            original_signature = inspect.signature(original)
        except (TypeError, ValueError):
            continue

        # functools.wraps peut déjà exposer correctement la signature originale. Dans ce
        # cas on ne touche rien. On cible seulement les wrappers génériques *args/**kwargs
        # ou ceux dont la signature diffère clairement de leur source.
        if current_signature == original_signature:
            continue
        if not _signature_is_generic(current_signature):
            continue

        try:
            callback.__signature__ = original_signature
        except (AttributeError, TypeError):
            continue

        key = str(getattr(command, "qualified_name", "") or getattr(command, "name", "commande"))
        if key not in repaired_keys:
            repaired_keys.add(key)
            logger.info("V18 : signature du wrapper restaurée pour +%s.", key)
        repaired += 1

    return repaired


def register_missing_policy() -> None:
    """Les sous-commandes +create héritent de la racine `create` dans le check global."""
    try:
        from .v17_shared import register_command_policy
        register_command_policy(configuration={"create"})
    except Exception:
        logger.debug("V18 : politique +create pas encore enregistrable.", exc_info=True)


def _is_registration_collision(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, commands.CommandRegistrationError):
            return True
        nested = getattr(current, "original", None) or getattr(current, "__cause__", None)
        current = nested if isinstance(nested, BaseException) else None
    return False


def install_extension_retry(bot: commands.Bot) -> None:
    """Retry unique et ciblé des collisions de registre pendant le bootstrap."""
    state = _state(bot)
    if state["load_extension_patched"]:
        return

    current = bot.load_extension
    function = getattr(current, "__func__", current)
    if getattr(function, "_sentrix_v18_registration_retry", False):
        state["load_extension_patched"] = True
        return

    async def load_extension_v18(_bot: commands.Bot, name: str, *, package: str | None = None):
        try:
            return await current(name, package=package)
        except Exception as error:
            if not _is_registration_collision(error):
                raise

            # L'extension Discord.py est nettoyée par load_extension lors d'un échec. On
            # retire ensuite les alias synthétiques responsables et on retente UNE fois.
            try:
                from .command_integrity_v18 import _disable_v16_runtime_aliases, _repair_alias_collisions
                removed = _disable_v16_runtime_aliases(_bot)
                repaired = _repair_alias_collisions(_bot)
            except Exception:
                logger.exception("V18 : nettoyage avant retry d'extension impossible.")
                raise error

            logger.warning(
                "V18 : collision pendant le chargement de %s ; retry unique après nettoyage "
                "(%s alias V16 retiré(s), %s collision(s) réparée(s)).",
                name,
                removed,
                repaired,
            )
            return await current(name, package=package)

    load_extension_v18._sentrix_v18_registration_retry = True
    load_extension_v18._sentrix_original = function
    bot.load_extension = MethodType(load_extension_v18, bot)
    state["load_extension_patched"] = True


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    register_missing_policy()
    repair_wrapped_signatures(bot)
    install_extension_retry(bot)


__all__ = ["install", "repair_wrapped_signatures"]
