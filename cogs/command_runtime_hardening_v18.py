"""Durcissement V18 du moteur de commandes SentriX.

Complète command_integrity_v18 avec trois corrections globales :
1. restaure la signature ET les paramètres discord.py d'origine des callbacks enveloppés
   par les runtimes SentriX ;
2. classe la racine +create dans la politique de configuration ;
3. retente UNE fois le chargement d'une extension uniquement si discord.py signale une
   collision de commande, après nettoyage des alias synthétiques V16.

Le point 1 est important : remplacer uniquement ``callback.__signature__`` ne suffit pas.
discord.py met en cache les paramètres convertibles dans ``Command.params`` quand le
callback est affecté. Un wrapper générique (*args, __original=..., **kwargs) peut donc
faire apparaître des arguments internes comme ``original``, ``name`` ou ``kwargs`` et
rendre une commande pourtant valide inutilisable. V18 reconstruit désormais ce cache à
partir du callback métier original, puis remet le wrapper de sécurité en place.

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
    for _ in range(16):
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


def _bad_cached_params(command: commands.Command) -> bool:
    """Détecte les paramètres internes typiques créés par un wrapper runtime."""
    reserved = {
        "self", "ctx", "context", "interaction", "bot", "_bot",
        "original", "__original", "name", "__name", "kwargs", "args",
    }
    try:
        names = {str(name).casefold().lstrip("_") for name in command.clean_params}
    except Exception:
        return True
    return bool(names & {item.lstrip("_") for item in reserved})


def _rebuild_command_params_from_original(command: commands.Command, original, wrapper) -> bool:
    """Force discord.py à recalculer Command.params depuis le callback métier original.

    L'affectation à ``Command.callback`` est justement le chemin utilisé par discord.py
    pour recalculer ses métadonnées internes. On l'utilise brièvement avec l'original,
    on sauvegarde les bons paramètres, puis on remet le wrapper et on restaure ce cache.
    Le callback exécuté reste donc le wrapper de sécurité ; seul le parsing utilisateur
    provient de la vraie commande.
    """
    try:
        command.callback = original
        good_params = dict(getattr(command, "params", {}) or {})
        command.callback = wrapper
        if not good_params:
            return False
        command.params = good_params
        return True
    except Exception:
        # Toujours remettre le wrapper même si une version de discord.py refuse une étape.
        try:
            if command.callback is not wrapper:
                command.callback = wrapper
        except Exception:
            pass
        logger.exception(
            "V18 : impossible de reconstruire les paramètres de +%s.",
            getattr(command, "qualified_name", getattr(command, "name", "?")),
        )
        return False


def repair_wrapped_signatures(bot: commands.Bot) -> int:
    """Restaure signature + cache Command.params, sans retirer les wrappers de sécurité."""
    repaired = 0
    state = _state(bot)
    repaired_keys: set[str] = state["signature_repairs"]

    for command in list(bot.walk_commands()):
        wrapper = getattr(command, "callback", None)
        if wrapper is None or not callable(wrapper):
            continue
        original = _original_callable(wrapper)
        if original is None:
            continue

        try:
            current_signature = inspect.signature(wrapper)
            original_signature = inspect.signature(original)
        except (TypeError, ValueError):
            continue

        generic = current_signature != original_signature and _signature_is_generic(current_signature)
        cached_bad = _bad_cached_params(command)
        if not generic and not cached_bad:
            continue

        params_rebuilt = _rebuild_command_params_from_original(command, original, wrapper)

        # Aide/introspection Python : exposer aussi la vraie signature sur le wrapper.
        try:
            wrapper.__signature__ = original_signature
        except (AttributeError, TypeError):
            pass

        # Vérification après réparation. Si les paramètres restent contaminés, ne pas
        # annoncer un succès silencieux : le rapport V18 le verra comme anomalie.
        if _bad_cached_params(command):
            logger.error(
                "V18 : paramètres internes encore exposés après réparation pour +%s.",
                getattr(command, "qualified_name", getattr(command, "name", "?")),
            )
            continue

        if params_rebuilt or generic:
            key = str(getattr(command, "qualified_name", "") or getattr(command, "name", "commande"))
            if key not in repaired_keys:
                repaired_keys.add(key)
                logger.info("V18 : signature + paramètres discord.py restaurés pour +%s.", key)
            repaired += 1

    # Certaines couches historiques affectent un callback décoré après la réparation et
    # discord.py peut alors conserver des ``inspect.Parameter`` bruts. Ils n'exposent pas
    # ``displayed_name`` et font planter +help lors du calcul de ``Command.signature``.
    for command in list(bot.walk_commands()):
        normalized = {}
        changed = False
        for name, param in dict(getattr(command, "params", {}) or {}).items():
            if str(name).casefold() in {"self", "ctx", "context", "interaction", "cog", "_ctx"}:
                changed = True
                continue
            if isinstance(param, commands.Parameter):
                normalized[name] = param
                continue
            if isinstance(param, inspect.Parameter):
                normalized[name] = commands.Parameter(
                    name=param.name,
                    kind=param.kind,
                    default=param.default,
                    annotation=param.annotation,
                    description=None,
                    displayed_default=None,
                    displayed_name=None,
                )
                changed = True
            else:
                normalized[name] = param
        if changed:
            command.params = normalized

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
