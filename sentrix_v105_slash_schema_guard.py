"""SentriX V105 — garde-fou global des schemas slash.

Cette couche s'execute apres la preparation V95 et juste avant chaque sync Discord.
Elle garantit que les parametres internes des callbacks Python (ctx, *args, **kwargs,
etc.) ne peuvent jamais etre publies comme options slash.

Les commandes racine directes, volontairement exclues du regroupement V95, sont
reconstruites comme vraies commandes ``app_commands`` a partir de leur commande texte.
``/setup`` conserve son pont specialise V103 vers le centre de configuration existant.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator

from discord import app_commands
from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_v103_setup_fix as v103

logger = logging.getLogger("bot.v105-slash-schema")

# Noms qui ne doivent jamais devenir des options visibles dans Discord.
FORBIDDEN_PUBLIC_PARAMETERS = frozenset({"ctx", "context", "args", "kwargs", "self"})
DIRECT_BRIDGED_ROOTS = ("help", "ping", "sentrix")
_INSTALL_MARKER = "_sentrix_v105_slash_schema_guard_installed"


def _iter_leaf_commands(
    nodes: Iterable[app_commands.Command | app_commands.Group],
) -> Iterator[app_commands.Command]:
    for node in nodes:
        if isinstance(node, app_commands.Group):
            yield from _iter_leaf_commands(node.commands)
        elif isinstance(node, app_commands.Command):
            yield node


def _parameter_names(command: app_commands.Command) -> set[str]:
    try:
        return {str(parameter.name).strip().casefold() for parameter in command.parameters}
    except Exception:
        # Une commande impossible a introspecter ne doit pas etre consideree comme saine.
        return {"<introspection-error>"}


def _replace_direct_root(bot: commands.Bot, name: str) -> bool:
    """Remplace une racine hybride par un wrapper slash dont la signature est maitrisee."""
    legacy = bot.get_command(name)
    if not isinstance(legacy, commands.Command):
        return False

    callback, _native = v95._make_callback(bot, legacy)
    native = app_commands.Command(
        name=name,
        description=v95._description(legacy),
        callback=callback,
    )

    if bot.tree.get_command(name) is not None:
        bot.tree.remove_command(name)
    bot.tree.add_command(native, override=True)
    return True


def _ensure_direct_roots(bot: commands.Bot) -> None:
    """Normalise les commandes slash racine que V95 laisse volontairement directes."""
    for name in DIRECT_BRIDGED_ROOTS:
        try:
            if _replace_direct_root(bot, name):
                logger.debug("/%s reconstruit avec une signature slash native.", name)
        except Exception:
            logger.exception("Impossible de reconstruire /%s en commande slash native.", name)
            raise

    # /setup utilise le pont dedie V103, qui n'expose que ``interaction`` a Discord.
    try:
        legacy_setup = v103._find_legacy_setup(bot)
    except Exception:
        legacy_setup = None
    if legacy_setup is not None:
        v103.install(bot)


def audit_tree(tree: app_commands.CommandTree) -> tuple[str, ...]:
    """Valide toute la surface slash finale et bloque une sync contenant une fuite interne."""
    violations: list[str] = []
    audited: list[str] = []

    for command in _iter_leaf_commands(tree.get_commands()):
        qualified_name = str(getattr(command, "qualified_name", None) or command.name)
        audited.append(qualified_name)
        names = _parameter_names(command)
        if "<introspection-error>" in names:
            violations.append(f"/{qualified_name}: introspection impossible")
            continue
        leaked = sorted(names & FORBIDDEN_PUBLIC_PARAMETERS)
        if leaked:
            violations.append(f"/{qualified_name}: {', '.join(leaked)}")

    if violations:
        details = "; ".join(violations)
        raise RuntimeError(
            "SentriX V105 a bloque la synchronisation slash car des parametres internes "
            f"seraient visibles dans Discord: {details}"
        )

    logger.info(
        "Audit slash V105 valide: %s commande(s), aucune fuite ctx/args/kwargs.",
        len(audited),
    )
    return tuple(audited)


async def prepare_bot(bot: commands.Bot) -> tuple[str, ...]:
    """Point d'entree testable: applique V95, les racines natives, puis audite."""
    await v95.prepare_bot(bot)
    _ensure_direct_roots(bot)
    return audit_tree(bot.tree)


def install() -> None:
    """Branche le garde-fou dans V95 afin qu'il s'execute avant chaque CommandTree.sync."""
    if getattr(v95, _INSTALL_MARKER, False):
        return

    original_prepare = v95.prepare_bot

    async def guarded_prepare(bot: commands.Bot):
        result = await original_prepare(bot)
        _ensure_direct_roots(bot)
        audit_tree(bot.tree)
        return result

    guarded_prepare.__name__ = "prepare_bot_v105_guarded"
    guarded_prepare.__qualname__ = guarded_prepare.__name__
    guarded_prepare._sentrix_original = original_prepare
    v95.prepare_bot = guarded_prepare
    setattr(v95, _INSTALL_MARKER, True)
    logger.info("SentriX V105 slash schema guard installe.")


__all__ = [
    "DIRECT_BRIDGED_ROOTS",
    "FORBIDDEN_PUBLIC_PARAMETERS",
    "audit_tree",
    "install",
    "prepare_bot",
]
