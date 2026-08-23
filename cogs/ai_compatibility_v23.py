"""SentriX V23 — compatibilité IA pour anciennes bases et registre préfixe.

Deux régressions de production sont couvertes ici :
1. d'anciennes tables ``ai_settings`` peuvent ne pas encore contenir toutes les colonnes
   ajoutées ensuite (ex. ``max_question_length``). L'ancien get_settings lisait ces clés
   directement et levait KeyError avant même l'appel OpenAI ;
2. certaines commandes du Cog Ai peuvent rester présentes dans ``Ai.get_commands()`` mais
   disparaître de ``bot.all_commands`` après les nettoyages/runtime historiques.

Cette couche ne change ni les prompts ni le moteur OpenAI. Elle rend seulement les réglages
rétrocompatibles et restaure les commandes préfixées IA réellement déclarées par le Cog.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.ai-compatibility-v23")


_LIST_FIELDS = {"allowed_channel_ids", "allowed_role_ids"}
_BOOL_FIELDS = {"enabled", "memory_enabled", "logs_enabled"}


def _row_to_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    try:
        return dict(row)
    except Exception:
        pass
    keys = getattr(row, "keys", None)
    if callable(keys):
        result = {}
        for key in keys():
            try:
                result[str(key)] = row[key]
            except Exception:
                continue
        return result
    return {}


def _normalise_settings(ai_service, raw: dict[str, Any]) -> dict[str, Any]:
    settings = dict(ai_service.DEFAULT_AI_SETTINGS)
    for key in list(settings):
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key in _LIST_FIELDS:
            try:
                if isinstance(value, str):
                    value = json.loads(value or "[]")
                value = list(value or [])
            except Exception:
                value = list(settings[key])
        elif key in _BOOL_FIELDS:
            value = bool(value)
        settings[key] = value

    # Bornes défensives : une ancienne valeur invalide ne doit jamais casser une commande.
    try:
        settings["max_question_length"] = max(100, int(settings.get("max_question_length", 1500) or 1500))
    except (TypeError, ValueError):
        settings["max_question_length"] = 1500
    try:
        settings["cooldown_seconds"] = max(0, int(settings.get("cooldown_seconds", 8) or 0))
    except (TypeError, ValueError):
        settings["cooldown_seconds"] = 8
    try:
        settings["per_minute_limit"] = max(1, int(settings.get("per_minute_limit", 6) or 6))
    except (TypeError, ValueError):
        settings["per_minute_limit"] = 6
    try:
        settings["daily_limit"] = max(1, int(settings.get("daily_limit", 50) or 50))
    except (TypeError, ValueError):
        settings["daily_limit"] = 50
    try:
        settings["memory_minutes"] = max(1, int(settings.get("memory_minutes", 30) or 30))
    except (TypeError, ValueError):
        settings["memory_minutes"] = 30
    return settings


def _install_settings_compat(bot: commands.Bot) -> None:
    from utils import ai_service

    current = ai_service.get_settings
    if getattr(current, "_sentrix_legacy_settings_safe_v23", False):
        return

    async def get_settings_safe(_bot, guild_id: int) -> dict:
        try:
            result = await current(_bot, guild_id)
        except (KeyError, IndexError):
            # Ancien schéma : relire la ligne sans supposer qu'une colonne précise existe.
            try:
                row = await _bot.db.fetchone(
                    "SELECT * FROM ai_settings WHERE guild_id = ?",
                    (guild_id,),
                )
                return _normalise_settings(ai_service, _row_to_mapping(row))
            except Exception:
                logger.exception("V23 : lecture compatible ai_settings impossible guild=%s", guild_id)
                return dict(ai_service.DEFAULT_AI_SETTINGS)
        except Exception:
            logger.exception("V23 : get_settings historique a échoué guild=%s", guild_id)
            return dict(ai_service.DEFAULT_AI_SETTINGS)

        # Même avec un schéma récent, toujours fusionner avec DEFAULT_AI_SETTINGS afin
        # qu'une future nouvelle option ne puisse plus produire de KeyError.
        if isinstance(result, dict):
            merged = dict(ai_service.DEFAULT_AI_SETTINGS)
            merged.update(result)
            return _normalise_settings(ai_service, merged)
        return dict(ai_service.DEFAULT_AI_SETTINGS)

    get_settings_safe._sentrix_legacy_settings_safe_v23 = True
    get_settings_safe._sentrix_original = current
    ai_service.get_settings = get_settings_safe


def _restore_ai_prefix_commands(bot: commands.Bot) -> list[str]:
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None:
        return []

    restored: list[str] = []
    # On ne fabrique aucune commande : on restaure uniquement les objets Command réellement
    # déclarés dans le Cog Ai et qui ont disparu du registre racine.
    for command in list(ai_cog.get_commands()):
        if getattr(command, "parent", None) is not None:
            continue
        name = str(getattr(command, "name", "") or "").casefold()
        if not name or bot.get_command(name) is not None:
            continue
        try:
            bot.add_command(command)
            restored.append(name)
        except commands.CommandRegistrationError:
            logger.warning("V23 : collision en restaurant +%s ; commande laissée intacte.", name)
        except Exception:
            logger.exception("V23 : restauration de +%s impossible.", name)

    return restored


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    _install_settings_compat(bot)
    restored = _restore_ai_prefix_commands(bot)
    if restored:
        logger.info("V23 : commandes IA préfixées restaurées : %s", ", ".join(restored))
    bot._sentrix_ai_compatibility_v23 = True


__all__ = ["install"]
