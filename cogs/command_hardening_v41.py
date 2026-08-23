"""Renforcement transversal des commandes SentriX V41.

Cette couche ne remplace pas les checks métier existants. Elle complète toute la surface
préfixée et slash avec des protections qui restent valables pour les futures commandes :
- même anti-spam global côté slash que côté commandes préfixées ;
- anti double-exécution très courte pour les clics/messages répétés ;
- limite de concurrence par utilisateur et par serveur ;
- limite plus stricte pour les commandes lourdes/destructives ;
- refus silencieux des appels provenant de bots ;
- audit automatique du registre pour détecter les commandes non classées, les collisions
  d'alias et les commandes sensibles accidentellement déclarées publiques.

Les refus slash sont privés. Les commandes préfixées utilisent CommandOnCooldown afin de
rester compatibles avec le gestionnaire d'erreurs central de main.py.
"""
from __future__ import annotations

import inspect
import logging
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import discord
from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.command-hardening-v41")

_DUPLICATE_WINDOW = 0.8
_USER_CONCURRENCY = 2
_GUILD_CONCURRENCY = 24
_HEAVY_USER_CONCURRENCY = 1
_HEAVY_GUILD_CONCURRENCY = 2
_STATE_TTL = 120.0

_AI_ROOTS = frozenset({
    "sentrix", "ai", "ask", "chat", "summarize", "image", "image-prompt",
    "explain", "rewrite", "fact-check", "improve", "correct", "ai-translate", "code",
})

_HEAVY_ROOTS = frozenset({
    "image", "server-backup", "server-restore", "create-server", "wipe-server",
    "massrole", "roleall", "sync", "syncguild", "permission-audit", "diagnostic",
})

_DESTRUCTIVE_ROOTS = frozenset({
    "wipe-server", "server-restore", "massrole", "roleall", "delete-channel",
    "reset-economy", "reset-levels", "config-reset", "bot-leave", "lockdown-server",
})


@dataclass(slots=True)
class _GuardState:
    slash_buckets: dict[int, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    same_command_last: dict[tuple[str, int, str], float] = field(default_factory=dict)
    active_user: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    active_guild: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    active_heavy_user: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    active_heavy_guild: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    prefix_tokens: dict[int, tuple[int, int, bool]] = field(default_factory=dict)
    slash_tokens: dict[int, tuple[int, int, bool]] = field(default_factory=dict)
    last_cleanup: float = 0.0


def _state(bot: commands.Bot) -> _GuardState:
    value = getattr(bot, "_sentrix_command_hardening_state", None)
    if isinstance(value, _GuardState):
        return value
    value = _GuardState()
    bot._sentrix_command_hardening_state = value
    return value


def _runtime_main(bot: commands.Bot):
    return sys.modules.get(bot.__class__.__module__) or sys.modules.get("main") or sys.modules.get("__main__")


def _root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or getattr(command, "name", "") or "").strip().casefold()


def _interaction_root(interaction: discord.Interaction) -> str:
    name = _root_name(getattr(interaction, "command", None))
    if name:
        return name
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return str(data.get("name") or "").strip().casefold()
    return ""


def _is_static_owner(user_id: int | None) -> bool:
    if user_id is None:
        return False
    user_id = int(user_id)
    return user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS


def _clean_state(bot: commands.Bot) -> None:
    state = _state(bot)
    now = time.monotonic()
    if now - state.last_cleanup < 30.0:
        return
    state.last_cleanup = now

    cutoff = now - _STATE_TTL
    for key, stamp in list(state.same_command_last.items()):
        if stamp < cutoff:
            state.same_command_last.pop(key, None)

    window = max(float(getattr(config, "GLOBAL_COOLDOWN_PER", 5.0) or 5.0), 5.0)
    bucket_cutoff = now - max(window, 30.0)
    for user_id, bucket in list(state.slash_buckets.items()):
        while bucket and bucket[0] < bucket_cutoff:
            bucket.popleft()
        if not bucket:
            state.slash_buckets.pop(user_id, None)


def _duplicate_retry(bot: commands.Bot, *, source: str, user_id: int, root: str) -> float:
    state = _state(bot)
    now = time.monotonic()
    key = (source, int(user_id), root)
    previous = state.same_command_last.get(key, 0.0)
    state.same_command_last[key] = now
    remaining = _DUPLICATE_WINDOW - (now - previous)
    return max(0.0, remaining)


