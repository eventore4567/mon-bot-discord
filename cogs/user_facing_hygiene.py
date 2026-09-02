"""Hygiène utilisateur et qualité d'exécution globale de SentriX.

Cette couche reste volontairement centrée sur l'expérience membre :
- aucun paramètre interne discord.py (ctx/context/interaction/self/cog) n'est affiché ;
- les erreurs d'arguments courantes indiquent quoi corriger ;
- les cooldowns préfixe, slash et hybrides utilisent le même format lisible ;
- les traces Python restent dans les logs ;
- le correctif historique de +gamble est consolidé ici au lieu d'un module séparé ;
- la qualité runtime V2.5 est installée sans ajouter de commande.

Important : aucune mutation globale de ``command.params`` ou ``command.callback`` n'est
faite ici. La seule exception est le contrat ciblé de +gamble, nécessaire pour réparer une
ancienne signature déjà corrompue ; /gamble n'est pas modifié.
"""
from __future__ import annotations

import logging
import math
import re
import types

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.user-facing-hygiene")

_INTERNAL_PARAMS = {"ctx", "context", "interaction", "self", "cog", "_ctx"}
_INTERNAL_TOKEN_RE = re.compile(
    r"(?:\s+)(?:<|\[|\()(?:ctx|context|interaction|self|cog|_ctx)(?:>|\]|\))",
    re.IGNORECASE,
)
_RAW_TECHNICAL_ERROR_RE = re.compile(
    r"^\s*Erreur technique\s*:\s*[A-Za-z_][A-Za-z0-9_]*(?:\s*\n.*)?$",
    re.IGNORECASE | re.DOTALL,
)
_INT_ERROR_RE = re.compile(r"(?:int|integer|entier|nombre)", re.IGNORECASE)
_AMOUNT_COMMANDS = {
    "gamble", "deposit", "withdraw", "pay", "give-money", "reset-economy",
}
_ID_COMMANDS = {"buy", "unwarn", "case"}


def _is_internal(name: str) -> bool:
    return str(name or "").casefold().strip() in _INTERNAL_PARAMS


def sanitize_usage_text(value: str | None) -> str:
    """Retire uniquement les paramètres techniques d'un texte destiné au membre."""
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _INTERNAL_TOKEN_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def visible_usage(command: commands.Command, prefix: str = "+") -> str:
    """Construit une syntaxe utilisateur sans modifier les paramètres internes."""
    parts = [f"{prefix}{command.qualified_name}"]
    for name, parameter in getattr(command, "clean_params", {}).items():
        if _is_internal(name):
            continue
        display = str(name).replace("_", " ")
        parts.append(f"<{display}>" if getattr(parameter, "required", False) else f"[{display}]")
    return " ".join(parts)


def _command_root_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _repair_help_categories() -> None:
    """Synchronise CATEGORIES et CATEGORY_BY_KEY, notamment pour SentriX V2."""
    try:
        from . import help_complete
    except Exception:
        return

    help_complete.CATEGORY_BY_KEY = {
        category.key: category for category in help_complete.CATEGORIES
    }

    current = help_complete._category_for
    if not getattr(current, "_sentrix_category_map_safe", False):
        def safe_category_for(command):
            try:
                return current(command)
            except KeyError:
                help_complete.CATEGORY_BY_KEY = {
                    category.key: category for category in help_complete.CATEGORIES
                }
                try:
                    return current(command)
                except KeyError:
                    return help_complete.CATEGORY_BY_KEY.get(
                        "other", next(iter(help_complete.CATEGORIES))
                    )

        safe_category_for._sentrix_category_map_safe = True
        safe_category_for._sentrix_original = current
        help_complete._category_for = safe_category_for

    try:
        from . import language_runtime
        language_runtime.CATEGORY_I18N.setdefault("v2", ("SentriX V2", "SentriX V2"))
    except Exception:
        pass

    try:
        from . import help_category_rework
        help_category_rework.COG_DEFAULT_CATEGORY.setdefault("SentriXV2", "v2")
    except Exception:
        pass


def _patch_main_usage_and_cooldown() -> None:
    try:
        import main
    except Exception:
        return

    def command_usage(ctx: commands.Context) -> str | None:
        command = getattr(ctx, "command", None)
        if command is None:
            return None
        prefix = getattr(ctx, "clean_prefix", None) or "+"
        return visible_usage(command, str(prefix))

    command_usage._sentrix_no_internal_params = True
    main.command_usage = command_usage
    main.cooldown_text = _cooldown_text


