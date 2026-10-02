"""Audit canonique de la surface de commandes SentriX.

Ce module ne renomme rien et ne patche aucun runtime. Il inspecte uniquement la
surface deja construite afin que le CI et les diagnostics puissent refuser les
regressions structurelles avant synchronisation Discord.

Les controles critiques couvrent les invariants produits par la refonte slash :
chemins uniques, limites Discord, options internes jamais exposees et absence des
anciens groupes generiques (more/extra/misc/page-N). Les autres anomalies sont
retournees comme avertissements pour rester utiles sans casser la compatibilite
des anciennes commandes prefixees +.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Iterable

import discord

_INTERNAL_OPTIONS = frozenset({"ctx", "context", "self", "args", "kwargs"})
_FORBIDDEN_SEGMENT_RE = re.compile(
    r"^(?:more|extra|misc|other|general|page(?:-\d+)?|more-\d+|extra-\d+)$",
    re.IGNORECASE,
)
_MAX_ROOTS = 100
_MAX_CHILDREN = 25
_MAX_SLASH_SEGMENT = 32
_MAX_DESCRIPTION = 100


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    code: str
    path: str
    detail: str

    @property
    def critical(self) -> bool:
        return self.severity == "critical"


@dataclass(frozen=True)
class SlashEntry:
    path: str
    node: Any
    callback_key: tuple[str, str] | None
    is_group: bool


def _unwrap_callback(callback: Any) -> Any:
    current = callback
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is None:
            break
        current = wrapped
    return current


def callback_key(callback: Any) -> tuple[str, str] | None:
    callback = _unwrap_callback(callback)
    if callback is None:
        return None
    module = str(getattr(callback, "__module__", "") or "")
    qualname = str(getattr(callback, "__qualname__", "") or "")
    if not module and not qualname:
        return None
    return module, qualname


def _slash_children(node: Any) -> list[Any]:
    children = getattr(node, "commands", None)
    if children is None:
        return []
    try:
        return list(children)
    except TypeError:
        return []


def iter_slash_entries(bot: Any) -> list[SlashEntry]:
    tree = getattr(bot, "tree", None)
    if tree is None:
        return []
    getter = getattr(tree, "get_commands", None)
    if not callable(getter):
        return []
    try:
        roots = list(getter(type=discord.AppCommandType.chat_input))
    except TypeError:
        roots = list(getter())

    entries: list[SlashEntry] = []

    def walk(node: Any, parent: str = "") -> None:
        name = str(getattr(node, "name", "") or "").strip()
        path = f"{parent} {name}".strip()
        children = _slash_children(node)
        entries.append(
            SlashEntry(
                path=path,
                node=node,
                callback_key=callback_key(getattr(node, "callback", None)),
                is_group=bool(children),
            )
        )
        for child in children:
            walk(child, path)

    for root in roots:
        walk(root)
    return entries


def _slash_parameter_names(node: Any) -> list[str]:
    params = getattr(node, "parameters", None)
    if params is not None:
        try:
            values = list(params)
        except TypeError:
            values = []
        names = [
            str(getattr(param, "name", "") or "").strip()
            for param in values
            if str(getattr(param, "name", "") or "").strip()
        ]
        if names:
            return names

    callback = _unwrap_callback(getattr(node, "callback", None))
    if callback is None:
        return []
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return []
    return [
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind
        not in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
    ]


def _prefix_commands(bot: Any) -> list[Any]:
    walker = getattr(bot, "walk_commands", None)
    if not callable(walker):
        return []
    try:
        return list(walker())
    except TypeError:
        return []


def _description(node: Any) -> str:
    return str(
        getattr(node, "description", "")
        or getattr(node, "help", "")
        or ""
    ).strip()


def _prefix_scope(command: Any) -> str:
    parent = getattr(command, "parent", None)
    if parent is None:
        return "<root>"
    return str(getattr(parent, "qualified_name", "") or getattr(parent, "name", "") or "<root>").casefold()


def _prefix_tokens(command: Any) -> list[str]:
    values = [str(getattr(command, "name", "") or "").strip()]
    values.extend(str(alias).strip() for alias in (getattr(command, "aliases", None) or ()))
    return [value.casefold() for value in values if value]


def audit_command_registry(
    bot: Any,
    *,
    allowed_callback_duplicates: Iterable[tuple[str, str]] = (),
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    allowed = set(allowed_callback_duplicates)
    entries = iter_slash_entries(bot)
    prefix = _prefix_commands(bot)

    roots = [entry for entry in entries if " " not in entry.path]
    if len(roots) > _MAX_ROOTS:
        issues.append(
            AuditIssue(
                "critical",
                "slash-root-limit",
                "/",
                f"{len(roots)} racines publiees pour une limite Discord de {_MAX_ROOTS}.",
            )
        )

    by_path: dict[str, list[SlashEntry]] = {}
    by_callback: dict[tuple[str, str], list[SlashEntry]] = {}
    for entry in entries:
        normalized_path = entry.path.casefold().strip()
        by_path.setdefault(normalized_path, []).append(entry)
        if entry.callback_key is not None and not entry.is_group:
            by_callback.setdefault(entry.callback_key, []).append(entry)

        segment = entry.path.rsplit(" ", 1)[-1]
        if len(segment) > _MAX_SLASH_SEGMENT:
            issues.append(
                AuditIssue(
                    "critical",
                    "slash-name-too-long",
                    f"/{entry.path}",
                    f"Le segment {segment!r} depasse {_MAX_SLASH_SEGMENT} caracteres.",
                )
            )
        if _FORBIDDEN_SEGMENT_RE.fullmatch(segment):
            issues.append(
                AuditIssue(
                    "critical",
                    "legacy-generic-name",
                    f"/{entry.path}",
                    f"Le segment generique {segment!r} ne doit plus etre public.",
                )
            )

        children = _slash_children(entry.node)
        if len(children) > _MAX_CHILDREN:
            issues.append(
                AuditIssue(
                    "critical",
                    "slash-group-limit",
                    f"/{entry.path}",
                    f"{len(children)} enfants pour une limite Discord de {_MAX_CHILDREN}.",
                )
            )

        description = _description(entry.node)
        if not entry.is_group and not description:
            issues.append(
                AuditIssue(
                    "warning",
                    "slash-description-empty",
                    f"/{entry.path}",
                    "La commande slash n'a pas de description.",
                )
            )
        if len(description) > _MAX_DESCRIPTION:
            issues.append(
                AuditIssue(
                    "critical",
                    "slash-description-too-long",
                    f"/{entry.path}",
                    f"Description de {len(description)} caracteres (maximum {_MAX_DESCRIPTION}).",
                )
            )

        for option in _slash_parameter_names(entry.node):
            if option.casefold() in _INTERNAL_OPTIONS:
                issues.append(
                    AuditIssue(
                        "critical",
                        "internal-option-exposed",
                        f"/{entry.path}",
                        f"L'option interne {option!r} est exposee a Discord.",
                    )
                )

    for normalized, duplicates in by_path.items():
        if len(duplicates) > 1:
            issues.append(
                AuditIssue(
                    "critical",
                    "duplicate-slash-path",
                    f"/{duplicates[0].path}",
                    f"Le chemin est publie {len(duplicates)} fois.",
                )
            )

    for key, duplicates in by_callback.items():
        if len(duplicates) > 1 and key not in allowed:
            paths = ", ".join(f"/{entry.path}" for entry in duplicates)
            issues.append(
                AuditIssue(
                    "critical",
                    "duplicate-slash-callback",
                    paths,
                    "Le meme callback metier est expose sous plusieurs chemins slash.",
                )
            )

    slash_callback_keys = {
        entry.callback_key
        for entry in entries
        if entry.callback_key is not None and not entry.is_group
    }
    prefix_callback_keys: dict[tuple[str, str], list[Any]] = {}
    prefix_tokens: dict[tuple[str, str], list[Any]] = {}
    for command in prefix:
        key = callback_key(getattr(command, "callback", None))
        if key is not None:
            prefix_callback_keys.setdefault(key, []).append(command)

        scope = _prefix_scope(command)
        for token in _prefix_tokens(command):
            prefix_tokens.setdefault((scope, token), []).append(command)

        name = str(getattr(command, "name", "") or "")
        aliases = [
            str(alias).casefold().strip()
            for alias in (getattr(command, "aliases", None) or ())
            if str(alias).strip()
        ]
        if name and name.casefold() in aliases:
            issues.append(
                AuditIssue(
                    "warning",
                    "useless-self-alias",
                    f"+{getattr(command, 'qualified_name', name)}",
                    "Un alias est identique au nom de la commande.",
                )
            )
        if len(aliases) != len(set(aliases)):
            issues.append(
                AuditIssue(
                    "warning",
                    "duplicate-prefix-alias",
                    f"+{getattr(command, 'qualified_name', name)}",
                    "La liste d'alias contient des doublons.",
                )
            )

        if not bool(getattr(command, "hidden", False)) and not _description(command):
            issues.append(
                AuditIssue(
                    "warning",
                    "prefix-description-empty",
                    f"+{getattr(command, 'qualified_name', name)}",
                    "La commande visible n'a pas de description.",
                )
            )

        if bool(getattr(command, "hidden", False)) and key in slash_callback_keys:
            issues.append(
                AuditIssue(
                    "critical",
                    "hidden-command-still-slash",
                    f"+{getattr(command, 'qualified_name', name)}",
                    "La commande prefixee est masquee mais son callback reste publie en slash.",
                )
            )

    for (scope, token), commands_with_token in prefix_tokens.items():
        identities = {
            str(getattr(command, "qualified_name", getattr(command, "name", "")) or "")
            for command in commands_with_token
        }
        if len(identities) > 1:
            issues.append(
                AuditIssue(
                    "warning",
                    "prefix-token-collision",
                    f"{scope}:{token}",
                    "Le meme nom/alias prefixe pointe vers plusieurs commandes : "
                    + ", ".join(sorted(identities, key=str.casefold)),
                )
            )

    for entry in entries:
        if entry.is_group or entry.callback_key is None:
            continue
        if entry.callback_key not in prefix_callback_keys:
            issues.append(
                AuditIssue(
                    "warning",
                    "slash-without-prefix-business-command",
                    f"/{entry.path}",
                    "Aucune commande metier prefixee associee n'a ete trouvee.",
                )
            )

    return issues


def critical_issues(issues: Iterable[AuditIssue]) -> list[AuditIssue]:
    return [issue for issue in issues if issue.critical]


def audit_counts(issues: Iterable[AuditIssue]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


def assert_registry_clean(
    bot: Any,
    *,
    allowed_callback_duplicates: Iterable[tuple[str, str]] = (),
) -> list[AuditIssue]:
    issues = audit_command_registry(
        bot,
        allowed_callback_duplicates=allowed_callback_duplicates,
    )
    critical = critical_issues(issues)
    if critical:
        summary = "\n".join(
            f"[{issue.code}] {issue.path}: {issue.detail}" for issue in critical
        )
        raise AssertionError(f"Audit du registre SentriX en echec:\n{summary}")
    return issues


__all__ = [
    "AuditIssue",
    "SlashEntry",
    "assert_registry_clean",
    "audit_command_registry",
    "audit_counts",
    "callback_key",
    "critical_issues",
    "iter_slash_entries",
]
