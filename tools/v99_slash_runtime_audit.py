"""SentriX V99 — audit déterministe des callbacks slash publics.

Le runtime V95/V98 adapte encore les commandes ``commands.Command`` historiques, dont
la callback métier reçoit naturellement un ``commands.Context`` nommé ``ctx``. Ce
``ctx`` est interne au pont d'exécution et ne doit jamais être confondu avec la
signature publique enregistrée auprès de Discord, qui reçoit une
``discord.Interaction``.

Ce module audite donc exclusivement les callbacks ``discord.app_commands`` réellement
exposés dans l'arbre slash. Il peut être importé par d'autres diagnostics et possède un
gate autonome, sans connexion Discord, pour verrouiller le comportement V99.
"""
from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import discord
from discord import app_commands
from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_v98_slash as v98

LEGACY_CONTEXT_NAMES = frozenset({"ctx", "context"})
INTERACTION_NAMES = frozenset({"interaction", "inter"})


@dataclass(frozen=True)
class CallbackAudit:
    """Résultat d'audit d'une callback slash publique."""

    qualified_name: str
    ok: bool
    first_parameter: str | None
    reason: str


def _callback_parameters(callback) -> list[inspect.Parameter]:
    """Retourne les paramètres publics, sans ``self``/``cls`` éventuel."""

    try:
        parameters = list(inspect.signature(callback).parameters.values())
    except (TypeError, ValueError):
        return []
    if parameters and parameters[0].name.casefold() in {"self", "cls"}:
        parameters = parameters[1:]
    return parameters


def _is_interaction_annotation(annotation: object) -> bool:
    if annotation is discord.Interaction:
        return True
    if annotation is inspect.Parameter.empty:
        return False
    name = getattr(annotation, "__name__", None)
    if name == "Interaction":
        return True
    text = str(annotation).replace("typing.", "").strip("'\"")
    return text in {"Interaction", "discord.Interaction", "<class 'discord.interactions.Interaction'>"}


def audit_public_callback(command: app_commands.Command) -> CallbackAudit:
    """Audite la signature enregistrée auprès de Discord, jamais la cible legacy.

    Une callback publique qui expose ``ctx``/``context`` est explicitement rejetée,
    même si ce paramètre est annoté ``discord.Interaction``. À l'inverse, un ``ctx``
    présent derrière ``v95._invoke_original`` est normal et n'entre pas dans cet audit.
    """

    qualified = str(getattr(command, "qualified_name", None) or getattr(command, "name", "?"))
    callback = getattr(command, "callback", None)
    parameters = _callback_parameters(callback)
    if not parameters:
        return CallbackAudit(qualified, False, None, "callback publique sans paramètre Interaction")

    first = parameters[0]
    first_name = first.name.casefold()
    if first_name in LEGACY_CONTEXT_NAMES:
        return CallbackAudit(
            qualified,
            False,
            first.name,
            f"callback publique expose le paramètre legacy {first.name!r}",
        )

    if first_name not in INTERACTION_NAMES and not _is_interaction_annotation(first.annotation):
        return CallbackAudit(
            qualified,
            False,
            first.name,
            "premier paramètre public non identifiable comme discord.Interaction",
        )

    return CallbackAudit(
        qualified,
        True,
        first.name,
        "callback publique Interaction valide",
    )


def iter_public_leaf_commands(items: Iterable[object]) -> Iterator[app_commands.Command]:
    """Parcourt récursivement les feuilles d'un arbre ``app_commands``."""

    for item in items:
        if isinstance(item, app_commands.Group):
            yield from iter_public_leaf_commands(item.commands)
        elif isinstance(item, app_commands.Command):
            yield item


def audit_tree(tree: app_commands.CommandTree) -> list[CallbackAudit]:
    """Audite toutes les commandes chat-input publiques d'un ``CommandTree``."""

    roots = tree.get_commands(guild=None, type=discord.AppCommandType.chat_input)
    return [audit_public_callback(command) for command in iter_public_leaf_commands(roots)]


