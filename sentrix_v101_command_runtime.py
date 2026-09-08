"""SentriX V101 — réparation centrale des commandes slash encore cassées après V100.

V101 traite trois défauts observés en production :
- certains Commands de Cog ont perdu leur liaison au Cog lors de la façade slash et leur
  callback est appelé sans ``self``/``ctx`` ;
- des wrappers internes peuvent polluer la signature publique avec ``ctx``, ``*args`` ou
  ``**kwargs`` alors que la déclaration de la commande n'expose aucune de ces options ;
- les demandes IA de code peuvent dépasser le plafond texte historique alors que Discord
  a déjà correctement différé l'interaction.

La correction reste centrale : aucune commande métier n'est patchée individuellement.
"""
from __future__ import annotations

import inspect
import logging
import shlex
from typing import Any

import discord
from discord.ext import commands

import sentrix_grouped_slash_fix as grouped
import sentrix_v95_runtime as v95
from utils import ai_service

logger = logging.getLogger("bot.v101-command-runtime")
_INSTALLED = False

_INTERNAL_CONTEXT_NAMES = frozenset({"self", "cls", "ctx", "context"})
_WRAPPER_VAR_NAMES = frozenset({"args", "kwargs"})
_AI_TIMEOUT_SECONDS = 75.0


def _is_required(parameter: Any) -> bool:
    required = getattr(parameter, "required", None)
    if required is not None:
        return bool(required)
    return getattr(parameter, "default", inspect.Parameter.empty) is inspect.Parameter.empty


def _callback_declaration(command: commands.Command):
    """Retourne la fonction de déclaration la plus proche et sa signature.

    Plusieurs couches SentriX décorent les callbacks. ``inspect.unwrap`` restaure la vraie
    méthode lorsque functools.wraps a été utilisé. Si la commande a perdu ``command.cog``,
    le ``__qualname__`` reste souvent suffisant pour retrouver la méthode de classe.
    """
    callback = getattr(command, "callback", None)
    if callback is None:
        return None, None
    candidate = inspect.unwrap(callback)

    # Si un wrapper non transparent garde malgré tout le qualname de la méthode, tenter la
    # déclaration sur la classe du Cog encore attaché.
    cog = getattr(command, "cog", None)
    method_name = getattr(candidate, "__name__", None) or getattr(callback, "__name__", None)
    if cog is not None and method_name:
        declared = getattr(type(cog), method_name, None)
        if declared is not None:
            declared = getattr(declared, "callback", declared)
            try:
                candidate = inspect.unwrap(declared)
            except Exception:
                pass

    try:
        return candidate, inspect.signature(candidate)
    except (TypeError, ValueError):
        return candidate, None


def _declared_user_params(command: commands.Command) -> list[tuple[str, Any]] | None:
    _callback, signature = _callback_declaration(command)
    if signature is None:
        return None

    params = list(signature.parameters.items())
    # Une méthode de Cog déclarée ``self, ctx, ...`` ; une commande globale ``ctx, ...``.
    if params and params[0][0].casefold() in {"self", "cls"}:
        params.pop(0)
    if params and params[0][0].casefold() in {"ctx", "context"}:
        params.pop(0)
    return params


