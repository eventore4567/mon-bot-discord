"""Attribution d'une exception runtime au module SentriX qui l'a provoquée."""
from __future__ import annotations

from types import TracebackType
from typing import Callable


def module_from_traceback(
    traceback_obj: TracebackType | None,
    *,
    known: Callable[[str], bool],
) -> str | None:
    """Retourne le dernier module cogs.* connu rencontré dans la trace."""
    matched: str | None = None
    current = traceback_obj
    while current is not None:
        module_name = str(current.tb_frame.f_globals.get("__name__", "") or "")
        if module_name.startswith("cogs.") and known(module_name):
            matched = module_name
        current = current.tb_next
    return matched