def _legacy_target(original: str, root: str, leaf: str | None = None) -> v95.SlashTarget:
    """Fabrique une cible legacy minimale pour le gate hors-ligne."""

    async def legacy_callback(ctx):
        return None

    command = commands.Command(
        legacy_callback,
        name=original.replace(" ", "-")[:32],
        description=f"Gate V99 {original}",
    )
    return v95.SlashTarget(
        command=command,
        root_name=root,
        leaf_name=leaf or original.replace(" ", "-"),
        original_name=original,
        native_options=True,
    )


def _build_representative_tree() -> tuple[commands.Bot, dict[str, dict], list[v95.SlashTarget]]:
    """Reproduit la surface V98 critique sans token ni appel réseau Discord."""

    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

    async def setup(interaction: discord.Interaction) -> None:
        return None

    bot.tree.add_command(
        app_commands.Command(
            name="setup",
            description="Configuration SentriX.",
            callback=setup,
        )
    )

    targets = [
        _legacy_target("ai", "ai", "ask"),
        _legacy_target("ai-translate", "ai", "translate"),
        _legacy_target("ban", "moderation", "ban"),
        _legacy_target("permission-audit", "security", "permission-audit"),
        _legacy_target("ticketpanel", "ticket", "panel"),
    ]

    original_builder = v95._build_targets
    try:
        v95._build_targets = lambda _bot: targets
        report = v98._add_grouped_surface_v98(bot)
    finally:
        v95._build_targets = original_builder

    return bot, report, targets


def main() -> int:
    errors: list[str] = []

    bot, report, targets = _build_representative_tree()
    audits = audit_tree(bot.tree)
    by_name = {audit.qualified_name: audit for audit in audits}

    setup_audit = by_name.get("setup")
    if setup_audit is None:
        errors.append("/setup a disparu de la surface publique")
    elif not setup_audit.ok:
        errors.append(f"/setup rejeté à tort: {setup_audit.reason}")
    elif setup_audit.first_parameter != "interaction":
        errors.append(f"/setup expose {setup_audit.first_parameter!r} au lieu de 'interaction'")

    failures = [audit for audit in audits if not audit.ok]
    for audit in failures:
        errors.append(f"/{audit.qualified_name}: {audit.reason}")

    expected_originals = {"ai", "ai-translate", "ban", "permission-audit", "ticketpanel"}
    mapped_originals = {str(meta.get("original")) for meta in report.values()}
    missing = expected_originals - mapped_originals
    if missing:
        errors.append(f"familles V99 absentes du mapping: {', '.join(sorted(missing))}")

    # Le ctx legacy doit rester présent derrière le pont : c'est précisément ce que
    # l'ancien diagnostic confondait avec la callback slash publique.
    for target in targets:
        legacy_params = _callback_parameters(target.command.callback)
        if not legacy_params or legacy_params[0].name != "ctx":
            errors.append(f"cible legacy {target.original_name!r}: ctx interne attendu")

    # Test négatif : le détecteur doit réellement refuser un ctx PUBLIC.
    async def leaked_ctx(ctx: discord.Interaction) -> None:
        return None

    leaked = app_commands.Command(
        name="leaked-ctx",
        description="Commande volontairement invalide pour le gate V99.",
        callback=leaked_ctx,
    )
    leaked_audit = audit_public_callback(leaked)
    if leaked_audit.ok:
        errors.append("le détecteur V99 accepte à tort un ctx exposé publiquement")

    if errors:
        for error in errors:
            print("[ERROR]", error)
        print(f"ECHEC V99: {len(errors)} problème(s)")
        return 1

    print("OK V99: /setup expose interaction; ctx legacy reste interne au pont V95.")
    print("OK V99: ai, ai-translate, modération, permissions et tickets ont une callback publique valide.")
    print("OK V99: le contrôle négatif rejette bien un ctx exposé publiquement.")
    print("Mappings représentatifs:")
    for path, meta in sorted(report.items()):
        print(f"  {path} <- {meta['original']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
