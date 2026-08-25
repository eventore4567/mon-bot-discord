"""SentriX V3 — l'aide reste toujours accessible.

`help` est une commande de navigation, pas une action métier coûteuse. Elle ne doit donc
pas consommer le quota global ni être refusée par l'anti-double-exécution V41. Cette
couche garde toutes les protections pour les autres commandes et ne modifie aucune
permission.
"""
from __future__ import annotations

import inspect
from types import MethodType

from discord.ext import commands

_HELP_ROOTS = frozenset({"help"})


def _root_name(command) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or getattr(command, "name", "") or "").strip().casefold()


def _help_context(ctx: commands.Context) -> bool:
    return _root_name(getattr(ctx, "command", None)) in _HELP_ROOTS


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

    # Normalement l'installation se produit pendant le chargement des extensions, avant
    # setup_hook.add_check(). Ce remplacement d'attribut suffit alors. Le bloc ci-dessous
    # couvre aussi un reload à chaud où l'ancien check serait déjà enregistré.
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


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_help_cooldown_exemption_v3", False):
        return

    _patch_global_prefix_cooldown(bot)
    _patch_v41_guards()
    bot._sentrix_help_cooldown_exemption_v3 = True