def _slash_rate_retry(bot: commands.Bot, user_id: int, root: str) -> float:
    """Applique aux slash le même plafond global que les commandes préfixées.

    Les opérations IA lourdes gardent en plus un plafond raisonnable afin qu'un seul membre
    ne puisse pas saturer les workers réseau/API du bot.
    """
    if _is_static_owner(user_id):
        return 0.0

    state = _state(bot)
    now = time.monotonic()
    rate = max(1, int(getattr(config, "GLOBAL_COOLDOWN_RATE", 3) or 3))
    period = max(1.0, float(getattr(config, "GLOBAL_COOLDOWN_PER", 5.0) or 5.0))

    if root in _AI_ROOTS:
        rate = min(rate, 2)
        period = max(period, 6.0)
    if root in _HEAVY_ROOTS:
        rate = 1
        period = max(period, 4.0)

    bucket = state.slash_buckets[int(user_id)]
    while bucket and now - bucket[0] >= period:
        bucket.popleft()
    if len(bucket) >= rate:
        return max(0.1, period - (now - bucket[0]))
    bucket.append(now)
    return 0.0


def _acquire(bot: commands.Bot, *, token_id: int, user_id: int, guild_id: int | None, root: str, slash: bool) -> str | None:
    state = _state(bot)
    user_id = int(user_id)
    guild_key = int(guild_id or 0)
    heavy = root in _HEAVY_ROOTS

    user_limit = _HEAVY_USER_CONCURRENCY if heavy else _USER_CONCURRENCY
    guild_limit = _HEAVY_GUILD_CONCURRENCY if heavy else _GUILD_CONCURRENCY

    current_user = state.active_heavy_user[user_id] if heavy else state.active_user[user_id]
    current_guild = state.active_heavy_guild[guild_key] if heavy else state.active_guild[guild_key]

    if current_user >= user_limit:
        return "Tu as déjà une commande de ce type en cours. Attends qu'elle se termine avant d'en relancer une."
    if guild_key and current_guild >= guild_limit:
        return "Trop de commandes sont déjà en cours sur ce serveur. Réessaie dans quelques secondes."

    state.active_user[user_id] += 1
    state.active_guild[guild_key] += 1
    if heavy:
        state.active_heavy_user[user_id] += 1
        state.active_heavy_guild[guild_key] += 1

    token = (user_id, guild_key, heavy)
    if slash:
        state.slash_tokens[int(token_id)] = token
    else:
        state.prefix_tokens[int(token_id)] = token
    return None


def _release_token(state: _GuardState, token: tuple[int, int, bool] | None) -> None:
    if token is None:
        return
    user_id, guild_key, heavy = token
    state.active_user[user_id] = max(0, state.active_user[user_id] - 1)
    state.active_guild[guild_key] = max(0, state.active_guild[guild_key] - 1)
    if heavy:
        state.active_heavy_user[user_id] = max(0, state.active_heavy_user[user_id] - 1)
        state.active_heavy_guild[guild_key] = max(0, state.active_heavy_guild[guild_key] - 1)


def release_prefix(bot: commands.Bot, ctx: commands.Context) -> None:
    state = _state(bot)
    token = state.prefix_tokens.pop(id(ctx), None)
    _release_token(state, token)


def release_slash(interaction: discord.Interaction) -> None:
    bot = getattr(interaction, "client", None)
    if not isinstance(bot, commands.Bot):
        return
    state = _state(bot)
    token = state.slash_tokens.pop(int(interaction.id), None)
    _release_token(state, token)


