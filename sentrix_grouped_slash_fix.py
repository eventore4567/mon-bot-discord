"""Correctif central des sous-commandes slash groupées SentriX.

La surface V98 expose les commandes historiques ``+`` sous forme de commandes slash
nommées. V95 reconstruisait ensuite une ligne de commande texte puis la reparsait. Cette
conversion faisait perdre des valeurs déjà transformées par Discord (Attachment, Member,
Role, salons) et fragilisait les paramètres keyword-only tels que ``*, question``.

Ce module remplace uniquement le transport V95 au démarrage :
- les commandes dont les options sont nativement représentables sont invoquées avec les
  objets déjà transformés par app_commands ;
- les convertisseurs historiques/non natifs et les vrais sous-groupes prefix gardent le
  parseur texte existant afin de ne pas modifier leur sémantique ;
- toute erreur provenant de cette passerelle slash devient une seule phrase texte courte,
  sans embed d'erreur ni seconde réponse après le defer Discord.
"""
from __future__ import annotations

import asyncio
import inspect
import logging

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView

import sentrix_v95_runtime as v95

logger = logging.getLogger("bot.grouped-slash-fix")

_INSTALLED = False


def _supports_direct_binding(command: commands.Command, option_names: tuple[str, ...]) -> bool:
    """Vrai si Discord a déjà produit exactement les valeurs attendues par le callback.

    Les sous-commandes d'un vrai ``commands.Group`` historique restent sur le chemin
    legacy afin de conserver les callbacks/checks/hooks du parent prefix. En revanche,
    une sous-commande ``HybridCommand`` sous ``HybridGroup`` est déjà une vraie route slash
    Discord : la reparsage par ``Group.invoke`` peut perdre la liaison du Cog et appeler le
    callback sans ``self``/``ctx``. Ces enfants hybrides utilisent donc le binding natif.
    """
    if option_names == ("arguments",):
        return False

    root_parent = command.root_parent
    if root_parent is not None and not isinstance(root_parent, commands.HybridGroup):
        return False

    try:
        _signature, native, generated_names = v95._build_signature(command)
    except Exception:
        return False
    return bool(native and tuple(generated_names) == tuple(option_names))


async def _default_for(parameter, ctx: commands.Context):
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
    """Reconstruit ``ctx.args``/``ctx.kwargs`` sans reconvertir en chaîne de caractères."""
    params = list(command.clean_params.items())
    if len(params) != len(option_names):
        raise commands.BadArgument("La signature slash ne correspond plus à la commande d'origine.")

    args: list = [ctx] if command.cog is None else [command.cog, ctx]
    kwargs: dict = {}

    for (original_name, parameter), exposed_name in zip(params, option_names):
        if exposed_name in values:
            value = values[exposed_name]
        elif bool(getattr(parameter, "required", False)):
            raise commands.MissingRequiredArgument(parameter)
        else:
            value = await _default_for(parameter, ctx)

        kind = parameter.kind
        if kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            args.append(value)
        elif kind == inspect.Parameter.KEYWORD_ONLY:
            # Point clé du correctif : ``*, question`` reste réellement un kwarg et ne
            # repasse plus par StringView/shlex.
            kwargs[original_name] = value
        else:
            # Les VAR_POSITIONAL/VAR_KEYWORD ne devraient jamais arriver ici : V95 les
            # expose via l'option texte ``arguments``. On échoue fermé si la signature a
            # changé entre la construction et l'invocation.
            raise commands.BadArgument("Cette forme de paramètres doit utiliser le parseur historique.")

    return args, kwargs


# Filet de sécurité pour la famille de commandes de sanction : un rapport utilisateur a
# montré un +unmute dont le dossier journalisé correspondait à +mute (mauvaise action
# potentiellement appliquée à un membre réel). Le nom de fonction Python de CES commandes
# précises est toujours identique à leur nom de commande (contrairement à des commandes
# comme bot-status/system_status, qu'on ne peut donc pas vérifier de la même façon sans
# faux positifs) — assez fiable pour détecter, ici, un command.callback qui pointerait
# vers une autre fonction que celle attendue, quelle qu'en soit la cause exacte. Échoue
# fermé (refuse d'exécuter) plutôt que de risquer la mauvaise sanction.
_SANCTION_COMMAND_NAMES = frozenset({"ban", "tempban", "unban", "kick", "mute", "unmute", "warn"})


