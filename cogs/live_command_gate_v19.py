"""SentriX V19 — gate live des commandes sur le processus Railway connecté à Discord.

Ce module ne lance aucune action destructive. Il valide la surface de commandes contre le
bot réellement connecté :
- les commandes slash locales sont comparées aux commandes réellement enregistrées chez Discord ;
- chaque commande texte racine et chacun de ses alias sont résolus par le vrai parser du bot,
  avec le préfixe réellement configuré dans un vrai serveur ;
- les checks locaux et le verrou global de permissions sont exécutés dans un contexte de
  vrai serveur/membre afin de détecter les exceptions techniques sans lancer le callback métier ;
- le résultat est conservé sur le bot pour les healthchecks et le bootstrap Railway.

Les commandes destructives (ban, kick, wipe, suppression de salons, paiements, etc.) ne sont
jamais exécutées par ce gate : tester leur callback en production détruirait volontairement
l'état du serveur. Leur chargement, résolution, signature et checks sont néanmoins validés.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from types import SimpleNamespace
from typing import Any

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView

logger = logging.getLogger("bot.live-command-gate-v19")

_REMOTE_RETRIES = 4
_REMOTE_RETRY_DELAY = 2.0


def _state(bot: commands.Bot) -> dict[str, Any]:
    value = getattr(bot, "_sentrix_live_command_gate_v19", None)
    if isinstance(value, dict):
        return value
    value = {
        "running": False,
        "completed": False,
        "ok": False,
        "errors": [],
        "warnings": [],
        "guild_id": None,
        "prefix": None,
        "prefix_commands": 0,
        "prefix_aliases": 0,
        "local_slash": 0,
        "remote_slash": 0,
        "checks_tested": 0,
        "global_permissions_tested": 0,
    }
    bot._sentrix_live_command_gate_v19 = value
    return value


def _first_probe_guild(bot: commands.Bot) -> discord.Guild | None:
    guilds = list(getattr(bot, "guilds", ()) or ())
    if not guilds:
        return None
    for guild in guilds:
        if guild.get_member(guild.owner_id) is not None:
            return guild
    return guilds[0]


async def _probe_member(guild: discord.Guild) -> discord.Member | None:
    member = guild.get_member(guild.owner_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(guild.owner_id)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return None


def _probe_channel(guild: discord.Guild) -> discord.abc.Messageable | None:
    me = guild.me
    for channel in guild.text_channels:
        if me is None:
            return channel
        try:
            perms = channel.permissions_for(me)
        except Exception:
            continue
        if perms.view_channel:
            return channel
    return guild.system_channel


def _fake_message(*, guild: discord.Guild, member: discord.Member, channel, content: str):
    return SimpleNamespace(
        id=0,
        content=content,
        author=member,
        guild=guild,
        channel=channel,
        created_at=discord.utils.utcnow(),
        attachments=[],
        mentions=[],
        role_mentions=[],
        channel_mentions=[],
        interaction=None,
    )


async def _real_prefix(bot: commands.Bot, message) -> str:
    try:
        prefixes = await bot.get_prefix(message)
    except Exception:
        return "+"
    if isinstance(prefixes, str):
        return prefixes
    for prefix in list(prefixes or ())[::-1]:
        value = str(prefix)
        if value and not value.startswith("<@"):
            return value
    return "+"


def _context(bot: commands.Bot, message, command: commands.Command, prefix: str) -> commands.Context:
    return commands.Context(
        message=message,
        bot=bot,
        view=StringView(message.content),
        args=[],
        kwargs={},
        prefix=prefix,
        command=command,
        invoked_with=command.name,
        invoked_parents=[],
        invoked_subcommand=None,
        subcommand_passed=None,
        command_failed=False,
        current_parameter=None,
        interaction=None,
    )


async def _check_local_predicates(ctx: commands.Context, command: commands.Command) -> list[str]:
    errors: list[str] = []
    for predicate in list(getattr(command, "checks", ()) or ()):
        try:
            result = predicate(ctx)
            if inspect.isawaitable(result):
                result = await result
            if result is False:
                continue
        except commands.CheckFailure:
            continue
        except Exception as exc:
            errors.append(
                f"check +{command.qualified_name}: {type(exc).__name__}: {str(exc)[:240]}"
            )
    return errors


async def _check_global_permission(bot: commands.Bot, ctx: commands.Context, command: commands.Command) -> list[str]:
    checker = getattr(bot, "global_permission_check", None)
    if not callable(checker):
        return ["global_permission_check absent du bot live"]
    try:
        allowed = await checker(ctx)
        if allowed is False:
            return [f"permission globale +{command.qualified_name}: retour False"]
        return []
    except commands.CheckFailure as exc:
        root = command.root_parent or command
        owner_only = set()
        try:
            import main
            owner_only = set(getattr(main, "OWNER_ONLY_COMMANDS", ()) or ())
        except Exception:
            pass
        if str(root.name).casefold() in {str(name).casefold() for name in owner_only}:
            return []
        # Le membre de probe est le propriétaire du serveur : une commande non owner-only
        # ne doit pas être bloquée par le verrou global de SentriX.
        return [
            f"permission globale +{command.qualified_name}: {type(exc).__name__}: {str(exc)[:240]}"
        ]
    except Exception as exc:
        return [
            f"permission globale +{command.qualified_name}: {type(exc).__name__}: {str(exc)[:240]}"
        ]


async def _remote_slash_names(bot: commands.Bot) -> tuple[set[str], str | None]:
    last_error: Exception | None = None
    for attempt in range(_REMOTE_RETRIES):
        try:
            remote = await bot.tree.fetch_commands()
            return {str(item.name).casefold() for item in remote}, None
        except discord.HTTPException as exc:
            last_error = exc
            if attempt < _REMOTE_RETRIES - 1:
                await asyncio.sleep(_REMOTE_RETRY_DELAY * (attempt + 1))
        except Exception as exc:
            last_error = exc
            break
    if last_error is None:
        return set(), "Discord n'a renvoyé aucune réponse"
    return set(), f"{type(last_error).__name__}: {str(last_error)[:300]}"


async def run_live_gate(bot: commands.Bot) -> dict[str, Any]:
    state = _state(bot)
    if state.get("running"):
        return state
    state.update({
        "running": True,
        "completed": False,
        "ok": False,
        "errors": [],
        "warnings": [],
        "guild_id": None,
        "prefix": None,
        "prefix_commands": 0,
        "prefix_aliases": 0,
        "local_slash": 0,
        "remote_slash": 0,
        "checks_tested": 0,
        "global_permissions_tested": 0,
    })
    errors: list[str] = state["errors"]

    try:
        if not bot.is_ready():
            errors.append("Discord n'est pas prêt au moment du gate live")
            return state

        guild = _first_probe_guild(bot)
        if guild is None:
            errors.append("aucun serveur Discord réel disponible pour tester les commandes +")
            return state
        state["guild_id"] = int(guild.id)

        member = await _probe_member(guild)
        channel = _probe_channel(guild)
        if member is None:
            errors.append("propriétaire du serveur de probe introuvable")
            return state
        if channel is None:
            errors.append("aucun salon réel disponible pour le parser +")
            return state

        seed = _fake_message(guild=guild, member=member, channel=channel, content="+")
        prefix = await _real_prefix(bot, seed)
        state["prefix"] = prefix

        # 1) Vrai parser préfixe pour toutes les commandes racine et tous leurs alias.
        for command in list(bot.commands):
            if not getattr(command, "enabled", True):
                continue
            candidates = [str(command.name), *[str(a) for a in getattr(command, "aliases", ())]]
            for index, invoked in enumerate(candidates):
                message = _fake_message(
                    guild=guild,
                    member=member,
                    channel=channel,
                    content=f"{prefix}{invoked}",
                )
                try:
                    ctx = await bot.get_context(message)
                except Exception as exc:
                    errors.append(
                        f"parser {prefix}{invoked}: {type(exc).__name__}: {str(exc)[:240]}"
                    )
                    continue
                if ctx.command is not command:
                    got = getattr(getattr(ctx, "command", None), "qualified_name", None)
                    errors.append(
                        f"parser {prefix}{invoked}: attendu {command.qualified_name}, obtenu {got or 'aucune commande'}"
                    )
                if index == 0:
                    state["prefix_commands"] += 1
                else:
                    state["prefix_aliases"] += 1

        # 2) Groupes et sous-commandes réellement chargés.
        for group in [item for item in bot.walk_commands() if isinstance(item, commands.Group)]:
            for child in list(group.commands):
                if group.get_command(child.name) is not child:
                    errors.append(
                        f"groupe +{group.qualified_name}: {child.name} ne se résout pas vers sa vraie sous-commande"
                    )
                for alias in list(getattr(child, "aliases", ()) or ()):
                    if group.get_command(alias) is not child:
                        errors.append(f"alias +{group.qualified_name} {alias}: résolution incorrecte")

        # 3) Checks locaux + verrou global sur un vrai serveur/propriétaire.
        for command in list(bot.walk_commands()):
            message = _fake_message(
                guild=guild,
                member=member,
                channel=channel,
                content=f"{prefix}{command.qualified_name}",
            )
            try:
                ctx = _context(bot, message, command, prefix)
            except Exception as exc:
                errors.append(
                    f"contexte +{command.qualified_name}: {type(exc).__name__}: {str(exc)[:240]}"
                )
                continue
            state["checks_tested"] += len(list(getattr(command, "checks", ()) or ()))
            errors.extend(await _check_local_predicates(ctx, command))
            state["global_permissions_tested"] += 1
            errors.extend(await _check_global_permission(bot, ctx, command))

        # 4) Slash réellement enregistrés chez Discord, via l'API distante.
        local_slash = {str(item.name).casefold() for item in bot.tree.get_commands()}
        remote_slash, remote_error = await _remote_slash_names(bot)
        state["local_slash"] = len(local_slash)
        state["remote_slash"] = len(remote_slash)
        if remote_error:
            errors.append(f"lecture des / chez Discord impossible: {remote_error}")
        else:
            missing_remote = sorted(local_slash - remote_slash)
            stale_remote = sorted(remote_slash - local_slash)
            if missing_remote:
                errors.append("/ absents chez Discord: " + ", ".join(missing_remote[:30]))
            if stale_remote:
                errors.append("/ obsolètes encore chez Discord: " + ", ".join(stale_remote[:30]))

        if bot.user is None or guild.me is None:
            errors.append("identité/membre du bot indisponible dans le serveur live")

        state["ok"] = not errors
        return state
    except Exception as exc:
        errors.append(f"gate live interne: {type(exc).__name__}: {str(exc)[:500]}")
        logger.exception("V19 : exception interne pendant le gate live.")
        return state
    finally:
        state["running"] = False
        state["completed"] = True
        state["ok"] = not bool(state["errors"])
        if state["ok"]:
            logger.info(
                "V19 LIVE OK : guild=%s prefix=%r, %s commandes +, %s alias +, %s checks locaux, "
                "%s permissions globales, %s/%s slash Discord.",
                state["guild_id"],
                state["prefix"],
                state["prefix_commands"],
                state["prefix_aliases"],
                state["checks_tested"],
                state["global_permissions_tested"],
                state["remote_slash"],
                state["local_slash"],
            )
        else:
            logger.error(
                "V19 LIVE ECHEC : %s problème(s) — %s",
                len(state["errors"]),
                " | ".join(state["errors"][:20]),
            )


def install(bot: commands.Bot) -> None:
    state = _state(bot)
    if state.get("listener_installed"):
        return

    @bot.listen("on_ready")
    async def sentrix_live_command_gate_v19() -> None:
        runtime = _state(bot)
        if runtime.get("completed") or runtime.get("running"):
            return
        try:
            await run_live_gate(bot)
        except Exception as exc:
            runtime["errors"] = list(runtime.get("errors", [])) + [
                f"listener live: {type(exc).__name__}: {str(exc)[:500]}"
            ]
            runtime["completed"] = True
            runtime["ok"] = False
            logger.exception("V19 : le listener live a lui-même échoué.")

        if not runtime.get("ok"):
            bot._sentrix_live_gate_failed = True
            bot._sentrix_live_gate_detail = " | ".join(runtime.get("errors", [])[:20])
            await bot.close()
        else:
            bot._sentrix_live_gate_failed = False
            bot._sentrix_live_gate_detail = "OK"

    state["listener_installed"] = True


__all__ = ["install", "run_live_gate"]
