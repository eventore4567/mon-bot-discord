"""Garantie forte des espaces internes de +create-server.

Cette couche ne se contente plus de modifier les modèles en mémoire : elle vérifie aussi
le serveur Discord réel après chaque construction et recrée les catégories/salons internes
manquants. Elle est idempotente et peut être appelée plusieurs fois sans doublon.
"""

from __future__ import annotations

import copy
import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.server-builder-required-spaces")


STAFF_CATEGORY = {
    "name": "STAFF",
    "privacy": "staff",
    "channels": [
        ("staff-général", "text"),
        ("staff-annonces", "readonly"),
        ("signalements", "text"),
        ("sanctions", "text"),
        ("tâches", "text"),
        ("réunions-staff", "text"),
        ("candidatures", "text"),
        ("Staff vocal", "voice"),
    ],
}

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

LOGS_CATEGORY = {
    "name": "LOGS",
    "privacy": "staff",
    "channels": [
        ("logs-serveur", "text"),
        ("logs-modération", "text"),
        ("logs-rôles", "text"),
        ("logs-tickets", "text"),
        ("logs-membres", "text"),
        ("logs-messages", "text"),
        ("logs-vocaux", "text"),
        ("logs-sécurité", "text"),
    ],
}

REQUIRED_CATEGORIES = (STAFF_CATEGORY, MODERATION_CATEGORY, LOGS_CATEGORY)


def _normalise(value: str) -> str:
    return str(value or "").casefold().strip()


def _find_template_category(categories: list[dict], name: str) -> dict | None:
    wanted = _normalise(name)
    return next(
        (category for category in categories if _normalise(category.get("name")) == wanted),
        None,
    )


def _merge_required_category(categories: list[dict], required: dict) -> int:
    """Ajoute la catégorie ou complète exactement les salons qui lui manquent."""
    existing = _find_template_category(categories, required["name"])
    if existing is None:
        categories.append(copy.deepcopy(required))
        return 1

    changed = 0
    if existing.get("privacy") != "staff":
        existing["privacy"] = "staff"
        changed += 1

    channels = existing.setdefault("channels", [])
    names = {_normalise(name) for name, _kind in channels}
    for channel in required["channels"]:
        if _normalise(channel[0]) not in names:
            channels.append(copy.deepcopy(channel))
            names.add(_normalise(channel[0]))
            changed += 1
    return changed


def _ensure_required_spaces(server_builder) -> int:
    """Répare tous les modèles +create-server en mémoire."""
    changed = 0
    for template in server_builder.SERVER_TEMPLATES.values():
        categories = template.get("categories")
        if not isinstance(categories, list):
            categories = []
            template["categories"] = categories
            changed += 1
        for required in REQUIRED_CATEGORIES:
            changed += _merge_required_category(categories, required)
    return changed


def _install_names_and_topics(server_builder) -> None:
    server_builder.CATEGORY_EMOJIS.setdefault("STAFF", "🔒")
    server_builder.CATEGORY_EMOJIS.setdefault("MODÉRATION", "🛡️")
    server_builder.CATEGORY_EMOJIS.setdefault("LOGS", "📋")
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


async def _repair_real_guild(server_builder, builder, guild: discord.Guild, template_key: str, author) -> dict:
    """Vérifie le serveur réel, pas seulement le modèle Python."""
    _ensure_required_spaces(server_builder)
    role_map = {role.name: role for role in guild.roles}
    required_data = {"categories": [copy.deepcopy(item) for item in REQUIRED_CATEGORIES]}
    reason = f"Réparation STAFF/MODÉRATION/LOGS +create-server demandée par {author}"

    (
        category_map,
        channel_map,
        categories_created,
        categories_updated,
        channels_created,
        channels_updated,
    ) = await builder._ensure_structure(
        guild,
        required_data,
        role_map,
        reason,
    )

    # Relie immédiatement les nouveaux salons de logs aux réglages SentriX.
    template = server_builder.SERVER_TEMPLATES.get(template_key, {})
    staff_role_name = template.get("staff_role_name", "Modérateur")
    try:
        await builder._configure_bot_channels(
            guild,
            role_map,
            category_map,
            channel_map,
            staff_role_name,
        )
    except Exception:
        logger.exception("Synchronisation des salons internes vers la configuration impossible sur %s", guild.id)

    return {
        "categories_created": categories_created,
        "categories_updated": categories_updated,
        "channels_created": channels_created,
        "channels_updated": channels_updated,
    }


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_server_builder_required_spaces_v3", False):
        return

    try:
        from . import server_builder
    except Exception:
        logger.exception("ServerBuilder indisponible pour la garantie STAFF/MODÉRATION/LOGS.")
        return

    _install_names_and_topics(server_builder)
    initial_changes = _ensure_required_spaces(server_builder)

    original_preview = server_builder.ServerBuilderView.build_preview_embed
    if not getattr(original_preview, "_sentrix_required_spaces_v3", False):
        def build_preview_embed(self, *args, **kwargs):
            _ensure_required_spaces(server_builder)
            return original_preview(self, *args, **kwargs)

        build_preview_embed._sentrix_required_spaces_v3 = True
        server_builder.ServerBuilderView.build_preview_embed = build_preview_embed

    original_build = server_builder.ServerBuilder.build_server
    if not getattr(original_build, "_sentrix_required_spaces_v3", False):
        async def build_server(self, guild, template_key, author, *args, **kwargs):
            _ensure_required_spaces(server_builder)
            result = None
            build_error = None
            try:
                result = await original_build(self, guild, template_key, author, *args, **kwargs)
            except Exception as exc:
                build_error = exc
            try:
                repaired = await _repair_real_guild(
                    server_builder,
                    self,
                    guild,
                    template_key,
                    author,
                )
                logger.info(
                    "+create-server audit réel sur %s : +%s catégorie(s), +%s salon(s), %s/%s mis à jour.",
                    guild.id,
                    repaired["categories_created"],
                    repaired["channels_created"],
                    repaired["categories_updated"],
                    repaired["channels_updated"],
                )
                if result is not None and (repaired["categories_created"] or repaired["channels_created"]):
                    try:
                        result.add_field(
                            name="Espaces internes vérifiés",
                            value=(
                                "STAFF, MODÉRATION et LOGS ont été contrôlés sur le serveur réel. "
                                f"{repaired['categories_created']} catégorie(s) et "
                                f"{repaired['channels_created']} salon(s) manquant(s) ont été recréés."
                            ),
                            inline=False,
                        )
                    except Exception:
                        pass
            except Exception:
                logger.exception("Audit/réparation réel de +create-server impossible sur %s", getattr(guild, "id", "?"))

            if build_error is not None:
                raise build_error
            return result

        build_server._sentrix_required_spaces_v3 = True
        server_builder.ServerBuilder.build_server = build_server

    bot._sentrix_server_builder_required_spaces_v3 = True
    bot._sentrix_server_builder_moderation_space_v2 = True
    bot._sentrix_server_builder_moderation_space = True
    logger.info(
        "+create-server V3 : STAFF, MODÉRATION et LOGS garantis dans les modèles ET audités sur le serveur réel (%s correction(s) initiale(s)).",
        initial_changes,
    )