def _effective_params(command: commands.Command) -> list[tuple[str, Any]]:
    """Paramètres réellement destinés à l'utilisateur, jamais ceux du wrapper runtime."""
    try:
        clean = list(command.clean_params.items())
    except Exception:
        clean = []

    clean_map = {str(name): parameter for name, parameter in clean}
    declared = _declared_user_params(command)

    # Si la déclaration d'origine est exploitable, elle est la source d'autorité sur les
    # NOMS. On réutilise toutefois les Parameter discord.py déjà calculés (converters,
    # defaults, required) lorsqu'ils correspondent.
    if declared is not None:
        declared_has_only_wrapper_vars = bool(declared) and all(
            parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            and name.casefold() in _WRAPPER_VAR_NAMES
            for name, parameter in declared
        )
        clean_looks_polluted = any(
            str(name).casefold() in _INTERNAL_CONTEXT_NAMES
            or (
                getattr(parameter, "kind", None)
                in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
                and str(name).casefold() in _WRAPPER_VAR_NAMES
            )
            for name, parameter in clean
        )

        # Une vraie déclaration ``*args`` est conservée en fallback texte. En revanche un
        # wrapper runtime pollué ne doit jamais fabriquer /setup [args...] <kwargs>.
        if not declared_has_only_wrapper_vars or clean_looks_polluted:
            output: list[tuple[str, Any]] = []
            for name, parameter in declared:
                lowered = str(name).casefold()
                if lowered in _INTERNAL_CONTEXT_NAMES:
                    continue
                output.append((str(name), clean_map.get(str(name), parameter)))
            # Si la déclaration est propre (ex. setup(self, ctx)), une liste vide est une
            # information valide : la commande n'a réellement aucune option publique.
            if not declared_has_only_wrapper_vars:
                return output

    # Repli prudent : retire uniquement les paramètres d'implémentation manifestes. Les
    # vrais *args d'une commande legacy restent disponibles via l'option texte arguments.
    return [
        (str(name), parameter)
        for name, parameter in clean
        if str(name).casefold() not in _INTERNAL_CONTEXT_NAMES
    ]


def _build_signature(command: commands.Command) -> tuple[inspect.Signature, bool, tuple[str, ...]]:
    params = _effective_params(command)
    unsupported_shape = (
        len(params) > v95.MAX_OPTIONS
        or any(
            getattr(parameter, "kind", None)
            in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            for _name, parameter in params
        )
    )
    interaction_param = inspect.Parameter(
        "interaction",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=discord.Interaction,
    )
    if unsupported_shape:
        argument = inspect.Parameter(
            "arguments",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=str,
            default="",
        )
        return inspect.Signature([interaction_param, argument]), False, ("arguments",)

    output = [interaction_param]
    names: list[str] = []
    native = True
    for raw_name, parameter in params:
        name = v95._safe_name(raw_name, fallback="option").replace("-", "_")
        if name in names:
            name = f"{name[:25]}_{len(names) + 1}"[:32]
        names.append(name)
        annotation = v95._native_annotation(getattr(parameter, "annotation", str))
        if annotation is str and v95._unwrap_optional(getattr(parameter, "annotation", str)) is not str:
            native = False
        required = _is_required(parameter)
        default = inspect.Parameter.empty if required else getattr(parameter, "default", None)
        output.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )
    return inspect.Signature(output), native, tuple(names)


def _argument_text(command: commands.Command, option_names: tuple[str, ...], kwargs: dict) -> str:
    if option_names == ("arguments",):
        return str(kwargs.get("arguments") or "").strip()

    params = _effective_params(command)
    pieces: list[str] = []
    gap = False
    for (original, parameter), exposed in zip(params, option_names):
        value = kwargs.get(exposed)
        required = _is_required(parameter)
        if value is None and not required:
            gap = True
            continue
        if value is None:
            continue
        if gap:
            raise commands.BadArgument(
                f"L'option « {original} » ne peut pas être fournie après une option facultative laissée vide."
            )
        rendered = v95._serialize_value(value)
        if rendered:
            pieces.append(rendered)
    return " ".join(pieces)


def _callback_needs_cog(command: commands.Command) -> bool:
    callback, signature = _callback_declaration(command)
    if inspect.ismethod(callback) and getattr(callback, "__self__", None) is not None:
        return False
    if signature is None:
        return bool(getattr(command, "cog", None))
    params = list(signature.parameters)
    return bool(params and params[0].casefold() in {"self", "cls"})


