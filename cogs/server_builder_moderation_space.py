"""Catégories internes obligatoires pour +create-server.

Quel que soit le modèle choisi, SentriX garantit désormais :
- une catégorie STAFF privée complète ;
- une catégorie MODÉRATION privée complète ;
- une catégorie LOGS privée complète.

Le correctif est réappliqué juste avant l'aperçu et juste avant la construction du serveur,
afin qu'une autre couche runtime ne puisse plus retirer ces catégories par accident.
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


def _normalise(value: str) -> str:
    return str(value or "").casefold().strip()


def _find_category(categories: list[dict], name: str) -> dict | None:
    wanted = _normalise(name)
    return next(
        (category for category in categories if _normalise(category.get("name")) == wanted),
        None,
    )


def _merge_required_category(categories: list[dict], required: dict) -> int:
    """Ajoute la catégorie ou complète les salons qui lui manquent."""
    existing = _find_category(categories, required["name"])
    if existing is None:
        categories.append(copy.deepcopy(required))
        return 1

    changed = 0
    # Ces trois espaces doivent toujours être invisibles aux membres classiques.
    if existing.get("privacy") != "staff":
        existing["privacy"] = "staff"
        changed += 1

    channels = existing.setdefault("channels", [])
    existing_names = {_normalise(name) for name, _kind in channels}
    for channel in required.get("channels", []):
        if _normalise(channel[0]) not in existing_names:
            channels.append(copy.deepcopy(channel))
            existing_names.add(_normalise(channel[0]))
            changed += 1
    return changed


def _ensure_required_spaces(server_builder) -> int:
    """Répare tous les modèles en mémoire et retourne le nombre de corrections."""
    staff_category = copy.deepcopy(server_builder._base_category("STAFF"))
    logs_category = copy.deepcopy(server_builder._base_category("LOGS"))

    changed = 0
    for template in server_builder.SERVER_TEMPLATES.values():
        categories = template.get("categories")
        if not isinstance(categories, list):
            categories = []
            template["categories"] = categories
            changed += 1

        changed += _merge_required_category(categories, staff_category)
        changed += _merge_required_category(categories, MODERATION_CATEGORY)
        changed += _merge_required_category(categories, logs_category)
    return changed


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_server_builder_moderation_space_v2", False):
        return

    try:
        from . import server_builder
    except Exception:
        logger.exception("ServerBuilder indisponible pour le correctif STAFF/MODÉRATION/LOGS.")
        return

    # Affichage et sujets des salons ajoutés par le correctif.
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

    changed = _ensure_required_spaces(server_builder)

    # Garantie supplémentaire : on répare à nouveau au moment exact où +create-server
    # affiche son aperçu puis au moment où il commence réellement l'installation.
    original_preview = server_builder.ServerBuilderView.build_preview_embed
    if not getattr(original_preview, "_sentrix_required_spaces", False):
        def build_preview_embed(self, *args, **kwargs):
            _ensure_required_spaces(server_builder)
            return original_preview(self, *args, **kwargs)

        build_preview_embed._sentrix_required_spaces = True
        server_builder.ServerBuilderView.build_preview_embed = build_preview_embed

    original_build_server = server_builder.ServerBuilder.build_server
    if not getattr(original_build_server, "_sentrix_required_spaces", False):
        async def build_server(self, guild, template_key, author, *args, **kwargs):
            _ensure_required_spaces(server_builder)
            return await original_build_server(
                self,
                guild,
                template_key,
                author,
                *args,
                **kwargs,
            )

        build_server._sentrix_required_spaces = True
        server_builder.ServerBuilder.build_server = build_server

    bot._sentrix_server_builder_moderation_space_v2 = True
    # Ancien marqueur conservé pour les autres couches qui le consultent encore.
    bot._sentrix_server_builder_moderation_space = True
    logger.info(
        "+create-server V2 : STAFF, MODÉRATION et LOGS privés garantis (%s correction(s) initiale(s)).",
        changed,
    )
