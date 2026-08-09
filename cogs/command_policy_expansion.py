"""Classification runtime des commandes transversales SentriX.

Certaines commandes sont ajoutées dynamiquement et n'appartiennent donc pas directement à
un Cog Discord. Cette couche les rattache explicitement aux catégories de +help et à la
politique fail-closed de main.py, sans modifier leur callback ni leur sécurité réelle.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import replace

from . import help_complete

logger = logging.getLogger("bot.command-policy-expansion")
_INSTALLED = False

ROOTS_BY_CATEGORY = {
    "economy": {"economy-system"},
    "levels": {"level-system"},
    "security": {"security", "antigif", "panic", "security-repair"},
    "stats": {"health"},
    "configuration": {"suivi-bot"},
}

MAIN_CATEGORY_ADDITIONS = {
    "securite": {"security", "antigif", "panic", "security-repair", "health"},
    "economie": {"economy-system", "level-system"},
    "configuration": {"suivi-bot"},
}


def _patch_help_categories() -> None:
    categories = []
    changed = False
    for category in help_complete.CATEGORIES:
        additions = ROOTS_BY_CATEGORY.get(category.key)
        if additions:
            merged = frozenset(set(category.roots) | additions)
            if merged != category.roots:
                category = replace(category, roots=merged)
                changed = True
        categories.append(category)
    if changed:
        help_complete.CATEGORIES = tuple(categories)
        help_complete.CATEGORY_BY_KEY = {
            category.key: category for category in help_complete.CATEGORIES
        }


def _patch_main_module(module) -> None:
    categories = getattr(module, "CATEGORY_COMMANDS", None)
    if not isinstance(categories, dict):
        return
    for category, names in MAIN_CATEGORY_ADDITIONS.items():
        existing = set(categories.get(category, frozenset()))
        categories[category] = frozenset(existing | names)

    known = getattr(module, "KNOWN_PERMISSION_COMMANDS", frozenset())
    module.KNOWN_PERMISSION_COMMANDS = frozenset(
        set(known) | set().union(*MAIN_CATEGORY_ADDITIONS.values())
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        # main peut être importé sous un nom différent selon CI/production : même après le
        # premier passage, on resynchronise les modules présents sans refaire le patch help.
        for name in ("main", "__main__"):
            module = sys.modules.get(name)
            if module is not None:
                _patch_main_module(module)
        return
    _INSTALLED = True
    _patch_help_categories()
    for name in ("main", "__main__"):
        module = sys.modules.get(name)
        if module is not None:
            _patch_main_module(module)
    logger.info("Classification SentriX étendue : systèmes, Security V2, health et suivi classés.")
