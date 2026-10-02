"""Verification post-sync de la surface slash réellement acceptée par Discord.

Contrairement aux audits locaux, cette couche reçoit le résultat de
CommandTree.sync(): les objets correspondent donc aux commandes renvoyées par
l'API Discord après publication. Elle ne modifie aucune commande et ne relance
aucune synchronisation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PublishAudit:
    local_paths: tuple[str, ...]
    remote_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    unexpected_paths: tuple[str, ...]
    musique_paths: tuple[str, ...]
    legacy_music_paths: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not self.missing_paths and not self.unexpected_paths


def _option_type_value(value: Any) -> int | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _children(node: Any, *, remote: bool) -> list[Any]:
    if remote:
        candidates = getattr(node, "options", None)
        if candidates is None:
            candidates = getattr(node, "commands", None)
        try:
            values = list(candidates or ())
        except TypeError:
            return []
        result = []
        for child in values:
            option_type = _option_type_value(getattr(child, "type", None))
            nested = bool(getattr(child, "options", None) or getattr(child, "commands", None))
            if option_type in {1, 2} or option_type is None or nested:
                result.append(child)
        return result

    try:
        return list(getattr(node, "commands", None) or ())
    except TypeError:
        return []


def _flatten(nodes: Iterable[Any], *, remote: bool) -> tuple[str, ...]:
    paths: list[str] = []

    def walk(node: Any, parent: str = "") -> None:
        name = str(getattr(node, "name", "") or "").strip()
        if not name:
            return
        path = f"{parent} {name}".strip()
        paths.append(path)
        for child in _children(node, remote=remote):
            walk(child, path)

    for node in nodes:
        walk(node)
    return tuple(sorted(set(paths), key=str.casefold))


def local_command_paths(tree: Any) -> tuple[str, ...]:
    getter = getattr(tree, "get_commands", None)
    if not callable(getter):
        return ()
    try:
        roots = list(getter())
    except TypeError:
        roots = []
    return _flatten(roots, remote=False)


def remote_command_paths(synced: Iterable[Any]) -> tuple[str, ...]:
    return _flatten(synced, remote=True)


def audit_published_commands(tree: Any, synced: Iterable[Any]) -> PublishAudit:
    local = local_command_paths(tree)
    remote = remote_command_paths(synced)
    local_set = set(local)
    remote_set = set(remote)

    # Certaines versions de discord.py matérialisent seulement les racines
    # dans la réponse REST de sync(). Dans ce cas on compare les racines sans
    # inventer de faux écarts sur les sous-commandes.
    remote_has_nested = any(" " in path for path in remote)
    if remote_has_nested:
        comparable_local = local_set
        comparable_remote = remote_set
    else:
        comparable_local = {path for path in local_set if " " not in path}
        comparable_remote = remote_set

    musique = tuple(
        path for path in remote
        if path.casefold() == "musique" or path.casefold().startswith("musique ")
    )
    legacy_music = tuple(
        path for path in remote
        if path.casefold() == "music" or path.casefold().startswith("music ")
    )

    return PublishAudit(
        local_paths=local,
        remote_paths=remote,
        missing_paths=tuple(sorted(comparable_local - comparable_remote, key=str.casefold)),
        unexpected_paths=tuple(sorted(comparable_remote - comparable_local, key=str.casefold)),
        musique_paths=musique,
        legacy_music_paths=legacy_music,
    )


__all__ = [
    "PublishAudit",
    "audit_published_commands",
    "local_command_paths",
    "remote_command_paths",
]
