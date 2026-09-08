"""SentriX V101 — réparation centrale et défensive des commandes slash.

V101 traite les défauts observés en production sans patcher les commandes métier une par une :
- les wrappers internes ne peuvent plus exposer ``ctx``, ``*args`` ou ``**kwargs`` comme
  options Discord ;
- une Command de Cog détachée ne récupère son Cog que si la correspondance est unique ;
- les valeurs Discord déjà typées restent transportées nativement ;
- les demandes IA de code disposent d'un délai raisonnable après defer ;
- une trace runtime minimale permet de diagnostiquer les commandes restantes sans journaliser
  le contenu utilisateur, les tokens, les paramètres SQL ni les prompts IA.
"""
from __future__ import annotations

import inspect
import logging
import shlex
import time
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
    """Retourne la déclaration de callback la plus proche et sa signature."""
    callback = getattr(command, "callback", None)
    if callback is None:
        return None, None
    try:
        candidate = inspect.unwrap(callback)
    except (TypeError, ValueError):
        candidate = callback

    # Si le Cog est encore attaché, la méthode déclarée sur sa classe est plus fiable qu'un
    # wrapper d'instance pour découvrir la signature publique.
    cog = getattr(command, "cog", None)
    method_name = getattr(candidate, "__name__", None) or getattr(callback, "__name__", None)
    if cog is not None and method_name:
        declared = getattr(type(cog), method_name, None)
        if declared is not None:
            declared = getattr(declared, "callback", declared)
            try:
                candidate = inspect.unwrap(declared)
            except (TypeError, ValueError):
                candidate = declared

    try:
        return candidate, inspect.signature(candidate)
    except (TypeError, ValueError):
        return candidate, None


def _declared_user_params(command: commands.Command) -> list[tuple[str, Any]] | None:
    _callback, signature = _callback_declaration(command)
    if signature is None:
        return None

    params = list(signature.parameters.items())
    if params and params[0][0].casefold() in {"self", "cls"}:
        params.pop(0)
    if params and params[0][0].casefold() in {"ctx", "context"}:
        params.pop(0)
    return params


def _is_opaque_runtime_wrapper(command: commands.Command) -> bool:
    """Détecte un décorateur non transparent de forme ``(*args, **kwargs)``.

    Une vraie commande legacy ``(ctx, *args)`` n'est PAS considérée opaque : la présence du
    contexte explicite prouve que les varargs appartiennent à la déclaration métier.
    """
    _callback, signature = _callback_declaration(command)
    if signature is None:
        return False
    params = list(signature.parameters.items())
    if params and params[0][0].casefold() in {"self", "cls"}:
        params.pop(0)
    if params and params[0][0].casefold() in {"ctx", "context"}:
        return False
    return bool(params) and all(
        parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        and str(name).casefold() in _WRAPPER_VAR_NAMES
        for name, parameter in params
    )


def _effective_params(command: commands.Command) -> list[tuple[str, Any]]:
    """Paramètres réellement destinés à l'utilisateur, jamais ceux du wrapper runtime."""
    try:
        clean = list(command.clean_params.items())
    except Exception:
        clean = []

    clean_map = {str(name): parameter for name, parameter in clean}
    declared = _declared_user_params(command)

    if declared is not None:
        declared_has_only_wrapper_vars = bool(declared) and all(
            parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            and str(name).casefold() in _WRAPPER_VAR_NAMES
            for name, parameter in declared
        )
        clean_has_internal_context = any(
            str(name).casefold() in _INTERNAL_CONTEXT_NAMES for name, _parameter in clean
        )
        clean_has_wrapper_vars = any(
            getattr(parameter, "kind", None)
            in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            and str(name).casefold() in _WRAPPER_VAR_NAMES
            for name, parameter in clean
        )

        # Cas exact reproduit par /setup : un wrapper opaque (*args, **kwargs) a contaminé
        # clean_params avec ctx/args/kwargs. Exposer ces noms serait à la fois faux et une
        # fuite d'implémentation. On échoue fermé : zéro option publique.
        if (
            declared_has_only_wrapper_vars
            and _is_opaque_runtime_wrapper(command)
            and (clean_has_internal_context or clean_has_wrapper_vars)
        ):
            logger.warning(
                "V101: paramètres internes d'un wrapper opaque masqués command=%s",
                getattr(command, "qualified_name", "unknown"),
            )
            return []

        # Une déclaration exploitable est la source d'autorité sur les NOMS ; les Parameter
        # discord.py restent prioritaires pour converters/defaults lorsqu'ils correspondent.
        if not declared_has_only_wrapper_vars:
            output: list[tuple[str, Any]] = []
            for name, parameter in declared:
                lowered = str(name).casefold()
                if lowered in _INTERNAL_CONTEXT_NAMES:
                    continue
                output.append((str(name), clean_map.get(str(name), parameter)))
            return output

    # Repli prudent : masque toujours le contexte interne. Les vrais varargs legacy restent
    # disponibles via l'option texte ``arguments``.
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


def _declared_method(candidate: Any, method_name: str):
    if not method_name:
        return None
    declared = getattr(type(candidate), method_name, None)
    declared = getattr(declared, "callback", declared)
    if declared is None:
        return None
    try:
        return inspect.unwrap(declared)
    except (TypeError, ValueError):
        return declared


