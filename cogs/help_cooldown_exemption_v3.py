"""SentriX V3 — aide toujours accessible et signature utilisateur propre.

`help` est une commande de navigation, pas une action métier coûteuse. Elle ne doit donc
pas consommer le quota global ni être refusée par l'anti-double-exécution V41.

Cette couche protège aussi l'interface V3 contre les composants Discord fragiles et
supprime explicitement des paramètres utilisateur tous les arguments techniques internes
(`ctx`, `context`, `interaction`, `self`, `cog`). Ainsi +help ne peut plus demander à un
membre d'écrire un argument Python interne.
"""
from __future__ import annotations

import inspect
import logging
from types import MethodType

import discord
from discord.ext import commands

logger = logging.getLogger("bot.help-v3-compat")
_HELP_ROOTS = frozenset({"help"})
_TECHNICAL_PARAMS = frozenset({"ctx", "context", "interaction", "self", "cog"})


def _root_name(command) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or getattr(command, "name", "") or "").strip().casefold()


def _help_context(ctx: commands.Context) -> bool:
    return _root_name(getattr(ctx, "command", None)) in _HELP_ROOTS


def _sanitize_help_command_params(help_command: commands.Command | None) -> None:
    """Retire les paramètres Python internes de la syntaxe visible et du parseur préfixe."""
    if help_command is None:
        return
    params = getattr(help_command, "params", None)
    if isinstance(params, dict):
        for name in list(params):
            if str(name).casefold() in _TECHNICAL_PARAMS:
                params.pop(name, None)
    # Le seul argument utilisateur accepté est le nom optionnel d'une commande.
    help_command.usage = "[commande]"


def _patch_global_prefix_cooldown(bot: commands.Bot) -> None:
    original = getattr(bot, "global_cooldown_check", None)
    if not callable(original) or getattr(original, "_sentrix_help_exempt_v3", False):
        return

    async def global_cooldown_with_help_exemption(self, ctx: commands.Context) -> bool:
        if _help_context(ctx):
            return True
        result = original(ctx)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    global_cooldown_with_help_exemption._sentrix_help_exempt_v3 = True
    patched = MethodType(global_cooldown_with_help_exemption, bot)

    checks = list(getattr(bot, "_checks", ()) or ())
    was_registered = any(check == original for check in checks)
    if was_registered:
        try:
            bot.remove_check(original)
        except Exception:
            pass

    bot.global_cooldown_check = patched
    if was_registered:
        bot.add_check(patched)


def _patch_v41_guards() -> None:
    from . import command_hardening_v41 as hardening

    if getattr(hardening, "_sentrix_help_exempt_v3", False):
        return

    original_duplicate_retry = hardening._duplicate_retry
    original_slash_rate_retry = hardening._slash_rate_retry
    original_acquire = hardening._acquire

    def duplicate_retry(bot, *, source: str, user_id: int, root: str) -> float:
        if str(root or "").casefold() in _HELP_ROOTS:
            return 0.0
        return original_duplicate_retry(bot, source=source, user_id=user_id, root=root)

    def slash_rate_retry(bot, user_id: int, root: str) -> float:
        if str(root or "").casefold() in _HELP_ROOTS:
            return 0.0
        return original_slash_rate_retry(bot, user_id, root)

    def acquire(bot, *, token_id: int, user_id: int, guild_id: int | None, root: str, slash: bool):
        if str(root or "").casefold() in _HELP_ROOTS:
            return None
        return original_acquire(
            bot,
            token_id=token_id,
            user_id=user_id,
            guild_id=guild_id,
            root=root,
            slash=slash,
        )

    hardening._duplicate_retry = duplicate_retry
    hardening._slash_rate_retry = slash_rate_retry
    hardening._acquire = acquire
    hardening._sentrix_help_exempt_v3 = True