def _patch_help_renderers() -> None:
    """Nettoie les anciennes couches qui pourraient encore afficher <ctx>/[ctx]."""
    try:
        from . import utility
    except Exception:
        utility = None

    if utility is not None:
        current = utility.format_command_line
        if not getattr(current, "_sentrix_no_internal_params", False):
            def format_command_line(command, prefix: str, slash_names: set):
                return sanitize_usage_text(current(command, prefix, slash_names))

            format_command_line._sentrix_no_internal_params = True
            format_command_line._sentrix_original = current
            utility.format_command_line = format_command_line

    try:
        from . import language_runtime
        current_usage = language_runtime._command_usage
        if not getattr(current_usage, "_sentrix_no_internal_params", False):
            def language_usage(command, prefix: str, language: str):
                return sanitize_usage_text(current_usage(command, prefix, language))

            language_usage._sentrix_no_internal_params = True
            language_usage._sentrix_original = current_usage
            language_runtime._command_usage = language_usage
    except Exception:
        pass

    try:
        from . import help_complete
        current_compact = help_complete._compact_command_line
        if not getattr(current_compact, "_sentrix_no_internal_params", False):
            def compact_line(*args, **kwargs):
                return sanitize_usage_text(current_compact(*args, **kwargs))

            compact_line._sentrix_no_internal_params = True
            compact_line._sentrix_original = current_compact
            help_complete._compact_command_line = compact_line
    except Exception:
        pass

    # V2.3 a importé usage_line directement. On nettoie son global local plutôt que les
    # paramètres réels de la commande.
    try:
        from . import sentrix_accessibility
        current_usage_line = sentrix_accessibility.usage_line
        if not getattr(current_usage_line, "_sentrix_no_internal_params", False):
            def accessibility_usage_line(prefix: str, command_name: str, signature=None):
                return current_usage_line(prefix, command_name, sanitize_usage_text(signature))

            accessibility_usage_line._sentrix_no_internal_params = True
            accessibility_usage_line._sentrix_original = current_usage_line
            sentrix_accessibility.usage_line = accessibility_usage_line
    except Exception:
        pass


def _patch_raw_technical_errors() -> None:
    """Les traces Python restent dans les logs, jamais dans Discord."""
    current = embeds.error
    if getattr(current, "_sentrix_hide_raw_technical_error", False):
        return

    def safe_error(description: str, title: str = "Action impossible"):
        text = str(description or "")
        if _RAW_TECHNICAL_ERROR_RE.match(text):
            description = (
                "Cette commande a rencontré un problème technique. "
                "Réessaie dans un instant. Si le problème continue, préviens le staff."
            )
        return current(description, title=title)

    safe_error._sentrix_hide_raw_technical_error = True
    safe_error._sentrix_original = current
    embeds.error = safe_error


def _cooldown_text(seconds: float) -> str:
    """Durée courte et lisible : 2 j 4 h, 3 h 12 min, 1 min 5 s, 8 s."""
    total = max(1, int(math.ceil(float(seconds))))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} j")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return " ".join(parts[:2] if days else parts[:3])


def _cooldown_retry_after(error) -> float | None:
    candidates = [error, getattr(error, "original", None)]
    for candidate in candidates:
        if isinstance(candidate, (commands.CommandOnCooldown, discord.app_commands.CommandOnCooldown)):
            try:
                return float(candidate.retry_after)
            except (TypeError, ValueError):
                return 1.0
    return None


async def _send_slash_cooldown(interaction: discord.Interaction, retry_after: float) -> None:
    embed = embeds.warning(
        f'Vous pourrez réutiliser cette commande dans **{_cooldown_text(retry_after)}**.',
        title="Cooldown actif",
    )
    try:
        if interaction.response.is_done():
            await panels.envoyer(interaction.followup, panels.depuis_embed(embed), ephemere=True)
        else:
            await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)
    except (discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer le cooldown slash.", exc_info=True)


def _patch_slash_error_ux(bot: commands.Bot) -> None:
    """Cooldowns slash/hybrides et erreurs de conversion lisibles."""
    current = bot.tree.on_error
    if getattr(current, "_sentrix_v25_error_ux", False):
        return

    async def slash_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        retry_after = _cooldown_retry_after(error)
        if retry_after is not None:
            return await _send_slash_cooldown(interaction, retry_after)

        original = getattr(error, "original", error)
        if isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
            embed = embeds.warning(
                "Une valeur n'est pas valide. Vérifiez le nombre, le membre, le rôle ou le salon sélectionné.",
                title="Valeur invalide",
            )
            try:
                if interaction.response.is_done():
                    return await panels.envoyer(interaction.followup, panels.depuis_embed(embed), ephemere=True)
                return await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)
            except (discord.HTTPException, discord.InteractionResponded):
                return None

        if isinstance(original, commands.CommandOnCooldown):
            return await _send_slash_cooldown(interaction, original.retry_after)
        return await current(interaction, error)

    slash_error._sentrix_v25_error_ux = True
    slash_error._sentrix_original = current
    bot.tree.on_error = slash_error


