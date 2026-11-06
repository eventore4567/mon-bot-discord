"""Réglages d'économie persistants, partagés par commandes, jeux et setup."""

from __future__ import annotations

import sqlite3
import time

from utils import config_journal

DEFAULTS = {
    "enabled": 1,
    "currency_name": "pièces",
    "daily_amount": 200,
    "weekly_amount": 1000,
    "work_min": 50,
    "work_max": 250,
    "work_cooldown": 3600,
    "salary_multiplier": 1.0,
    "interest_rate": 0.01,
    "interest_cap": 1000,
    "rob_enabled": 1,
    "rob_success": 40,
    "rob_fine": -1,
    "games_pay": 1,
    "games_multiplier": 1.0,
    "panel_channel_id": 0,
    "panel_message_id": 0,
    "updated_by": 0,
    "updated_at": 0,
}
# -1 conserve l'amende historique aléatoire ; toute valeur configurée est >= 0.
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sentrix_economy_settings (guild_id BIGINT PRIMARY KEY, "
    + ", ".join(
        f"{key} {'TEXT' if isinstance(value, str) else 'REAL' if isinstance(value, float) else 'BIGINT'}"
        for key, value in DEFAULTS.items()
    )
    + ")"
)
BOUNDS = {
    "daily_amount": (50, 100000),
    "weekly_amount": (100, 1000000),
    "work_min": (1, 100000),
    "work_max": (1, 100000),
    "work_cooldown": (300, 86400),
    "salary_multiplier": (0.5, 5),
    "interest_rate": (0, 0.05),
    "interest_cap": (0, 100000),
    "rob_success": (5, 90),
    "rob_fine": (0, 1000000),
    "games_multiplier": (0, 5),
}
_CACHE = {}


def invalidate(bot, guild_id):
    _CACHE.pop((id(bot.db), int(guild_id)), None)


async def get_economy_settings(bot, guild_id: int) -> dict:
    key = (id(bot.db), int(guild_id))
    cached = _CACHE.get(key)
    if cached and cached[0] > time.monotonic():
        return dict(cached[1])
    # Adaptateurs de lecture seuls : les valeurs historiques restent disponibles.
    if not hasattr(bot.db, "execute") or not hasattr(bot.db, "fetchone"):
        return dict(DEFAULTS)
    await bot.db.execute(SCHEMA)
    row = await bot.db.fetchone(
        "SELECT * FROM sentrix_economy_settings WHERE guild_id=?", (guild_id,)
    )
    values = dict(DEFAULTS)
    if row:
        for name in DEFAULTS:
            try:
                if row[name] is not None:
                    values[name] = row[name]
            except (KeyError, IndexError, TypeError):
                pass
    # L'interrupteur historique reste l'autorité commune des commandes et jeux.
    try:
        switch = await bot.db.fetchone(
            "SELECT enabled FROM module_settings WHERE guild_id=? AND module='economy'",
            (guild_id,),
        )
        if switch is not None:
            values["enabled"] = int(bool(switch["enabled"]))
    except (sqlite3.OperationalError, KeyError, IndexError, TypeError):
        pass
    # Le nom historique reste synchronisé avec les profils et le dashboard.
    try:
        currency = await bot.db.fetchone(
            "SELECT currency_plural FROM economy_settings_v2 WHERE guild_id=?",
            (guild_id,),
        )
        if currency and currency["currency_plural"]:
            values["currency_name"] = currency["currency_plural"]
    except (sqlite3.OperationalError, KeyError, IndexError, TypeError):
        pass
    _CACHE[key] = (time.monotonic() + 30, values, bot.db)
    return dict(values)


def validate(updates: dict, current: dict) -> dict:
    result = dict(updates)
    for name, value in result.items():
        if name not in DEFAULTS:
            raise ValueError("Réglage inconnu.")
        if name in BOUNDS:
            lo, hi = BOUNDS[name]
            if not lo <= float(value) <= hi:
                raise ValueError(f"{name} doit être compris entre {lo:g} et {hi:g}.")
        if name in {"enabled", "rob_enabled", "games_pay"} and value not in (
            0,
            1,
            False,
            True,
        ):
            raise ValueError("Choisissez oui ou non.")
        if name == "currency_name" and not 1 <= len(str(value).strip()) <= 32:
            raise ValueError("Le nom de monnaie doit contenir 1 à 32 caractères.")
    combined = {**current, **result}
    if combined["work_min"] > combined["work_max"]:
        raise ValueError("Le salaire minimum doit être inférieur ou égal au maximum.")
    return result


async def save_economy_settings(bot, guild_id, updates, actor_id):
    current = await get_economy_settings(bot, guild_id)
    updates = validate(updates, current)
    values = {
        **current,
        **updates,
        "updated_by": int(actor_id),
        "updated_at": int(time.time()),
    }
    names = tuple(DEFAULTS)
    await bot.db.execute(
        "INSERT INTO sentrix_economy_settings (guild_id,"
        + ",".join(names)
        + ") VALUES (?"
        + ",?" * len(names)
        + ") ON CONFLICT(guild_id) DO UPDATE SET "
        + ",".join(f"{n}=excluded.{n}" for n in (*updates, "updated_by", "updated_at")),
        (guild_id, *(values[n] for n in names)),
    )
    invalidate(bot, guild_id)
    from utils import sentrix_trace

    token = sentrix_trace.ACTOR.set((int(actor_id), "formulaire"))
    try:
        for name, value in updates.items():
            await config_journal.record(
                bot.db, guild_id, "economy." + name, current[name], value
            )
        if "enabled" in updates:
            from utils.system_features import set_system_feature

            await set_system_feature(
                bot.db, guild_id, "economy", bool(updates["enabled"])
            )
    finally:
        sentrix_trace.ACTOR.reset(token)
    return values


async def enabled_or_reply(bot, ctx):
    if ctx.guild is None:
        return False
    if (await get_economy_settings(bot, ctx.guild.id))["enabled"]:
        return True
    await ctx.send("L'économie est désactivée sur ce serveur", ephemeral=True)
    return False


async def sync_economy_switch(bot, guild_id, enabled, actor_id=None):
    """Synchronise les anciens boutons/dashboard, sans créer de réglages implicites."""
    await bot.db.execute(SCHEMA)
    await bot.db.execute(
        "UPDATE sentrix_economy_settings SET enabled=?,updated_by=COALESCE(?,updated_by),updated_at=? WHERE guild_id=?",
        (int(bool(enabled)), actor_id, int(time.time()), guild_id),
    )
    invalidate(bot, guild_id)