def _sanitize_view(view: discord.ui.View) -> None:
    """Retire les emojis des composants V3 uniquement, pas ceux des embeds."""
    for item in list(getattr(view, "children", ()) or ()):
        if isinstance(item, discord.ui.Button):
            item.emoji = None
        elif isinstance(item, discord.ui.Select):
            for option in item.options:
                option.emoji = None


def _patch_v3_components(bot: commands.Bot) -> None:
    try:
        from . import help_clean_style as clean
        from . import sentrix_v3_ux as v3
    except Exception:
        return

    help_command = bot.get_command("help")
    if help_command is None:
        return

    # Important : même si une autre couche a recalculé la signature du callback,
    # les arguments techniques ne doivent jamais devenir des arguments utilisateur.
    _sanitize_help_command_params(help_command)

    if not getattr(v3.V3Select, "_sentrix_component_compat_v3", False):
        original_select_init = v3.V3Select.__init__

        def select_init(self, *args, **kwargs):
            original_select_init(self, *args, **kwargs)
            for option in self.options:
                option.emoji = None

        v3.V3Select.__init__ = select_init
        v3.V3Select._sentrix_component_compat_v3 = True

    for view_cls in (v3.V3HomeView, v3.V3PagesView):
        if getattr(view_cls, "_sentrix_component_compat_v3", False):
            continue
        original_init = view_cls.__init__

        def make_init(previous):
            def compatible_init(self, *args, **kwargs):
                previous(self, *args, **kwargs)
                _sanitize_view(self)
            return compatible_init

        view_cls.__init__ = make_init(original_init)
        view_cls._sentrix_component_compat_v3 = True

    clean.CleanHelpSelect = v3.V3Select
    clean.CleanHelpHomeView = v3.V3HomeView
    clean.CleanHelpPagesView = v3.V3PagesView

    current_callback = help_command.callback
    if not getattr(current_callback, "_sentrix_safe_help_v3", False):
        async def safe_help_callback(cog, ctx: commands.Context, *, commande: str | None = None):
            try:
                result = current_callback(cog, ctx, commande=commande)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except discord.HTTPException:
                logger.warning("Discord a refusé les composants de +help ; fallback embed seul.", exc_info=True)

                language = "fr"
                try:
                    from . import language_runtime
                    language = await language_runtime.get_language(
                        ctx.bot, ctx.guild.id if ctx.guild else None
                    )
                except Exception:
                    pass

                prefix = "+"
                try:
                    conf = await ctx.bot.db.get_guild_config(ctx.guild.id) if ctx.guild else None
                    prefix = conf["prefix"] if conf and conf["prefix"] else "+"
                except Exception:
                    pass

                is_staff = False
                try:
                    is_staff = bool(await cog._user_is_staff(ctx))
                except Exception:
                    pass

                embed = v3._home_embed(ctx.bot, ctx.guild, prefix, is_staff, language)
                return await ctx.send(embed=embed)

        safe_help_callback.__name__ = getattr(current_callback, "__name__", "help_cmd")
        safe_help_callback.__doc__ = getattr(current_callback, "__doc__", None)
        safe_help_callback._sentrix_safe_help_v3 = True
        safe_help_callback._sentrix_v3_ux = True
        help_command.callback = safe_help_callback

    # Le setter du callback peut recalculer Command.params : nettoyer une seconde fois
    # APRES l'affectation est ce qui empêche définitivement « ctx est obligatoire ».
    _sanitize_help_command_params(help_command)

    bot._sentrix_help_components_safe_v3 = True
    logger.info("+help V3 compatible : aucun argument ctx interne, cooldown neutralisé et fallback actif.")


def install(bot: commands.Bot) -> None:
    if not getattr(bot, "_sentrix_help_cooldown_exemption_v3", False):
        _patch_global_prefix_cooldown(bot)
        _patch_v41_guards()
        bot._sentrix_help_cooldown_exemption_v3 = True

    # Retenté après chaque extension car help n'existe qu'après le chargement d'utility.
    _patch_v3_components(bot)


__all__ = ["install", "_sanitize_help_command_params"]
