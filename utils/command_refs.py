"""Écrire une commande dans un texte : la forme que le membre peut vraiment taper.

Les textes collaient ``ctx.clean_prefix`` devant le nom préfixé. En « / », cela
donnait ``/jeuxjour`` ou ``/infinit resume`` : des commandes qui n'existent pas
dans le menu. Ici : le chemin du catalogue (utils/slash_catalog.py) quand la
commande en cours vient de « / » et que la cible y est publiée, sinon la forme
``+``, qui marche toujours.
"""
from __future__ import annotations

from typing import Any

_CHEMINS: dict[str, str] | None = None


def _chemins() -> dict[str, str]:
    global _CHEMINS
    if _CHEMINS is None:
        from utils import slash_catalog

        _CHEMINS = {entree.source: entree.path for entree in slash_catalog.CATALOG}
    return _CHEMINS


def reference(ctx: Any, source: str, suite: str = "", *, nom_prefixe: str | None = None) -> str:
    """``source`` : nom de la commande préfixée (qualified_name) ; ``suite`` : arguments."""
    en_slash = getattr(ctx, "interaction", None) is not None
    chemin = _chemins().get(source) if en_slash else None
    if chemin:
        base = "/" + chemin
    else:
        prefixe = getattr(ctx, "clean_prefix", None)
        if en_slash or not isinstance(prefixe, str) or not prefixe or prefixe == "/":
            prefixe = "+"
        base = prefixe + (nom_prefixe or source)
    return f"{base} {suite}".rstrip()


__all__ = ["reference"]