async def _send_slash_denial(interaction: discord.Interaction, text: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer le refus du garde V41.", exc_info=True)


def _cooldown_error(retry_after: float) -> commands.CommandOnCooldown:
    rate = max(1, int(getattr(config, "GLOBAL_COOLDOWN_RATE", 3) or 3))
    period = max(1.0, float(getattr(config, "GLOBAL_COOLDOWN_PER", 5.0) or 5.0))
    cooldown = commands.Cooldown(rate, period)
    return commands.CommandOnCooldown(cooldown, max(0.1, retry_after), commands.BucketType.user)


def _audit_registry(bot: commands.Bot) -> None:
    main = _runtime_main(bot)
    if main is None:
        return

    public = set(getattr(main, "PUBLIC_COMMANDS", ()) or ())
    known = set(getattr(main, "KNOWN_PERMISSION_COMMANDS", ()) or ())
    roots: set[str] = set()
    aliases: dict[str, set[str]] = defaultdict(set)
    missing_docs: list[str] = []

    for command in bot.walk_commands():
        root = _root_name(command)
        if root:
            roots.add(root)
        canonical = str(getattr(command, "qualified_name", "") or "").strip()
        if canonical and not (getattr(command, "help", None) or getattr(command, "description", None)):
            missing_docs.append(canonical)
        for alias in getattr(command, "aliases", ()) or ():
            aliases[str(alias).casefold()].add(canonical or root)

    try:
        for command in bot.tree.get_commands():
            name = _root_name(command)
            if name:
                roots.add(name)
    except Exception:
        logger.debug("Audit slash partiel : lecture du CommandTree impossible.", exc_info=True)

    unknown = sorted(name for name in roots if name not in known)
    dangerous_public = sorted(_DESTRUCTIVE_ROOTS & public)
    alias_collisions = {
        alias: sorted(values)
        for alias, values in aliases.items()
        if len(values) > 1
    }

    report = {
        "root_commands": len(roots),
        "unknown_policy": unknown,
        "dangerous_public": dangerous_public,
        "alias_collisions": alias_collisions,
        "missing_docs": sorted(set(missing_docs)),
    }
    bot._sentrix_command_audit = report

    if unknown:
        logger.warning(
            "Audit commandes V41 : %s racine(s) non classée(s), donc fail-closed : %s",
            len(unknown), ", ".join(unknown[:30]),
        )
    if dangerous_public:
        logger.critical(
            "Audit commandes V41 : commandes destructives déclarées publiques : %s",
            ", ".join(dangerous_public),
        )
    if alias_collisions:
        logger.warning("Audit commandes V41 : %s collision(s) d'alias détectée(s).", len(alias_collisions))


def install(bot: commands.Bot) -> None:
    """Installe les gardes une seule fois puis ré-audite le registre à chaque extension."""
    _audit_registry(bot)
    if getattr(bot, "_sentrix_command_hardening_v41", False):
        return

    async def prefix_guard(ctx: commands.Context) -> bool:
        command = getattr(ctx, "command", None)
        author = getattr(ctx, "author", None)
        if command is None or author is None:
            return True
        if getattr(author, "bot", False):
            return False

        _clean_state(bot)
        root = _root_name(command)
        retry = _duplicate_retry(bot, source="prefix", user_id=author.id, root=root)
        if retry > 0:
            raise _cooldown_error(retry)

        error = _acquire(
            bot,
            token_id=id(ctx),
            user_id=author.id,
            guild_id=getattr(getattr(ctx, "guild", None), "id", None),
            root=root,
            slash=False,
        )
        if error:
            raise _cooldown_error(1.5)
        return True

    original_tree_check = bot.tree.interaction_check

    async def slash_guard(interaction: discord.Interaction) -> bool:
        previous = original_tree_check(interaction)
        if inspect.isawaitable(previous):
            previous = await previous
        if previous is False:
            return False
        if interaction.type is not discord.InteractionType.application_command:
            return True

        user = getattr(interaction, "user", None)
        if user is None or getattr(user, "bot", False):
            return False

        _clean_state(bot)
        root = _interaction_root(interaction)
        retry = _duplicate_retry(bot, source="slash", user_id=user.id, root=root)
        if retry > 0:
            await _send_slash_denial(interaction, f"Commande déjà reçue. Réessaie dans {max(1, round(retry))} s.")
            return False

        retry = _slash_rate_retry(bot, int(user.id), root)
        if retry > 0:
            await _send_slash_denial(interaction, f"Tu utilises les commandes trop vite. Réessaie dans {max(1, round(retry))} s.")
            return False

        error = _acquire(
            bot,
            token_id=int(interaction.id),
            user_id=int(user.id),
            guild_id=interaction.guild_id,
            root=root,
            slash=True,
        )
        if error:
            await _send_slash_denial(interaction, error)
            return False
        return True

    async def prefix_done(ctx: commands.Context) -> None:
        release_prefix(bot, ctx)

    async def prefix_failed(ctx: commands.Context, _error: commands.CommandError) -> None:
        release_prefix(bot, ctx)

    async def slash_done(interaction: discord.Interaction, _command: Any) -> None:
        release_slash(interaction)

    prefix_guard._sentrix_command_hardening_v41 = True
    slash_guard._sentrix_command_hardening_v41 = True
    slash_guard._sentrix_previous_tree_check = original_tree_check

    bot.add_check(prefix_guard)
    bot.tree.interaction_check = slash_guard
    bot.add_listener(prefix_done, "on_command_completion")
    bot.add_listener(prefix_failed, "on_command_error")
    bot.add_listener(slash_done, "on_app_command_completion")
    bot._sentrix_command_hardening_v41 = True

    logger.info(
        "Commandes V41 renforcées : anti double-exécution, anti-spam slash, concurrence et audit global actifs."
    )
