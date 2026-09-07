"""SentriX V99 — audit déterministe des callbacks slash et du bootstrap Railway.

Le runtime SentriX expose trois formes différentes qu'il ne faut pas confondre :

- une ``app_commands.Command`` native reçoit directement ``discord.Interaction`` ;
- une ``HybridAppCommand`` discord.py conserve légitimement un callback métier ``ctx``
  car discord.py transforme lui-même l'Interaction en Context avant l'appel ;
- les commandes legacy regroupées par V95/V98 reçoivent publiquement ``interaction`` puis
  passent en interne par ``commands.Context``.

V99 audite ces trois contrats séparément et verrouille aussi le véritable point d'entrée
Railway afin que V95/V97/V98/V96 soient installées avant la synchronisation Discord.
Aucun token ni appel réseau Discord n'est nécessaire.
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
import sentrix_v97_reliability as v97
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


def _annotation_matches(annotation: object, expected_type: type, *names: str) -> bool:
    if annotation is expected_type:
        return True
    if annotation is inspect.Parameter.empty:
        return False
    name = getattr(annotation, "__name__", None)
    if name in names:
        return True
    text = str(annotation).replace("typing.", "").strip("'\"")
    return text in set(names)


def _is_interaction_annotation(annotation: object) -> bool:
    return _annotation_matches(
        annotation,
        discord.Interaction,
        "Interaction",
        "discord.Interaction",
        "<class 'discord.interactions.Interaction'>",
    )


def _is_context_annotation(annotation: object) -> bool:
    return _annotation_matches(
        annotation,
        commands.Context,
        "Context",
        "commands.Context",
        "discord.ext.commands.Context",
        "<class 'discord.ext.commands.context.Context'>",
    )


def _is_hybrid_app_command(command: object) -> bool:
    """Détecte le wrapper officiel discord.py sans dépendre d'une classe privée."""

    return bool(getattr(command, "__commands_is_hybrid_app_command__", False))


