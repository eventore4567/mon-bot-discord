"""Correctif de production final pour les embeds de commandes et les logs SentriX.

Objectifs :
- toutes les commandes + et / restent en embed, y compris ``sentrix`` ;
- les réponses préfixées gardent la référence Discord sans reping automatique de l'auteur ;
- le vrai ``SentriXContext.send`` est protégé directement, sans dépendre uniquement d'un
  monkey-patch de ``commands.Context.send`` ;
- le Cog officiel ``Logs`` est garanti au runtime ;
- une ancienne migration où TOUS les logs configurés sont restés ``enabled=0`` est réparée
  une seule fois par serveur, puis les choix administrateur suivants sont respectés.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord
from discord.ext import commands

from . import command_embed_invariant as invariant
from . import final_interaction_policy as policy
from . import runtime_fix_v1
from utils import log_service

logger = logging.getLogger("bot.production-embed-log-repair")

_MIGRATION_KEY = "production_embed_log_repair_v2"
_PREFIX_MARKER = "_sentrix_direct_embed_transport_v2"
_POLICY_MARKER = "_sentrix_all_commands_embed_v2"
_EMITTING_LOG_TYPES = tuple(
    key for key, meta in log_service.LOG_TYPES.items() if bool(meta.get("emits"))
)


def _state(bot: commands.Bot) -> dict[str, Any]:
    current = getattr(bot, "sentrix_embed_log_repair_state", None)
    if not isinstance(current, dict):
        current = {
            "installed": False,
            "prefix_transport": False,
            "all_command_roots_embed": False,
            "logs_cog_loaded": False,
            "log_listener_count": 0,
            "guilds_checked": 0,
            "guilds_mass_recovered": 0,
            "configured_log_routes": 0,
            "enabled_log_routes": 0,
            "last_repair_at": None,
            "last_error": None,
        }
        bot.sentrix_embed_log_repair_state = current
    return current


def _force_all_command_embeds() -> None:
    """Supprime la dernière exception historique : ``sentrix`` reste une commande.

    Les messages ordinaires du bot ne sont pas concernés : sans racine de commande, les
    transports globaux ne convertissent rien. Seules les sorties exécutées dans le contexte
    d'une commande sont donc forcées en embed.
    """
    current = policy._plain_root
    if getattr(current, _POLICY_MARKER, False):
        return

    def no_plain_command_root(_root: str) -> bool:
        return False

    setattr(no_plain_command_root, _POLICY_MARKER, True)
    no_plain_command_root._sentrix_original = current
    policy._plain_root = no_plain_command_root


def _install_direct_prefix_transport(bot: commands.Bot) -> None:
    """Protège directement ``SentriXContext.send``.

    Les anciennes couches ne peuvent plus contourner le renderer en remplaçant seulement
    ``commands.Context.send``. La référence au message utilisateur est conservée, mais
    ``mention_author=False`` évite la notification automatique qui était revenue.
    """
    import main as bot_main

    context_cls = bot_main.SentriXContext
    current = context_cls.send
    if getattr(current, _PREFIX_MARKER, False):
        state = _state(bot)
        state["prefix_transport"] = True
        return

    async def send_with_embed(self, *args, **kwargs):
        root = policy._root_name(getattr(self, "command", None)) or policy._COMMAND_ROOT.get()

        if self.interaction is None and self.message is not None:
            if "reference" not in kwargs:
                kwargs["reference"] = discord.MessageReference(
                    message_id=self.message.id,
                    channel_id=self.channel.id,
                    guild_id=self.guild.id if self.guild else None,
                    fail_if_not_exists=False,
                )
            # Réponse visuellement liée au message, mais aucune notification automatique.
            kwargs["mention_author"] = False

        args, kwargs = invariant._normalize_command_payload(
            args,
            kwargs,
            root=root or "commande",
            bot=getattr(self, "bot", None),
        )
        return await current(self, *args, **kwargs)

    setattr(send_with_embed, _PREFIX_MARKER, True)
    send_with_embed._sentrix_original = current
    context_cls.send = send_with_embed
    _state(bot)["prefix_transport"] = True


def _should_mass_recover(
    configured_count: int,
    enabled_count: int,
    migration_applied: bool,
) -> bool:
    """Répare uniquement le cas historique « tout configuré mais tout désactivé »."""
    return bool(configured_count > 0 and enabled_count == 0 and not migration_applied)


async def _ensure_migration_table(bot: commands.Bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS sentrix_runtime_migrations (
            guild_id INTEGER NOT NULL,
            migration_key TEXT NOT NULL,
            applied_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, migration_key)
        )
        """
    )