def _patch_prefix_error_ux(bot: commands.Bot) -> None:
    """Donne une erreur précise avant le handler générique de V2.3/main.py."""
    current = bot.on_command_error
    if getattr(current, "_sentrix_v25_error_ux", False):
        return

    async def prefix_error(_bot, ctx: commands.Context, error: commands.CommandError):
        original = getattr(error, "original", error)

        if isinstance(original, commands.CommandOnCooldown):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Vous pourrez réutiliser cette commande dans **{_cooldown_text(original.retry_after)}**.', title='Cooldown actif')))

        if isinstance(original, commands.MaxConcurrencyReached):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Une partie ou une action identique est déjà en cours. Terminez-la avant de recommencer.', title='Action déjà en cours')))

        # Les convertisseurs spécialisés savent déjà produire de meilleurs messages dans
        # les handlers existants : ne pas les réduire à un simple BadArgument générique.
        specialized = tuple(
            cls for cls in (
                getattr(commands, "MemberNotFound", None),
                getattr(commands, "UserNotFound", None),
                getattr(commands, "RoleNotFound", None),
                getattr(commands, "ChannelNotFound", None),
            ) if isinstance(cls, type)
        )
        if specialized and isinstance(original, specialized):
            return await current(ctx, error)

        if isinstance(original, commands.BadArgument):
            root_name = _command_root_name(ctx)
            usage = visible_usage(ctx.command, str(getattr(ctx, "clean_prefix", None) or "+")) if ctx.command else None
            raw = str(original)

            if root_name in _AMOUNT_COMMANDS or _INT_ERROR_RE.search(raw):
                if root_name in _ID_COMMANDS:
                    description = "L'identifiant doit être un nombre entier positif."
                elif root_name == "gamble":
                    description = "Le montant doit être un nombre entier positif, par exemple `10` ou `500`."
                else:
                    description = "Le montant indiqué n'est pas valide. Utilise un nombre positif."
                if usage:
                    description += f"\nUtilise : `{usage}`"
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(description, title='Montant invalide')))

            if root_name in _ID_COMMANDS:
                description = "L'identifiant doit être un nombre entier valide."
                if usage:
                    description += f"\nUtilise : `{usage}`"
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(description, title='Identifiant invalide')))

        return await current(ctx, error)

    prefix_error._sentrix_v25_error_ux = True
    prefix_error._sentrix_original = current
    bot.on_command_error = types.MethodType(prefix_error, bot)


async def _gamble_signature_probe(ctx: commands.Context, montant: int):
    return None


def _repair_gamble_parser(bot: commands.Bot) -> None:
    """Contrat ciblé +gamble : un seul argument utilisateur ``montant: int``.

    Cette réparation est gardée ici parce qu'une ancienne couche runtime a déjà corrompu
    ce contrat en production. Elle ne touche pas à l'Application Command /gamble.
    """
    command = bot.get_command("gamble")
    if command is None:
        return

    actual = tuple(str(name) for name in getattr(command, "clean_params", {}))
    annotation = getattr(getattr(command, "clean_params", {}).get("montant"), "annotation", None)
    if actual == ("montant",) and annotation is int:
        command.usage = "<montant>"
        command._sentrix_gamble_contract_fixed = True
        return

    probe = commands.Command(_gamble_signature_probe, name="_sentrix_gamble_signature_probe")
    command.params = probe.params.copy()
    command.usage = "<montant>"
    command._sentrix_gamble_contract_fixed = True
    logger.warning("Contrat du parseur +gamble réparé : %r -> ('montant',).", actual)


def _install_runtime_quality(bot: commands.Bot) -> None:
    try:
        from . import runtime_quality_v25
        runtime_quality_v25.install(bot)
    except Exception:
        logger.exception("Impossible d'installer la qualité runtime V2.5.")


def apply(bot: commands.Bot) -> None:
    _repair_help_categories()
    _patch_main_usage_and_cooldown()
    _patch_help_renderers()
    _patch_raw_technical_errors()
    _patch_slash_error_ux(bot)
    _patch_prefix_error_ux(bot)
    _repair_gamble_parser(bot)
    _install_runtime_quality(bot)
    # Les modules de qualité peuvent remplacer des callbacks pendant cette passe ; leur
    # cache de paramètres doit être nettoyé après, sinon ``ctx`` réapparaît dans +help.
    from .command_runtime_hardening_v18 import repair_wrapped_signatures
    repair_wrapped_signatures(bot)
    bot._sentrix_user_facing_hygiene = True


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_user_facing_hygiene_listener", False):
        apply(bot)
        return

    apply(bot)

    async def reapply_on_ready():
        # Les dernières couches runtime peuvent être installées après Stats.
        apply(bot)

    bot.add_listener(reapply_on_ready, "on_ready")
    bot._sentrix_user_facing_hygiene_listener = True
    logger.info(
        "UX globale active : ctx masqué, erreurs précises, cooldowns cohérents et qualité V2.5; 0 nouvelle commande."
    )
