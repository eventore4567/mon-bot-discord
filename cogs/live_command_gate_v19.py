"""SentriX V19 — diagnostic live non bloquant.

Ce module s'exécute une fois que le bot est réellement connecté à Discord. Il vérifie le
registre des commandes et compare les commandes slash locales avec celles enregistrées chez
Discord, mais il ne ferme JAMAIS le bot de production. Les tests d'exécution plus agressifs
doivent rester réservés au service Canary séparé.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.live-command-gate-v19")

_RESERVED = frozenset({"self", "ctx", "context", "interaction", "bot", "_bot"})
_REQUIRED = ("help", "ping", "create", "create sentrix", "create server", "create-server")


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
        "guilds": 0,
        "text_commands": 0,
        "local_slash": 0,
        "remote_slash": 0,
    }
    bot._sentrix_live_command_gate_v19 = value
    return value


async def _fetch_remote_slash(bot: commands.Bot) -> tuple[set[str], str | None]:
    last_error: BaseException | None = None
    for attempt in range(3):
        try:
            items = await bot.tree.fetch_commands()
            return {str(item.name).casefold() for item in items}, None
        except discord.HTTPException as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(2.0 * (attempt + 1))
        except Exception as exc:
            last_error = exc
            break
    if last_error is None:
        return set(), "aucune réponse Discord"
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
        "guilds": len(list(getattr(bot, "guilds", ()) or ())),
        "text_commands": 0,
        "local_slash": 0,
        "remote_slash": 0,
    })
    errors: list[str] = state["errors"]
    warnings: list[str] = state["warnings"]

    try:
        if not bot.is_ready():
            warnings.append("Discord n'était pas encore prêt au lancement du diagnostic")
            return state

        commands_seen = list(bot.walk_commands())
        state["text_commands"] = len(commands_seen)

        for required in _REQUIRED:
            if bot.get_command(required) is None:
                errors.append(f"commande essentielle absente: {required}")

        for command in commands_seen:
            name = str(getattr(command, "qualified_name", "") or "commande")
            callback = getattr(command, "callback", None)
            if callback is None or not inspect.iscoroutinefunction(callback):
                errors.append(f"callback invalide: {name}")
                continue
            try:
                params = dict(getattr(command, "clean_params", {}) or {})
            except Exception as exc:
                errors.append(f"signature illisible {name}: {type(exc).__name__}: {str(exc)[:180]}")
                continue
            leaked = [key for key in params if str(key).casefold() in _RESERVED]
            if leaked:
                errors.append(f"paramètre interne exposé {name}: {', '.join(leaked)}")

        local = {str(item.name).casefold() for item in bot.tree.get_commands()}
        state["local_slash"] = len(local)
        remote, remote_error = await _fetch_remote_slash(bot)
        state["remote_slash"] = len(remote)

        # La propagation globale des slash peut prendre du temps chez Discord : une
        # différence distante est donc un diagnostic, jamais une raison d'éteindre SentriX.
        if remote_error:
            warnings.append(f"lecture des / distants impossible: {remote_error}")
        else:
            missing = sorted(local - remote)
            stale = sorted(remote - local)
            if missing:
                warnings.append("/ pas encore visibles chez Discord: " + ", ".join(missing[:30]))
            if stale:
                warnings.append("/ anciens encore visibles chez Discord: " + ", ".join(stale[:30]))

        state["ok"] = not errors
        return state
    except Exception as exc:
        errors.append(f"diagnostic live interne: {type(exc).__name__}: {str(exc)[:500]}")
        logger.exception("V19 : diagnostic live interrompu.")
        return state
    finally:
        state["running"] = False
        state["completed"] = True
        state["ok"] = not bool(state["errors"])

        # CRITIQUE : le diagnostic de production ne doit jamais agir comme un kill switch.
        bot._sentrix_live_gate_failed = False
        bot._sentrix_live_gate_detail = (
            "OK" if state["ok"] else " | ".join(state["errors"][:20])
        )

        if state["ok"]:
            logger.info(
                "V19 LIVE diagnostic OK : guilds=%s, commandes+=%s, slash local/distant=%s/%s, warnings=%s.",
                state["guilds"],
                state["text_commands"],
                state["local_slash"],
                state["remote_slash"],
                len(state["warnings"]),
            )
        else:
            logger.error(
                "V19 LIVE diagnostic : %s erreur(s), bot maintenu en ligne — %s",
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

        # Ne bloque pas on_ready et ne ferme jamais le client Discord.
        task = asyncio.create_task(run_live_gate(bot))
        bot._sentrix_live_gate_task = task

    state["listener_installed"] = True


__all__ = ["install", "run_live_gate"]