async def _migration_applied(bot: commands.Bot, guild_id: int) -> bool:
    row = await bot.db.fetchone(
        "SELECT 1 AS ok FROM sentrix_runtime_migrations WHERE guild_id = ? AND migration_key = ?",
        (int(guild_id), _MIGRATION_KEY),
    )
    return bool(row)


async def _mark_migration(bot: commands.Bot, guild_id: int) -> None:
    await bot.db.execute(
        "INSERT INTO sentrix_runtime_migrations (guild_id, migration_key, applied_at) "
        "VALUES (?, ?, ?) ON CONFLICT(guild_id, migration_key) DO NOTHING",
        (int(guild_id), _MIGRATION_KEY, int(time.time())),
    )


async def _ensure_logs_cog(bot: commands.Bot) -> tuple[bool, int]:
    """Garantit que le seul propriétaire officiel des listeners est réellement chargé."""
    cog = bot.get_cog("Logs")
    if cog is None:
        try:
            if "cogs.logs" in bot.extensions:
                await bot.reload_extension("cogs.logs")
            else:
                await bot.load_extension("cogs.logs")
        except Exception:
            logger.exception("Impossible de restaurer le Cog officiel Logs.")
        cog = bot.get_cog("Logs")

    listeners = 0
    if cog is not None:
        try:
            listeners = len(cog.get_listeners())
        except Exception:
            listeners = 0
    return cog is not None, listeners


async def _valid_routes(bot: commands.Bot, guild: discord.Guild) -> list[tuple[str, dict]]:
    routes: list[tuple[str, dict]] = []
    for log_type in _EMITTING_LOG_TYPES:
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
        except Exception:
            logger.exception("Lecture du log %s impossible sur guild=%s.", log_type, guild.id)
            continue
        channel_id = setting.get("channel_id")
        if not channel_id:
            continue
        ok, _reason = log_service.validate_channel(guild, int(channel_id))
        if ok:
            routes.append((log_type, setting))
    return routes


async def repair_guild_runtime(bot: commands.Bot, guild: discord.Guild) -> dict[str, int | bool]:
    """Répare routage/permissions puis récupère une migration entièrement désactivée."""
    await _ensure_migration_table(bot)

    # D'abord, restaurer les routes legacy cassées sans modifier les désactivations valides.
    try:
        await runtime_fix_v1.repair_guild_logs(bot, guild, force_enable=False)
    except Exception:
        logger.exception("Réparation de base des logs impossible sur guild=%s.", guild.id)

    routes = await _valid_routes(bot, guild)
    configured_count = len(routes)
    enabled_count = sum(1 for _kind, setting in routes if bool(setting.get("enabled")))
    applied = await _migration_applied(bot, guild.id)
    recovered = False

    if _should_mass_recover(configured_count, enabled_count, applied):
        # Cas observé en production : create-logs avait bien créé/routé les salons mais
        # toutes les lignes log_settings étaient restées à enabled=0. On les remet actives
        # UNE seule fois. Une désactivation faite ensuite par l'admin restera respectée.
        for log_type, setting in routes:
            channel_id = setting.get("channel_id")
            if not channel_id:
                continue
            try:
                await log_service.set_log_enabled(bot, guild.id, log_type, True)
                enabled_count += 1
            except Exception:
                logger.exception(
                    "Activation de récupération impossible pour %s sur guild=%s.",
                    log_type,
                    guild.id,
                )
        recovered = enabled_count > 0
        logger.warning(
            "Migration logs récupérée guild=%s : %s route(s) configurée(s), %s activée(s).",
            guild.id,
            configured_count,
            enabled_count,
        )

    # Marquer la migration après le diagnostic, même si aucune route n'existe : on évite
    # qu'un futur choix explicite « tout désactivé » soit réinterprété à chaque redémarrage.
    if not applied:
        await _mark_migration(bot, guild.id)

    return {
        "configured": configured_count,
        "enabled": enabled_count,
        "recovered": recovered,
    }