def _raise_ambiguous_cog(command: commands.Command, candidates: list[Any]) -> None:
    names = sorted({type(item).__name__ for item in candidates})
    logger.error(
        "V101: liaison Cog ambiguë refusée command=%s candidates=%s count=%s",
        getattr(command, "qualified_name", "unknown"),
        names,
        len(candidates),
    )
    raise commands.CommandError(
        f"Liaison Cog ambiguë pour {getattr(command, 'qualified_name', 'commande')}."
    )


def _resolve_cog(command: commands.Command, ctx: commands.Context):
    """Restaure un Cog détaché uniquement si la correspondance est unique.

    Ordre de confiance : identité/code du callback > classe+méthode unique. Aucun premier
    résultat arbitraire n'est accepté.
    """
    cog = getattr(command, "cog", None)
    if cog is not None:
        return cog

    callback, _signature = _callback_declaration(command)
    bot = getattr(ctx, "bot", None)
    if bot is None:
        return None
    cogs = list(getattr(bot, "cogs", {}).values())
    if not cogs:
        return None

    try:
        target = inspect.unwrap(getattr(command, "callback", None))
    except (TypeError, ValueError):
        target = getattr(command, "callback", None)
    target_code = getattr(target, "__code__", None)
    target_name = getattr(target, "__name__", None) or getattr(callback, "__name__", None)

    exact: list[Any] = []
    if target_name:
        for candidate in cogs:
            declared = _declared_method(candidate, target_name)
            if declared is None:
                continue
            if declared is target or (
                target_code is not None and getattr(declared, "__code__", None) is target_code
            ):
                exact.append(candidate)
    if len(exact) == 1:
        chosen = exact[0]
        logger.warning(
            "V101: liaison Cog restaurée par callback command=%s cog=%s",
            getattr(command, "qualified_name", "unknown"),
            type(chosen).__name__,
        )
        return chosen
    if len(exact) > 1:
        _raise_ambiguous_cog(command, exact)

    # Repli moins fort : qualname + méthode, uniquement si un seul Cog enregistré convient.
    qualname = str(
        getattr(callback, "__qualname__", "")
        or getattr(getattr(command, "callback", None), "__qualname__", "")
    )
    qual_parts = [part for part in qualname.split(".") if part and part != "<locals>"]
    owner_name = qual_parts[-2] if len(qual_parts) >= 2 else ""
    class_matches = [
        candidate
        for candidate in cogs
        if owner_name
        and type(candidate).__name__ == owner_name
        and (not target_name or _declared_method(candidate, target_name) is not None)
    ]
    if len(class_matches) == 1:
        chosen = class_matches[0]
        logger.warning(
            "V101: liaison Cog restaurée par classe unique command=%s cog=%s",
            getattr(command, "qualified_name", "unknown"),
            type(chosen).__name__,
        )
        return chosen
    if len(class_matches) > 1:
        _raise_ambiguous_cog(command, class_matches)
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
    old = float(getattr(ai_service, "REQUEST_TIMEOUT_SECONDS", 15.0))
    ai_service.REQUEST_TIMEOUT_SECONDS = max(old, _AI_TIMEOUT_SECONDS)
    if getattr(ai_service, "_TEXT_CLIENT", None) is not None:
        ai_service._TEXT_CLIENT = None
    logger.info(
        "V101: timeout IA texte porté à %ss (ancien=%ss).",
        ai_service.REQUEST_TIMEOUT_SECONDS,
        old,
    )


def _option_type_summary(values: dict) -> dict[str, str]:
    """Résumé de diagnostic sans aucune valeur utilisateur."""
    return {
        str(name)[:64]: type(value).__name__
        for name, value in values.items()
    }


def _install_runtime_trace() -> None:
    current = v95._invoke_original
    if getattr(current, "_sentrix_v101_trace", False):
        return

    async def traced_invoke(bot, command, interaction, option_names, kwargs):
        trace_id = str(getattr(interaction, "id", "unknown"))
        command_name = str(getattr(command, "qualified_name", "unknown"))
        started = time.monotonic()
        logger.info(
            "V101 slash trace id=%s command=%s phase=start options=%s option_types=%s",
            trace_id,
            command_name,
            tuple(str(name) for name in option_names),
            _option_type_summary(kwargs),
        )
        try:
            return await current(bot, command, interaction, option_names, kwargs)
        except BaseException:
            logger.exception(
                "V101 slash trace id=%s command=%s phase=raised",
                trace_id,
                command_name,
            )
            raise
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "V101 slash trace id=%s command=%s phase=end duration_ms=%s",
                trace_id,
                command_name,
                duration_ms,
            )

    traced_invoke._sentrix_v101_trace = True
    traced_invoke._sentrix_original = current
    if getattr(current, "_sentrix_grouped_fix", False):
        traced_invoke._sentrix_grouped_fix = True
    v95._invoke_original = traced_invoke


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    v95._build_signature = _build_signature
    v95._argument_text = _argument_text
    grouped._bind_native_arguments = _bind_native_arguments

    _install_ai_timeout()
    _install_runtime_trace()
    _INSTALLED = True
    logger.warning(
        "SentriX V101 installé : signatures assainies, Cog fail-closed, timeout IA renforcé et traces privées actives."
    )


__all__ = [
    "install",
    "_effective_params",
    "_build_signature",
    "_bind_native_arguments",
    "_resolve_cog",
    "_is_opaque_runtime_wrapper",
    "_option_type_summary",
]
