"""Identité stable d'une instance SentriX/Bot'Odboug.

Les deux services Railway partagent volontairement le même code. Ce module centralise les
valeurs qui doivent au contraire rester propres à chaque instance : marque affichée, nom,
mot de réveil et namespace de stockage. Les valeurs explicites restent toujours
prioritaires afin qu'un renommage Railway n'altère jamais les données persistantes.
"""
from __future__ import annotations

import os
import re


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def railway_service_name() -> str:
    return _clean(os.getenv("RAILWAY_SERVICE_NAME"))


def is_odboug_instance() -> bool:
    explicit = _clean(os.getenv("BOT_BRAND_LABEL"))
    if explicit:
        return explicit.casefold() == "odboug"
    return "odboug" in railway_service_name().casefold()


def brand_label() -> str:
    explicit = _clean(os.getenv("BOT_BRAND_LABEL"))
    if explicit:
        return explicit[:48]
    if is_odboug_instance():
        return "Odboug"
    return "SentriX"


def display_name() -> str:
    explicit = _clean(os.getenv("BOT_DISPLAY_NAME"))
    if explicit:
        return explicit[:32]
    if is_odboug_instance():
        return "[+] Bot'Odboug |"
    return ""


def _slug(value: str) -> str:
    value = value.casefold().replace("'", "-").replace("’", "-")
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-_")
    return value[:48]


def instance_key() -> str:
    """Clé persistante utilisée pour isoler PostgreSQL/Redis entre plusieurs bots.

    BOT_INSTANCE_KEY est recommandé si l'instance doit survivre à un renommage. Sans
    configuration, on conserve volontairement ``sentrix`` pour la production historique et
    ``odboug`` pour le second service afin que les anciens snapshots SentriX restent lisibles.
    """
    explicit = _slug(_clean(os.getenv("BOT_INSTANCE_KEY")))
    if explicit:
        return explicit
    brand = brand_label()
    if brand.casefold() == "sentrix":
        return "sentrix"
    if brand.casefold() == "odboug":
        return "odboug"
    return _slug(brand) or "sentrix"


def wake_words() -> tuple[str, ...]:
    configured = tuple(
        item.strip()
        for item in _clean(os.getenv("BOT_WAKE_WORDS")).split(",")
        if item.strip()
    )
    if configured:
        return configured
    brand = brand_label()
    words = [brand]
    if brand.casefold() == "odboug":
        words.extend(("Odboug", "Bot Odboug", "Bot'Odboug", "Bot’Odboug"))
    unique: list[str] = []
    seen: set[str] = set()
    for word in words:
        key = word.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(word)
    return tuple(unique)


def storage_key(key: str) -> str:
    """Namespace Redis borné et stable pour l'instance courante."""
    return f"sentrix:{instance_key()}:{str(key).lstrip(':')}"[:240]


def brand_text(text: str | None) -> str:
    """Remplace uniquement la marque SentriX dans un texte généré par le bot."""
    value = str(text or "")
    brand = brand_label()
    if brand.casefold() == "sentrix":
        return value
    return re.sub(r"\bSentriX\b", brand, value, flags=re.IGNORECASE)