class ProductionEmbedLogRepair(commands.Cog, name="ProductionEmbedLogRepair"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ready_task: asyncio.Task | None = None

    async def _repair_all(self) -> None:
        state = _state(self.bot)
        state["last_error"] = None
        try:
            loaded, listener_count = await _ensure_logs_cog(self.bot)
            state["logs_cog_loaded"] = loaded
            state["log_listener_count"] = listener_count

            checked = recovered = configured = enabled = 0
            for guild in list(self.bot.guilds):
                try:
                    result = await repair_guild_runtime(self.bot, guild)
                    checked += 1
                    recovered += int(bool(result["recovered"]))
                    configured += int(result["configured"])
                    enabled += int(result["enabled"])
                except Exception as exc:
                    state["last_error"] = type(exc).__name__
                    logger.exception("Réparation finale logs impossible sur guild=%s.", guild.id)

            state.update({
                "guilds_checked": checked,
                "guilds_mass_recovered": recovered,
                "configured_log_routes": configured,
                "enabled_log_routes": enabled,
                "last_repair_at": int(time.time()),
            })
            logger.info(
                "Runtime embed/log validé : Logs=%s listeners=%s guilds=%s routes=%s actives=%s récupérées=%s.",
                loaded,
                listener_count,
                checked,
                configured,
                enabled,
                recovered,
            )
        except Exception as exc:
            state["last_error"] = type(exc).__name__
            logger.exception("Diagnostic final embed/log impossible.")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._ready_task is not None and not self._ready_task.done():
            return
        self._ready_task = asyncio.create_task(self._repair_all())

    @commands.Cog.listener()
    async def on_guild_available(self, guild: discord.Guild) -> None:
        try:
            await repair_guild_runtime(self.bot, guild)
        except Exception:
            logger.exception("Réparation logs on_guild_available impossible sur guild=%s.", guild.id)


def _install_health_patch(bot: commands.Bot) -> None:
    try:
        from web import production_health
    except Exception:
        return

    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_embed_log_repair_v2", False):
        return

    def safe_health_with_embed_logs(runtime_bot: commands.Bot):
        payload = current(runtime_bot)
        if not isinstance(payload, dict):
            payload = {}
        state = dict(_state(runtime_bot))
        payload["embed_log_runtime"] = state
        return payload

    safe_health_with_embed_logs._sentrix_embed_log_repair_v2 = True
    safe_health_with_embed_logs._sentrix_original = current
    production_health._safe_slash_health = safe_health_with_embed_logs


async def setup(bot: commands.Bot) -> None:
    # Réinstaller d'abord l'invariant global, puis protéger directement le Context réel.
    invariant.install(bot)
    _force_all_command_embeds()
    _install_direct_prefix_transport(bot)

    # Le runtime précédent coupe déjà le kill-switch SENTRIX_LOG_PRODUCER ; on le garde
    # explicitement actif ici au cas où l'ordre de chargement change à nouveau.
    runtime_fix_v1._install_log_producer_fix()

    loaded, listeners = await _ensure_logs_cog(bot)
    state = _state(bot)
    state.update({
        "installed": True,
        "prefix_transport": True,
        "all_command_roots_embed": True,
        "logs_cog_loaded": loaded,
        "log_listener_count": listeners,
    })

    existing = bot.get_cog("ProductionEmbedLogRepair")
    if existing is not None:
        await bot.remove_cog("ProductionEmbedLogRepair")
    await bot.add_cog(ProductionEmbedLogRepair(bot))
    _install_health_patch(bot)

    logger.info(
        "Correctif production V2 actif : toutes commandes en embed, aucun auto-ping auteur, logs officiels garantis."
    )


__all__ = [
    "setup",
    "repair_guild_runtime",
    "_should_mass_recover",
    "_install_direct_prefix_transport",
    "_force_all_command_embeds",
]
