"""Compléments obligatoires pour +create-server.

Tous les modèles de serveur doivent inclure :
- un espace de logs complet et privé ;
- un espace de modération privé dédié.

Le patch modifie uniquement les modèles en mémoire avant l'ouverture de l'assistant
+create-server. L'installation reste idempotente et ne crée jamais deux catégories
LOGS/MODÉRATION dans un même modèle.
"""

from __future__ import annotations

import copy
import logging

from discord.ext import commands

logger = logging.getLogger("bot.server-builder-moderation-space")


MODERATION_CATEGORY = {
    "name": "MODÉRATION",
    "privacy": "staff",
    "channels": [
        ("modération-général", "text"),
        ("mise-en-surveillance", "text"),
        ("preuves-modération", "text"),
        ("dossiers-modération", "text"),
        ("réunion-modération", "voice"),
    ],
}


def _has_category(categories: list[dict], name: str) -> bool:
    wanted = name.casefold().strip()
    return any(str(category.get("name", "")).casefold().strip() == wanted for category in categories)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_server_builder_moderation_space", False):
        return

    try:
        from . import server_builder
    except Exception:
        logger.exception("ServerBuilder indisponible pour le patch LOGS/MODÉRATION.")
        return

    # Enrichit aussi l'affichage et les sujets des nouveaux salons.
    server_builder.CATEGORY_EMOJIS.setdefault("MODÉRATION", "🛡️")
    server_builder.CHANNEL_EMOJIS.update({
        "modération-général": "🛡️",
        "mise-en-surveillance": "👁️",
        "preuves-modération": "📂",
        "dossiers-modération": "📋",
        "réunion-modération": "🔊",
    })
    server_builder.CHANNEL_TOPICS.update({
        "modération-général": "Coordination privée de l'équipe de modération.",
        "mise-en-surveillance": "Suivi interne des membres placés sous surveillance.",
        "preuves-modération": "Preuves utiles aux sanctions et interventions du staff.",
        "dossiers-modération": "Dossiers internes et suivi des situations de modération.",
        "réunion-modération": "Salon vocal privé réservé à l'équipe de modération.",
    })

    log_category = copy.deepcopy(server_builder._base_category("LOGS"))

    changed = 0
    for template in server_builder.SERVER_TEMPLATES.values():
        categories = template.get("categories")
        if not isinstance(categories, list):
            continue

        if not _has_category(categories, "LOGS"):
            categories.append(copy.deepcopy(log_category))
            changed += 1

        if not _has_category(categories, "MODÉRATION"):
            categories.append(copy.deepcopy(MODERATION_CATEGORY))
            changed += 1

    bot._sentrix_server_builder_moderation_space = True
    logger.info(
        "+create-server renforcé : LOGS et MODÉRATION garantis sur tous les modèles (%s ajout(s)).",
        changed,
    )