def _resolve_cog(command: commands.Command, ctx: commands.Context):
    cog = getattr(command, "cog", None)
    if cog is not None:
        return cog

    callback, _signature = _callback_declaration(command)
    qualname = str(getattr(callback, "__qualname__", "") or getattr(command.callback, "__qualname__", ""))
    owner_name = qualname.split(".", 1)[0] if "." in qualname else ""
    bot = getattr(ctx, "bot", None)
    if bot is None:
        return None

    # Priorité au nom de classe présent dans le qualname : c'est stable même lorsqu'un
    # Command a été copié/détaché pendant la construction V98.
    for candidate in getattr(bot, "cogs", {}).values():
        if owner_name and type(candidate).__name__ == owner_name:
            logger.warning(
                "V101: liaison Cog restaurée command=%s cog=%s",
                command.qualified_name,
                owner_name,
            )
            return candidate

    # Repli par identité/code de méthode pour les wrappers qui ont perdu leur qualname.
    target = inspect.unwrap(getattr(command, "callback", None))
    target_code = getattr(target, "__code__", None)
    target_name = getattr(target, "__name__", None)
    for candidate in getattr(bot, "cogs", {}).values():
        if not target_name:
            continue
        declared = getattr(type(candidate), target_name, None)
        declared = getattr(declared, "callback", declared)
        if declared is None:
            continue
        declared = inspect.unwrap(declared)
        if declared is target or (target_code is not None and getattr(declared, "__code__", None) is target_code):
            logger.warning(
                "V101: liaison Cog restaurée par callback command=%s cog=%s",
                command.qualified_name,
                type(candidate).__name__,
            )
            return candidate
    return None


async def _default_for(parameter: Any, ctx: commands.Context):
    getter = getattr(parameter, "get_default", None)
    if getter is not None:
        value = getter(ctx)
        if inspect.isawaitable(value):
            return await value
        return value
    default = getattr(parameter, "default", inspect.Parameter.empty)
    if default is inspect.Parameter.empty:
        raise commands.MissingRequiredArgument(parameter)
    return default


async def _bind_native_arguments(
    command: commands.Command,
    ctx: commands.Context,
    option_names: tuple[str, ...],
    values: dict,
) -> tuple[list, dict]:
    params = _effective_params(command)
    if len(params) != len(option_names):
        raise commands.BadArgument(
            f"Signature slash incohérente ({len(params)} paramètre(s) métier, {len(option_names)} option(s))."
        )

    needs_cog = _callback_needs_cog(command)
    cog = _resolve_cog(command, ctx) if needs_cog else None
    if needs_cog and cog is None:
        raise commands.CommandError(
            f"Impossible de restaurer le Cog de la commande {command.qualified_name}."
        )

    args: list[Any] = [cog, ctx] if needs_cog else [ctx]
    call_kwargs: dict[str, Any] = {}

    for (original_name, parameter), exposed_name in zip(params, option_names):
        if exposed_name in values:
            value = values[exposed_name]
        elif _is_required(parameter):
            raise commands.MissingRequiredArgument(parameter)
        else:
            value = await _default_for(parameter, ctx)

        kind = getattr(parameter, "kind", inspect.Parameter.POSITIONAL_OR_KEYWORD)
        if kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            args.append(value)
        elif kind == inspect.Parameter.KEYWORD_ONLY:
            call_kwargs[original_name] = value
        else:
            raise commands.BadArgument("Cette forme de paramètres doit utiliser le parseur historique.")

    return args, call_kwargs


def _install_ai_timeout() -> None:
    # Le HTTP 200 d'OpenAI peut être reçu avant la fin du corps de réponse. 45 s restait
    # insuffisant pour certaines réponses de code Sol. Discord est déjà defer(), on peut
    # donc laisser une marge raisonnable sans risquer l'expiration de l'interaction.
    old = float(getattr(ai_service, "REQUEST_TIMEOUT_SECONDS", 15.0))
    ai_service.REQUEST_TIMEOUT_SECONDS = max(old, _AI_TIMEOUT_SECONDS)
    # Force la recréation du client afin que son objet timeout reprenne la nouvelle valeur.
    if getattr(ai_service, "_TEXT_CLIENT", None) is not None:
        ai_service._TEXT_CLIENT = None
    logger.info(
        "V101: timeout IA texte porté à %ss (ancien=%ss).",
        ai_service.REQUEST_TIMEOUT_SECONDS,
        old,
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # V101 devient la source de vérité de signature après les gardes V97/V100.
    v95._build_signature = _build_signature
    v95._argument_text = _argument_text
    grouped._bind_native_arguments = _bind_native_arguments

    _install_ai_timeout()
    _INSTALLED = True
    logger.warning(
        "SentriX V101 installé : signatures slash assainies, liaison Cog restaurable et timeout IA renforcé."
    )


__all__ = [
    "install",
    "_effective_params",
    "_build_signature",
    "_bind_native_arguments",
    "_resolve_cog",
]
