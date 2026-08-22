"""Assets visuels officiels de SentriX pour les réponses Discord.

Les images sont jointes au message puis référencées avec ``attachment://``. Cette
méthode fonctionne même lorsque le dépôt GitHub est privé et évite de dépendre d'un
hébergeur d'images externe. Chaque envoi ouvre un nouveau ``discord.File`` afin de
rester compatible avec les réponses simultanées.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import discord


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "sentrix"

CATEGORY_ASSETS: dict[str, str] = {
    "brand": "brand.png",
    "utility": "brand.png",
    "premium": "brand.png",
    "configuration": "configuration.png",
    "tickets": "tickets.png",
    "levels": "levels.png",
    "music": "music.png",
    "events": "events.png",
    "giveaways": "events.png",
    "invites": "invites.png",
    "logs": "logs.png",
    "profile": "profile.png",
    "shop": "shop.png",
    "leaderboard": "leaderboard.png",
    "security": "security.png",
    "ai": "ai.png",
    "moderation": "moderation.png",
    "games": "games.png",
    "economy": "economy.png",
}


def _asset_name(category: str | None) -> str:
    return CATEGORY_ASSETS.get(str(category or "").casefold(), "brand.png")


def _has_thumbnail(embed: discord.Embed) -> bool:
    thumbnail = getattr(embed, "thumbnail", None)
    return bool(getattr(thumbnail, "url", None))


def _has_remote_identity(embed: discord.Embed) -> bool:
    """Vrai lorsque l'embed affiche déjà une petite icône distante dans son auteur."""
    icon_url = getattr(getattr(embed, "author", None), "icon_url", None)
    return str(icon_url or "").startswith(("https://", "http://"))


def _file_name(file: Any) -> str:
    return str(getattr(file, "filename", "") or "")


def decorate_send_kwargs(
    kwargs: dict[str, Any],
    *,
    embed: discord.Embed | None,
    category: str | None,
) -> dict[str, Any]:
    """Ajoute l'icône de catégorie au premier embed sans écraser une miniature métier.

    Les profils de membres, produits de boutique ou autres miniatures déjà définies
    restent prioritaires. L'icône SentriX est ajoutée uniquement lorsqu'il reste une
    place parmi les dix pièces jointes acceptées par Discord.

    Les panneaux interactifs sont volontairement exclus. Leurs boutons et menus remplacent
    régulièrement l'embed sans renvoyer son fichier local ; Discord transforme alors
    l'ancienne miniature en grande pièce jointe au-dessus du panneau. Ils utilisent à la
    place l'avatar public du bot, qui reste petit et stable pendant toutes les éditions.
    """
    if kwargs.get("view") is not None:
        return kwargs
    if (
        not isinstance(embed, discord.Embed)
        or _has_thumbnail(embed)
        or _has_remote_identity(embed)
    ):
        return kwargs

    asset_name = _asset_name(category)
    asset_path = ASSET_DIR / asset_name
    if not asset_path.is_file():
        return kwargs

    attachment_name = f"sentrix-{asset_name}"
    existing_file = kwargs.get("file")
    existing_files = list(kwargs.get("files") or [])
    all_files = ([existing_file] if existing_file is not None else []) + existing_files

    if any(_file_name(item) == attachment_name for item in all_files):
        embed.set_thumbnail(url=f"attachment://{attachment_name}")
        return kwargs
    if len(all_files) >= 10:
        return kwargs

    brand_file = discord.File(
        asset_path,
        filename=attachment_name,
        description=f"Icône {str(category or 'SentriX').capitalize()}",
    )
    decorated = dict(kwargs)
    if existing_file is not None:
        decorated.pop("file", None)
        decorated["files"] = [existing_file, *existing_files, brand_file]
    elif "files" in decorated:
        decorated["files"] = [*existing_files, brand_file]
    else:
        decorated["file"] = brand_file

    embed.set_thumbnail(url=f"attachment://{attachment_name}")
    return decorated
