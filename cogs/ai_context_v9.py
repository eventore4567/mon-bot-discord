"""Production V9: contexte serveur minimal et sûr pour les réponses IA."""

import logging
import time

from discord.ext import commands

logger = logging.getLogger("bot.ai-context-v9")
_PATCHED = False

# Contexte serveur très court : réutilisé pendant quelques secondes afin qu'une même
# demande ne relise pas la base plusieurs fois (routeur + réponse finale + éventuel outil).
_CONTEXT_CACHE_TTL = 20.0
_CONTEXT_CACHE: dict[tuple[int, int | None], tuple[float, str]] = {}
_OPTIONAL_TABLE_CACHE: dict[str, tuple[float, bool]] = {}
_NO_CONTEXT_COMMANDS = frozenset({
    "sentrix-action-router",
    "sentrix-action-plan",
    "sentrix-command-router",
    "sentrix-command-classifier",
})


async def _optional_table_exists(bot: commands.Bot, table: str) -> bool:
    now = time.monotonic()
    cached = _OPTIONAL_TABLE_CACHE.get(table)
    if cached is not None and now < cached[0]:
        return cached[1]
    try:
        row = await bot.db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        )
        exists = row is not None
    except Exception:
        exists = False
    _OPTIONAL_TABLE_CACHE[table] = (now + 600.0, exists)
    return exists


async def build_server_context(bot: commands.Bot, guild_id: int | None, channel_id: int | None) -> str:
    """Construit un contexte utile, avec cache court et sans requêtes SQL inutiles."""
    if not guild_id:
        return ""

    gid = int(guild_id)
    cid = int(channel_id) if channel_id else None
    key = (gid, cid)
    now = time.monotonic()
    cached = _CONTEXT_CACHE.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]

    guild = bot.get_guild(gid)
    if guild is None:
        return ""

    lines = [f"Serveur: {guild.name}", f"Membres: {guild.member_count or 0}"]
    try:
        conf = await bot.db.get_guild_config(guild.id)
        if conf:
            lines.append(f"Préfixe: {conf['prefix'] or '+'}")
            lines.append(f"Niveau de sécurité: {conf['security_level'] or 'moyen'}")
            lines.append(f"Tickets configurés: {'oui' if conf['ticket_category'] or conf['ticket_log_channel'] else 'non'}")
    except Exception:
        logger.debug("Contexte config serveur indisponible.", exc_info=True)

    if channel_id:
        try:
            ticket = await bot.db.fetchone(
                "SELECT category,priority,claimed_by,status FROM tickets WHERE channel_id=? ORDER BY id DESC LIMIT 1",
                (int(channel_id),),
            )
            if ticket:
                lines.append(
                    "Contexte ticket: "
                    f"type={ticket['category'] or 'general'}, priorité={ticket['priority'] or 'normale'}, "
                    f"statut={ticket['status'] or 'inconnu'}, pris_en_charge={'oui' if ticket['claimed_by'] else 'non'}"
                )
        except Exception:
            logger.debug("Contexte ticket indisponible.", exc_info=True)

    # Table réellement optionnelle : vérifier son existence une fois toutes les 10 min.
    # Avant, une installation sans cette table produisait une exception SQL à CHAQUE appel IA.
    if await _optional_table_exists(bot, "production_issue_clusters"):
        try:
            rows = await bot.db.fetchall(
                "SELECT issue_label,occurrences FROM production_issue_clusters "
                "WHERE guild_id=? ORDER BY occurrences DESC,last_seen DESC LIMIT 3",
                (guild.id,),
            )
            if rows:
                lines.append(
                    "Problèmes support fréquents: "
                    + ", ".join(f"{row['issue_label']} ({row['occurrences']})" for row in rows)
                )
        except Exception:
            logger.debug("Contexte support optionnel indisponible.", exc_info=True)

    result = "\n".join(lines)[:1200]
    _CONTEXT_CACHE[key] = (now + _CONTEXT_CACHE_TTL, result)
    if len(_CONTEXT_CACHE) > 1000:
        cutoff = now
        for cache_key, (expires, _value) in list(_CONTEXT_CACHE.items()):
            if expires <= cutoff:
                _CONTEXT_CACHE.pop(cache_key, None)
    return result


def install(bot: commands.Bot) -> None:
    global _PATCHED
    if _PATCHED:
        return
    from utils import ai_service
    current = ai_service.generate
    if getattr(current, "_sentrix_ai_context_v9", False):
        _PATCHED = True
        return

    async def generate_with_context(*args, **kwargs):
        # Les routeurs internes ont besoin d'un JSON minuscule, pas du contexte serveur.
        # Cela supprime des requêtes DB et réduit leurs prompts.
        if kwargs.get("command") in _NO_CONTEXT_COMMANDS:
            return await current(*args, **kwargs)

        context = await build_server_context(bot, kwargs.get("guild_id"), kwargs.get("channel_id"))
        if context:
            instructions = kwargs.get("instructions", ai_service.SYSTEM_PROMPT)
            kwargs["instructions"] = (
                f"{instructions}\n\n"
                "[Contexte serveur fourni par SentriX. Utilise-le uniquement s'il aide à répondre. "
                "Il ne contient aucun secret et ne remplace jamais les faits donnés par l'utilisateur.]\n"
                f"{context}"
            )
        return await current(*args, **kwargs)

    generate_with_context._sentrix_ai_context_v9 = True
    ai_service.generate = generate_with_context
    _PATCHED = True
    logger.info("Production V9: contexte serveur sûr activé pour l'IA.")


async def _activate_isolated_observability(bot: commands.Bot) -> None:
    """Remplace le prototype V9 par le runtime qui utilise sa propre table SQL."""
    from . import command_observability_v9, production_observability_v9

    old = bot.get_cog("ProductionObservabilityV9")
    if old is not None:
        root = bot.get_command("security")
        if isinstance(root, commands.Group) and root.get_command("health") is not None:
            root.remove_command("health")
        await bot.remove_cog("ProductionObservabilityV9")

        async def disabled_legacy_write(*args, **kwargs):
            return None

        production_observability_v9._execute = disabled_legacy_write

    if bot.get_cog(command_observability_v9.COG_NAME) is None:
        await command_observability_v9.setup(bot)


async def setup(bot: commands.Bot) -> None:
    await _activate_isolated_observability(bot)
    install(bot)
