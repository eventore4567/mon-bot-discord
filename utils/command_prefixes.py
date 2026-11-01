"""Préfixes indépendants pour les commandes officielles et personnalisées.

guild_config.prefix = préfixe OFFICIEL (commandes du bot).
sentrix_custom_command_prefix = préfixe des commandes personnalisées seulement.
La première lecture copie l'ancien préfixe du serveur pour ne pas casser les
déclencheurs déjà créés. Après migration, les deux valeurs évoluent séparément.
"""
from __future__ import annotations

import re

TABLE = """
CREATE TABLE IF NOT EXISTS sentrix_custom_command_prefix (
    guild_id INTEGER PRIMARY KEY,
    prefix TEXT NOT NULL
)
"""

def validate_prefix(value: str) -> str:
    value = str(value or "").strip()
    if not 1 <= len(value) <= 5 or re.search(r"\s", value) or value.startswith("/") or value.startswith("<@"):
        raise ValueError("Préfixe invalide : 1 à 5 caractères, sans espace, / ni mention Discord.")
    return value

async def get_custom_prefix(bot, guild_id: int) -> str:
    await bot.db.execute(TABLE)
    row = await bot.db.fetchone(
        "SELECT prefix FROM sentrix_custom_command_prefix WHERE guild_id=?", (int(guild_id),)
    )
    if row:
        return str(row["prefix"])
    # Migration non destructive : l'ancien préfixe servait aux deux systèmes.
    conf = await bot.db.get_guild_config(int(guild_id))
    legacy = str(conf["prefix"] if conf and conf["prefix"] else "+")
    try:
        legacy = validate_prefix(legacy)
    except ValueError:
        legacy = "+"
    await bot.db.execute(
        "INSERT INTO sentrix_custom_command_prefix (guild_id, prefix) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO NOTHING",
        (int(guild_id), legacy),
    )
    row = await bot.db.fetchone(
        "SELECT prefix FROM sentrix_custom_command_prefix WHERE guild_id=?", (int(guild_id),)
    )
    return str(row["prefix"]) if row else legacy

async def set_custom_prefix(bot, guild_id: int, prefix: str) -> str:
    prefix = validate_prefix(prefix)
    await bot.db.execute(TABLE)
    await bot.db.execute(
        "INSERT INTO sentrix_custom_command_prefix (guild_id, prefix) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET prefix=excluded.prefix",
        (int(guild_id), prefix),
    )
    return prefix

async def set_official_prefix(bot, guild_id: int, prefix: str) -> str:
    prefix = validate_prefix(prefix)
    # Migrer AVANT d'écrire l'officiel pour ne jamais modifier le personnalisé.
    await get_custom_prefix(bot, guild_id)
    await bot.db.set_guild_config(int(guild_id), "prefix", prefix)
    if hasattr(bot, "prefix_cache"):
        bot.prefix_cache[int(guild_id)] = prefix
    return prefix