def audit_public_callback(command: app_commands.Command) -> CallbackAudit:
    """Audite la signature selon le type réel de commande Discord.

    ``ctx`` est interdit sur une App Command native mais attendu sur une HybridAppCommand :
    discord.py possède alors son propre pont Interaction -> Context. Les wrappers V95/V98,
    eux, sont des App Commands natives et doivent donc toujours exposer ``interaction``.
    """

    qualified = str(getattr(command, "qualified_name", None) or getattr(command, "name", "?"))
    callback = getattr(command, "callback", None)
    parameters = _callback_parameters(callback)
    if not parameters:
        return CallbackAudit(qualified, False, None, "callback publique sans premier paramètre exploitable")

    first = parameters[0]
    first_name = first.name.casefold()
    hybrid = _is_hybrid_app_command(command)

    if hybrid:
        if first_name in LEGACY_CONTEXT_NAMES or _is_context_annotation(first.annotation):
            return CallbackAudit(
                qualified,
                True,
                first.name,
                "HybridAppCommand valide : discord.py transforme Interaction en Context",
            )
        if first_name in INTERACTION_NAMES or _is_interaction_annotation(first.annotation):
            return CallbackAudit(
                qualified,
                True,
                first.name,
                "HybridAppCommand avec paramètre Interaction identifiable",
            )
        return CallbackAudit(
            qualified,
            False,
            first.name,
            "HybridAppCommand sans Context/Interaction identifiable",
        )

    if first_name in LEGACY_CONTEXT_NAMES or _is_context_annotation(first.annotation):
        return CallbackAudit(
            qualified,
            False,
            first.name,
            f"App Command native expose un Context legacy via {first.name!r}",
        )

    if first_name not in INTERACTION_NAMES and not _is_interaction_annotation(first.annotation):
        return CallbackAudit(
            qualified,
            False,
            first.name,
            "premier paramètre natif non identifiable comme discord.Interaction",
        )

    return CallbackAudit(
        qualified,
        True,
        first.name,
        "App Command native Interaction valide",
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


def bootstrap_contract_errors(root: Path = ROOT) -> list[str]:
    """Valide le chemin de démarrage réellement utilisé par Railway/Docker.

    Le contrat interdit de dépendre uniquement de ``sitecustomize`` pour les correctifs
    slash critiques. Le bootstrap normal doit reproduire les garanties déjà présentes sur
    l'entrypoint HA produit, avant la création du bot et avant ``CommandTree.sync``.
    """

    errors: list[str] = []
    required_files = {
        "Procfile": root / "Procfile",
        "Dockerfile": root / "Dockerfile",
        "sentrix_v98_boot.py": root / "sentrix_v98_boot.py",
    }
    texts: dict[str, str] = {}
    for label, path in required_files.items():
        try:
            texts[label] = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{label} illisible: {type(exc).__name__}")

    procfile = texts.get("Procfile", "")
    dockerfile = texts.get("Dockerfile", "")
    source = texts.get("sentrix_v98_boot.py", "")

    if "sentrix_v98_boot.py" not in procfile:
        errors.append("Procfile ne démarre pas sentrix_v98_boot.py")
    if "sentrix_v98_boot.py" not in dockerfile:
        errors.append("Dockerfile ne démarre pas sentrix_v98_boot.py")

    required_tokens = (
        "install_v95()",
        "import railway_boot as runtime_boot",
        "install_v97(runtime_boot.dashboard_web)",
        "install_v98()",
        "install_v96()",
        "install_v96_finalizer()",
        "asyncio.run(runtime_boot.run())",
    )
    for token in required_tokens:
        if token not in source:
            errors.append(f"bootstrap Railway incomplet: {token!r} absent")

    def before(first: str, second: str, message: str) -> None:
        first_pos = source.find(first)
        second_pos = source.find(second)
        if first_pos < 0 or second_pos < 0:
            return
        if first_pos >= second_pos:
            errors.append(message)

    before(
        "install_v95()",
        "import railway_boot as runtime_boot",
        "V95 doit être installée avant l'import du bootstrap Railway",
    )
    before(
        "import railway_boot as runtime_boot",
        "install_v96()",
        "V96 doit patcher la vraie classe Bot après l'import de railway_boot",
    )
    before(
        "install_v97(runtime_boot.dashboard_web)",
        "install_v98()",
        "V97 doit fiabiliser le bridge avant que V98 ne fige la surface sémantique",
    )

    return errors


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
    """Reproduit les trois chemins slash critiques sans token ni réseau Discord."""

    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

    @bot.hybrid_command(name="setup", description="Configuration SentriX.")
    async def legacy_setup(ctx: commands.Context) -> None:
        return None

    # Racine directe distincte du help_command fourni par défaut par commands.Bot.
    @bot.hybrid_command(name="sentrix", description="Assistant SentriX.")
    async def hybrid_sentrix(ctx: commands.Context) -> None:
        return None

    # Le /setup hybride historique est volontairement remplacé par V97. /sentrix reste
    # hybride afin que l'audit vérifie aussi le comportement officiel discord.py.
    if not v97._replace_setup_slash(bot):
        raise RuntimeError("Gate V99: impossible de remplacer /setup via V97")

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
        errors.append(f"/setup invalide: {setup_audit.reason}")
    elif setup_audit.first_parameter != "interaction":
        errors.append(f"/setup expose {setup_audit.first_parameter!r} au lieu de 'interaction' après V97")

    hybrid_audit = by_name.get("sentrix")
    if hybrid_audit is None:
        errors.append("/sentrix hybride a disparu de la surface publique")
    elif not hybrid_audit.ok:
        errors.append(f"/sentrix hybride rejeté à tort: {hybrid_audit.reason}")
    elif hybrid_audit.first_parameter not in LEGACY_CONTEXT_NAMES:
        errors.append(f"/sentrix hybride n'expose plus son Context attendu: {hybrid_audit.first_parameter!r}")

    for audit in audits:
        if not audit.ok:
            errors.append(f"/{audit.qualified_name}: {audit.reason}")

    expected_originals = {"ai", "ai-translate", "ban", "permission-audit", "ticketpanel"}
    mapped_originals = {str(meta.get("original")) for meta in report.values()}
    missing = expected_originals - mapped_originals
    if missing:
        errors.append(f"familles V99 absentes du mapping: {', '.join(sorted(missing))}")

    # Les commandes legacy V95/V98 gardent ctx uniquement derrière leur wrapper public.
    for target in targets:
        legacy_params = _callback_parameters(target.command.callback)
        if not legacy_params or legacy_params[0].name != "ctx":
            errors.append(f"cible legacy {target.original_name!r}: ctx interne attendu")

    # Contrôle négatif : un vrai App Command natif ne doit jamais exposer ctx.
    async def leaked_ctx(ctx: discord.Interaction) -> None:
        return None

    leaked = app_commands.Command(
        name="leaked-ctx",
        description="Commande volontairement invalide pour le gate V99.",
        callback=leaked_ctx,
    )
    leaked_audit = audit_public_callback(leaked)
    if leaked_audit.ok:
        errors.append("le détecteur V99 accepte à tort un ctx sur une App Command native")

    errors.extend(bootstrap_contract_errors())

    if errors:
        for error in errors:
            print("[ERROR]", error)
        print(f"ECHEC V99: {len(errors)} problème(s)")
        return 1

    print("OK V99: /setup V97 expose Interaction et les HybridAppCommand ctx restent valides.")
    print("OK V99: wrappers V95/V98 Interaction -> Context valides pour IA, modération, permissions et tickets.")
    print("OK V99: Procfile + Dockerfile verrouillent le bootstrap Railway V95/V97/V98/V96.")
    print("OK V99: le contrôle négatif rejette un ctx sur une App Command native.")
    print("Mappings représentatifs:")
    for path, meta in sorted(report.items()):
        print(f"  {path} <- {meta['original']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