def _sanction_callback_mismatch(command: commands.Command) -> str | None:
    name = str(getattr(command, "name", "") or "").casefold()
    if name not in _SANCTION_COMMAND_NAMES:
        return None
    callback = getattr(command, "callback", None)
    if callback is None:
        return None
    try:
        declared = inspect.unwrap(callback)
    except (TypeError, ValueError):
        declared = callback
    declared_name = str(getattr(declared, "__name__", "") or "").casefold()
    if declared_name and declared_name != name:
        return (
            f"Sécurité : '{command.qualified_name}' devait exécuter la fonction '{name}' "
            f"mais son callback pointe vers '{declared_name}'. Commande bloquée plutôt que "
            f"de risquer d'appliquer la mauvaise sanction."
        )
    return None


async def _make_context(bot: commands.Bot, interaction: discord.Interaction) -> commands.Context:
    ctx = await commands.Context.from_interaction(interaction)
    # SentriX ajoute des helpers à son Context. On conserve la même compatibilité que V95.
    try:
        sentrix_context = getattr(__import__("main"), "SentriXContext", None)
        if sentrix_context is not None and not isinstance(ctx, sentrix_context):
            ctx.__class__ = sentrix_context
    except Exception:
        pass
    return ctx


async def _invoke_native(
    bot: commands.Bot,
    command: commands.Command,
    ctx: commands.Context,
    option_names: tuple[str, ...],
    values: dict,
) -> None:
    """Exécute une commande prefix/hybride avec le cycle de vie commands.py, sans parser."""
    mismatch = _sanction_callback_mismatch(command)
    if mismatch:
        logger.critical(mismatch)
        raise commands.CommandError(mismatch)

    ctx.command = command
    ctx.invoked_with = command.name
    ctx.invoked_parents = []
    ctx.invoked_subcommand = None
    ctx.subcommand_passed = None

    bot.dispatch("command", ctx)

    if not await command.can_run(ctx):
        raise commands.CheckFailure(
            f"The check functions for command {command.qualified_name} failed."
        )

    args, kwargs = await _bind_native_arguments(command, ctx, option_names, values)
    ctx.args = args
    ctx.kwargs = kwargs

    acquired = False
    concurrency = getattr(command, "_max_concurrency", None)
    if concurrency is not None:
        await concurrency.acquire(ctx)
        acquired = True

    hooks_started = False
    try:
        # Les valeurs ont déjà été parsées et transformées par app_commands. Le cooldown
        # est donc préparé au même endroit logique que Command.prepare, sans second parse.
        command._prepare_cooldowns(ctx)
        await command.call_before_hooks(ctx)
        hooks_started = True

        try:
            await command.callback(*ctx.args, **ctx.kwargs)
        except commands.CommandError:
            ctx.command_failed = True
            raise
        except asyncio.CancelledError:
            ctx.command_failed = True
            return
        except Exception as exc:
            ctx.command_failed = True
            raise commands.CommandInvokeError(exc) from exc
    finally:
        # ``hooked_wrapped_callback`` appelle les after-hooks même si le callback échoue.
        # En revanche, si la préparation elle-même échoue, Command.prepare ne les appelle
        # pas : ``hooks_started`` conserve cette distinction.
        if acquired:
            try:
                await concurrency.release(ctx.message)
            except Exception:
                logger.exception("Impossible de libérer la concurrence de %s", command.qualified_name)
        if hooks_started:
            await command.call_after_hooks(ctx)

    if not ctx.command_failed:
        bot.dispatch("command_completion", ctx)


async def _invoke_legacy(
    bot: commands.Bot,
    command: commands.Command,
    ctx: commands.Context,
    option_names: tuple[str, ...],
    values: dict,
) -> None:
    """Chemin V95 conservé pour convertisseurs non natifs et groupes prefix réels."""
    root = command.root_parent or command
    mismatch = _sanction_callback_mismatch(root)
    if mismatch:
        logger.critical(mismatch)
        raise commands.CommandError(mismatch)

    path = str(command.qualified_name).split()[1:] if command.root_parent is not None else []
    arguments = v95._argument_text(command, option_names, values)
    source = " ".join([*path, arguments]).strip()

    ctx.view = StringView(source)
    ctx.command = root
    ctx.invoked_with = root.name
    ctx.invoked_parents = []
    ctx.invoked_subcommand = None
    ctx.subcommand_passed = None

    bot.dispatch("command", ctx)
    await root.invoke(ctx)
    if not ctx.command_failed:
        bot.dispatch("command_completion", ctx)


