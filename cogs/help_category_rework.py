"""Classement canonique des commandes dans +help.

Cette couche corrige les catégories logiques sans déplacer les cogs ni changer les
permissions. Les commandes sont classées d'abord par leur nom fonctionnel, puis par le
cog auquel elles appartiennent. Les cogs mixtes (notamment Utility et Moderation) sont
ainsi répartis proprement au lieu d'envoyer toutes leurs commandes dans une seule rubrique.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.help-category-rework")
_INSTALLED = False

# Commandes ajoutées par des couches runtime qui n'appartiennent pas aux cogs historiques
# référencés dans help_complete.CATEGORIES.
EXACT_CATEGORY_OVERRIDES: dict[str, str] = {
    "security-repair": "security",
    "suivi-bot": "stats",
}

# Catégorie par défaut des cogs dédiés. Les règles exactes restent prioritaires : par
# exemple +ban est placé dans Sanctions même s'il vit dans le cog Moderation, et +say /
# +addemoji restent en Modération même s'ils vivent dans Utility.
COG_DEFAULT_CATEGORY: dict[str, str] = {
    "Ai": "ai",
    "Utility": "utility",
    "Economy": "economy",
    "ShopAdmin": "economy",
    "GamesEconomy": "economy",
    "Levels": "levels",
    "Minigames": "games",
    "Music": "music",
    "Events": "events",
    "Invites": "social",
    "Notifications": "social",
    "Tickets": "tickets",
    "Moderation": "moderation",
    "Automod": "security",
    "Security": "security",
    "SecurityHardening": "security",
    "SecurityCommandCenter": "security",
    "Configuration": "configuration",
    "GamesSetup": "configuration",
    "ServerBuilder": "server",
    "Verification": "roles",
    "EmbedBuilder": "embeds",
    "Design": "embeds",
    "Stats": "stats",
    "BotTracker": "stats",
    "Owner": "owner",
}


def _root_name(command) -> str:
    qualified = str(getattr(command, "qualified_name", "") or "").casefold().strip()
    return qualified.split(" ", 1)[0]


def _exact_category_map(help_complete) -> dict[str, str]:
    """Construit une table unique et détecte toute règle exacte contradictoire."""
    result: dict[str, str] = {}
    for category in help_complete.CATEGORIES:
        if category.key == "other":
            continue
        for root in category.roots:
            existing = result.get(root)
            if existing is not None and existing != category.key:
                raise RuntimeError(
                    f"Commande {root!r} classée à la fois dans {existing!r} et {category.key!r}."
                )
            result[root] = category.key
    for root, key in EXACT_CATEGORY_OVERRIDES.items():
        result[root.casefold()] = key
    return result


def install(bot: commands.Bot) -> None:
    """Remplace uniquement le moteur de classement de l'aide SentriX."""
    del bot  # Le classement s'applique aux fonctions déjà installées dans help_complete.
    global _INSTALLED
    if _INSTALLED:
        return

    from . import help_complete, utility

    exact_categories = _exact_category_map(help_complete)
    known_keys = set(help_complete.CATEGORY_BY_KEY)

    invalid_defaults = sorted(
        key for key in COG_DEFAULT_CATEGORY.values() if key not in known_keys
    )
    if invalid_defaults:
        raise RuntimeError(
            "Catégories de cog inconnues : " + ", ".join(invalid_defaults)
        )

    def category_for(command):
        root = _root_name(command)

        # 1) Le nom exact décrit le mieux la fonction réelle de la commande.
        exact_key = exact_categories.get(root)
        if exact_key:
            return help_complete.CATEGORY_BY_KEY[exact_key]

        # 2) Familles de commandes : giveaway-*, automod-*, ticket-*...
        for category in help_complete.CATEGORIES:
            if category.key == "other":
                continue
            if any(root.startswith(prefix) for prefix in category.prefixes):
                return category

        # 3) Cog dédié. Utility est volontairement Outils pratiques par défaut : seules
        # les commandes d'information ou de modération explicitement nommées en sortent.
        cog = getattr(command, "cog", None)
        cog_name = getattr(cog, "qualified_name", "") if cog else ""
        default_key = COG_DEFAULT_CATEGORY.get(cog_name)
        if default_key:
            return help_complete.CATEGORY_BY_KEY[default_key]

        return help_complete.CATEGORY_BY_KEY["other"]

    # Toutes les fonctions installées par help_complete résolvent ce global au moment de
    # l'appel. Remplacer _category_for suffit donc pour l'accueil, le menu, la recherche,
    # "Toutes les commandes" et chaque page de catégorie.
    help_complete._category_for = category_for
    utility.logical_category_for = category_for

    _INSTALLED = True
    logger.info(
        "Catégorisation +help rework activée : règles exactes, familles et cogs canoniques."
    )
