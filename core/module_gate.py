"""Garde d'accès aux modules dont le circuit est ouvert.

Aucune logique métier ici : on traduit uniquement l'état du micro-kernel en une
indisponibilité temporaire propre pour les commandes Discord.
"""
from __future__ import annotations

from typing import Any

from discord import app_commands

_GATED_COMMAND_IDS: set[int] = set()
from discord.ext import commands


class ModuleTemporarilyUnavailable(commands.CheckFailure):
    def __init__(self, module: str):
        self.module = module
        super().__init__(f"Module temporairement indisponible: {module}")


class AppModuleTemporarilyUnavailable(app_commands.CheckFailure):
    def __init__(self, module: str):
        self.module = module
        super().__init__(f"Module temporairement indisponible: {module}")


def _module_from_value(value: Any) -> str | None:
    if value is None:
        return None
    module = str(getattr(value, "__module__", "") or "")
    if module.startswith("cogs."):
        return module
    cls = getattr(value, "__class__", None)
    module = str(getattr(cls, "__module__", "") or "")
    return module if module.startswith("cogs.") else None


def prefix_command_module(ctx: commands.Context) -> str | None:
    command = getattr(ctx, "command", None)
    cog = getattr(command, "cog", None)
    return _module_from_value(cog) or _module_from_value(getattr(command, "callback", None))


def app_command_module(command: Any) -> str | None:
    binding = getattr(command, "binding", None)
    return _module_from_value(binding) or _module_from_value(getattr(command, "callback", None))


def circuit_open(bot, module: str | None) -> bool:
    if not module:
        return False
    kernel = getattr(bot, "module_kernel", None)
    if kernel is None or not hasattr(kernel, "snapshot"):
        return False
    state = kernel.snapshot().get("modules", {}).get(module, {})
    return bool(state.get("circuit_open"))


async def prefix_gate(ctx: commands.Context) -> bool:
    module = prefix_command_module(ctx)
    if circuit_open(ctx.bot, module):
        raise ModuleTemporarilyUnavailable(module or "inconnu")
    kernel = getattr(ctx.bot, "module_kernel", None)
    if module and kernel is not None and hasattr(kernel, "enter_runtime"):
        kernel.enter_runtime(module)
    return True


def app_gate_for(command):
    async def check(interaction) -> bool:
        module = app_command_module(command)
        if circuit_open(interaction.client, module):
            raise AppModuleTemporarilyUnavailable(module or "inconnu")
        kernel = getattr(interaction.client, "module_kernel", None)
        if module and kernel is not None and hasattr(kernel, "enter_runtime"):
            kernel.enter_runtime(module)
        return True
    check.__name__ = f"sentrix_module_gate_{str(getattr(command, 'name', 'command')).replace('-', '_')}"
    return check


def _walk_app_commands(tree):
    walker = getattr(tree, "walk_commands", None)
    if callable(walker):
        yield from walker()
        return

    # Repli pour les versions/implémentations où CommandTree n'expose pas
    # walk_commands(). On traverse récursivement les groupes connus.
    stack = list(getattr(tree, "get_commands", lambda: [])())
    while stack:
        command = stack.pop()
        yield command
        children = getattr(command, "commands", None)
        if children:
            stack.extend(list(children))


def install_app_gates(bot) -> int:
    """Ajoute une garde aux commandes slash actuellement enregistrées."""
    installed = 0
    for command in _walk_app_commands(bot.tree):
        if not isinstance(command, app_commands.Command):
            continue
        add_check = getattr(command, "add_check", None)
        if not callable(add_check):
            continue
        marker = id(command)
        if marker in _GATED_COMMAND_IDS:
            continue
        add_check(app_gate_for(command))
        _GATED_COMMAND_IDS.add(marker)
        installed += 1
    return installed