def _unwrap_error(error: BaseException) -> BaseException:
    current: BaseException = error
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        original = getattr(current, "original", None)
        if not isinstance(original, BaseException):
            break
        current = original
    return current


def _short_error(error: BaseException) -> str:
    """Message volontairement court : une phrase, aucun embed rouge."""
    raw = _unwrap_error(error)

    if isinstance(error, commands.CommandOnCooldown):
        seconds = max(1, int(round(error.retry_after)))
        return f"Cette commande est en cooldown. Réessaie dans {seconds} s."
    if isinstance(error, commands.MissingRequiredArgument):
        name = getattr(getattr(error, "param", None), "name", "option")
        return f"Il manque l’option obligatoire « {name} »."
    if isinstance(error, commands.BotMissingPermissions):
        return "Il me manque une permission Discord pour faire ça."
    if isinstance(error, commands.MissingPermissions):
        return "Tu n’as pas les permissions nécessaires pour cette commande."
    if isinstance(error, (commands.NotOwner, commands.CheckFailure)):
        return "Tu n’as pas la permission d’utiliser cette commande."
    if isinstance(error, commands.NoPrivateMessage):
        return "Cette commande doit être utilisée dans un serveur."
    if isinstance(error, commands.PrivateMessageOnly):
        return "Cette commande doit être utilisée en message privé."
    if isinstance(error, commands.MaxConcurrencyReached):
        return "Cette commande est déjà en cours. Réessaie dans un instant."
    if isinstance(error, (commands.BadArgument, commands.TooManyArguments)):
        return "Une des options fournies est invalide."
    if isinstance(raw, discord.Forbidden):
        return "Discord refuse cette action à cause d’une permission manquante."
    if isinstance(raw, discord.HTTPException):
        return "Discord a refusé la requête. Réessaie dans un instant."
    return "Une erreur est survenue pendant la commande. Réessaie."


async def _send_short_error(interaction: discord.Interaction, error: BaseException) -> None:
    text = _short_error(error)[:1900]
    try:
        if interaction.response.is_done():
            # Après ``defer(thinking=True)``, éditer la réponse originale retire l'état
            # d'attente. On ne crée donc pas un deuxième message d'erreur.
            await interaction.edit_original_response(content=text, embeds=[], view=None)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        return
    except (discord.NotFound, discord.HTTPException):
        pass

    # Dernier recours si l'interaction a déjà une réponse non éditable. On n'utilise
    # jamais d'embed et on évite de lever une seconde exception vers CommandTree.
    try:
        await interaction.followup.send(text, ephemeral=True)
    except (discord.NotFound, discord.HTTPException):
        logger.warning("Impossible d'envoyer l'erreur slash compacte : interaction expirée.")


async def _invoke_original_fixed(
    bot: commands.Bot,
    command: commands.Command,
    interaction: discord.Interaction,
    option_names: tuple[str, ...],
    kwargs: dict,
) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)

    ctx = await _make_context(bot, interaction)
    try:
        if _supports_direct_binding(command, option_names):
            await _invoke_native(bot, command, ctx, option_names, kwargs)
        else:
            await _invoke_legacy(bot, command, ctx, option_names, kwargs)
    except commands.CommandError as exc:
        ctx.command_failed = True
        logger.warning(
            "Erreur slash groupée %s: %s: %s",
            command.qualified_name,
            exc.__class__.__name__,
            exc,
        )
        await _send_short_error(interaction, exc)
    except Exception as exc:
        ctx.command_failed = True
        logger.exception("Erreur inattendue slash groupée %s", command.qualified_name)
        await _send_short_error(interaction, exc)


def install() -> None:
    """Installe le correctif une seule fois avant la construction/synchronisation V98."""
    global _INSTALLED
    if _INSTALLED or getattr(v95._invoke_original, "_sentrix_grouped_fix", False):
        _INSTALLED = True
        return

    _invoke_original_fixed._sentrix_grouped_fix = True
    _invoke_original_fixed._sentrix_original = v95._invoke_original
    v95._invoke_original = _invoke_original_fixed
    _INSTALLED = True
    logger.info("Correctif slash groupé : binding natif et erreurs compactes installés.")


__all__ = [
    "install",
    "_bind_native_arguments",
    "_short_error",
    "_supports_direct_binding",
]
