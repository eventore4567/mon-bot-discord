"""Démarrage Railway résilient, durable et shardé pour SentriX.

Le serveur HTTP est ouvert avant le chargement complet des cogs Discord. Quand PostgreSQL
est configuré, le bootstrap tente aussi de restaurer la base SQLite principale depuis son
dernier snapshot durable si le fichier local a disparu ou est invalide.

Le healthcheck Railway ne passe désormais à HTTP 200 qu'une fois la session Discord
réellement prête. Avec /health configuré côté Railway, l'ancien déploiement peut donc
continuer à servir pendant que le nouveau finit son démarrage au lieu de couper SentriX
trop tôt.
"""

import asyncio
import logging
import os
import traceback

from aiohttp import web as aiohttp_web
from discord.ext import commands

import config
from utils.durable_database import DurableDatabaseReplica
from utils.failover import FailoverSettings, RedisFailoverLease


class SentriXAutoShardedBot(commands.AutoShardedBot):
    """AutoShardedBot qui respecte SHARD_COUNT quand l'opérateur veut le figer."""

    def __init__(self, *args, **kwargs):
        if config.SHARD_COUNT > 0:
            kwargs.setdefault("shard_count", config.SHARD_COUNT)
        super().__init__(*args, **kwargs)


if not getattr(commands, "_sentrix_auto_sharded_bootstrap", False):
    commands.Bot = SentriXAutoShardedBot
    commands._sentrix_auto_sharded_bootstrap = True

import main as bot_main
from web import dashboard as dashboard_web

if "cogs.drop" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.drop")
if "cogs.interaction_transport_guard" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.interaction_transport_guard")
# Les deux anciens diagnostics ci-dessous ne sont plus chargés en permanence :
# - stale_discord_app_detector pouvait scanner jusqu'à 250 intégrations au démarrage ;
# - command_error_probe relisait la base toutes les 5 secondes uniquement pour /health.
# Les modules restent dans le dépôt pour un diagnostic manuel si le problème revient.
if "cogs.legacy_observability_conflict_guard" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.legacy_observability_conflict_guard")
if "cogs.slash_reliability_v7" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.slash_reliability_v7")
if "cogs.automod_enable_all" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.automod_enable_all")
if "cogs.setup_auto_fix" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.setup_auto_fix")
if "cogs.setup_experience_v2" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.setup_experience_v2")
if "cogs.emoji_name_lookup" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.emoji_name_lookup")
if "cogs.emoji_unicode_asset_fix" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.emoji_unicode_asset_fix")
# Ancienne V2 chargée d'abord pour la compatibilité avec les données déjà présentes.
if "cogs.create_sentrix" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.create_sentrix")
# V3 retire proprement le Cog V2 puis réenregistre +create sentrix avec la structure
# professionnelle, les salons emoji et les logs automatiques séparés.
if "cogs.create_sentrix_v3" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.create_sentrix_v3")
if "cogs.canonical_interactions" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.canonical_interactions")
# Nouvelles fonctions isolées : starboard, vocaux temporaires, sticky, annonces planifiées
# et diagnostic serveur.
if "cogs.sentrix_plus" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.sentrix_plus")
# Suite professionnelle : 20 systèmes regroupés derrière +sentrixpro.
if "cogs.sentrix_ultimate" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.sentrix_ultimate")
# Une seule politique visuelle finale.
if "cogs.plain_text_all_extension" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.plain_text_all_extension")
# Profil final : +profil/+profile = carte communautaire aérée ; +me = statistiques perso.
if "cogs.profile_oxyde_runtime" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.profile_oxyde_runtime")
if "cogs.deferred_context_response_guard" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.deferred_context_response_guard")
if "cogs.slash_error_completion_guard" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.slash_error_completion_guard")
# Toute dernière garde non destructive : réaffirme zéro cooldown, neutralise le throttle
# local IA restant et sécurise l'archivage partiel des pièces jointes.
if "cogs.final_stability_guard" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.final_stability_guard")
# Dernier verrou runtime : un départ/kick/ban ne doit jamais devenir une suppression de
# progression. Chargé après les autres cogs pour entourer les commandes de reset finales.
if "cogs.member_data_retention_v17" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.member_data_retention_v17")

bot_main.CATEGORY_COMMANDS["economie"] = (
    bot_main.CATEGORY_COMMANDS.get("economie", frozenset()) | frozenset({"drop"})
)

_SENTRIX_PLUS_CONFIG_COMMANDS = frozenset({
    "starboard-setup", "starboard-off", "voicehub-setup", "voicehub-off",
    "sticky-set", "sticky-every", "sticky-off", "schedule-send", "schedule-list",
    "schedule-cancel", "server-health",
})
_SENTRIX_PLUS_MEMBER_COMMANDS = frozenset({
    "sentrix-plus", "voice-name", "voice-limit", "voice-lock", "voice-unlock", "voice-transfer",
})

_SENTRIX_PRO_PUBLIC_COMMANDS = frozenset({
    "sentrixpro", "sentrixpro help", "sentrixpro trust", "sentrixpro profile",
    "sentrixpro badges", "sentrixpro season", "sentrixpro status",
})
_SENTRIX_PRO_ADMIN_COMMANDS = frozenset({
    "sentrixpro security", "sentrixpro lockdown", "sentrixpro quarantine-setup",
    "sentrixpro history", "sentrixpro live", "sentrixpro notifications",
    "sentrixpro welcome", "sentrixpro autorole", "sentrixpro goal",
    "sentrixpro aimod", "sentrixpro ticket-summary", "sentrixpro digest",
    "sentrixpro modules", "sentrixpro module",
})

bot_main.CATEGORY_COMMANDS["configuration"] = (
    bot_main.CATEGORY_COMMANDS.get("configuration", frozenset())
    | frozenset({"create", "create sentrix"})
    | _SENTRIX_PLUS_CONFIG_COMMANDS
    | _SENTRIX_PRO_ADMIN_COMMANDS
)
bot_main.PUBLIC_COMMANDS = (
    getattr(bot_main, "PUBLIC_COMMANDS", frozenset())
    | _SENTRIX_PLUS_MEMBER_COMMANDS
    | _SENTRIX_PRO_PUBLIC_COMMANDS
)
bot_main.KNOWN_PERMISSION_COMMANDS = (
    bot_main.KNOWN_PERMISSION_COMMANDS
    | frozenset({"drop", "create", "create sentrix"})
    | _SENTRIX_PLUS_CONFIG_COMMANDS
    | _SENTRIX_PLUS_MEMBER_COMMANDS
    | _SENTRIX_PRO_PUBLIC_COMMANDS
    | _SENTRIX_PRO_ADMIN_COMMANDS
)


logger = logging.getLogger("bot.railway")


async def _dashboard_already_started(_bot):
    return None


def _install_discord_readiness_healthcheck() -> None:
    """Ne déclare le nouveau déploiement prêt qu'après on_ready Discord.

    Le dashboard HTTP démarre volontairement avant Discord. Avant ce correctif, /health
    répondait donc 200 immédiatement : Railway pouvait arrêter l'ancien conteneur alors
    que le nouveau bot était encore en train de charger ses cogs / ouvrir le Gateway.
    """
    current = dashboard_web.handle_health
    if getattr(current, "_sentrix_discord_readiness", False):
        return

    async def ready_health(request):
        bot = request.app["bot"]
        failover = getattr(bot, "sentrix_failover", None)
        lease_ok = bool(failover is None or failover.owns_lease)
        ready = bool(bot.is_ready() and not bot.is_closed() and lease_ok)
        failover_state = failover.public_state() if failover is not None else {"enabled": False}
        return aiohttp_web.json_response(
            {
                "ok": ready,
                "discord_ready": ready,
                "latency_ms": round(bot.latency * 1000) if ready else None,
                "failover": failover_state,
            },
            status=200 if ready else 503,
        )

    ready_health._sentrix_discord_readiness = True
    ready_health._sentrix_original = current
    dashboard_web.handle_health = ready_health
    logger.info("Healthcheck Railway lié à l'état réel de la connexion Discord.")


def _install_sentrix_asset_route() -> None:
    """Expose la bannière Ping sur le domaine Railway de SentriX.

    Discord charge plus fiablement une image servie directement par l'application que
    les URLs GitHub raw/attachment utilisées auparavant dans MediaGallery.
    """
    current = dashboard_web.build_app
    if getattr(current, "_sentrix_asset_route", False):
        return

    def build_app_with_assets(bot):
        app = current(bot)

        async def ping_banner(_request):
            response = aiohttp_web.FileResponse("assets/sentrix-log-header.png")
            response.headers["Cache-Control"] = "public, max-age=86400"
            return response

        app.router.add_get("/assets/sentrix-ping-banner.png", ping_banner)
        return app

    build_app_with_assets._sentrix_asset_route = True
    build_app_with_assets._sentrix_original = current
    dashboard_web.build_app = build_app_with_assets
    logger.info("Bannière Ping SentriX exposée via Railway.")


async def _prepare_durable_store(
    bot,
    *,
    force_failover_restore: bool = False,
) -> DurableDatabaseReplica:
    durable = DurableDatabaseReplica(config.DATABASE_PATH)
    bot.sentrix_durable_store = durable
    if not durable.configured:
        if config.FAILOVER_ENABLED:
            raise RuntimeError("Le failover SentriX exige POSTGRES_URL/DATABASE_URL.")
        logger.info("PostgreSQL durable non configuré ; démarrage SQLite normal.")
        return durable
    try:
        connected = await asyncio.wait_for(durable.connect(), timeout=8)
        if connected:
            result = await asyncio.wait_for(
                durable.restore_latest_if_needed(force=force_failover_restore),
                timeout=30,
            )
            if result.get("restored"):
                logger.warning("Base restaurée depuis PostgreSQL avant connexion SQLite : %s", result)
            elif force_failover_restore:
                raise RuntimeError(
                    "Promotion failover refusée : aucun snapshot PostgreSQL restaurable "
                    f"({result.get('reason') or 'raison inconnue'})."
                )
            else:
                logger.info("Restauration PostgreSQL non nécessaire : %s", result.get("reason"))
        elif config.FAILOVER_ENABLED:
            raise RuntimeError("PostgreSQL durable indisponible pour le failover.")
    except Exception:
        if config.FAILOVER_ENABLED:
            raise
        logger.warning(
            "Préparation PostgreSQL durable impossible ; le démarrage local continue :\n%s",
            traceback.format_exc(),
        )
    return durable


async def _failover_snapshot_loop(
    bot,
    durable: DurableDatabaseReplica,
    coordinator: RedisFailoverLease,
) -> None:
    """Publie un snapshot partage regulier tant que ce processus detient le lease."""
    await bot.wait_until_ready()
    while coordinator.owns_lease and not bot.is_closed():
        try:
            result = await asyncio.wait_for(
                durable.snapshot(reason="failover_periodic", clean_shutdown=False),
                timeout=60,
            )
            coordinator.record_snapshot(result)
            if not result.get("stored"):
                logger.error("Snapshot failover non stocké : %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Snapshot failover périodique impossible.")
        await asyncio.sleep(coordinator.settings.snapshot_interval)


async def _run_active(
    coordinator: RedisFailoverLease | None = None,
    *,
    force_failover_restore: bool = False,
) -> None:
    bot = bot_main.BotAllInOne()
    bot.sentrix_failover = coordinator

    # V19 : le gate est attaché AVANT bot.start(). Il s'exécute après on_ready, donc avec
    # une vraie connexion Discord, de vrais serveurs/membres et le registre slash distant.
    # En cas d'incohérence critique il ferme le client ; le bootstrap transforme ensuite
    # cette fermeture en échec Railway au lieu de laisser tourner un build cassé.
    from cogs.live_command_gate_v19 import install as install_live_command_gate_v19
    install_live_command_gate_v19(bot)

    # Les handlers doivent être remplacés AVANT build_app() / start_dashboard().
    _install_discord_readiness_healthcheck()
    _install_sentrix_asset_route()

    watchdog_task: asyncio.Task | None = None
    snapshot_task: asyncio.Task | None = None

    if coordinator is not None:
        async def close_after_lease_loss() -> None:
            if not bot.is_closed():
                await bot.close()

        watchdog_task = asyncio.create_task(
            coordinator.maintain(close_after_lease_loss),
            name="sentrix-failover-lease-watchdog",
        )

    durable = await _prepare_durable_store(
        bot,
        force_failover_restore=force_failover_restore,
    )

    await bot.db.connect()
    if coordinator is not None:
        if not coordinator.owns_lease:
            raise RuntimeError("Lease failover perdu avant la connexion Discord.")
        bootstrap_snapshot = await asyncio.wait_for(
            durable.snapshot(reason="failover_promotion", clean_shutdown=False),
            timeout=60,
        )
        coordinator.record_snapshot(bootstrap_snapshot)
        if not bootstrap_snapshot.get("stored"):
            raise RuntimeError(f"Snapshot initial failover impossible : {bootstrap_snapshot}")
        snapshot_task = asyncio.create_task(
            _failover_snapshot_loop(bot, durable, coordinator),
            name="sentrix-failover-postgres-snapshots",
        )
    logger.info("Base prête pour le démarrage anticipé du dashboard Railway.")
    logger.info(
        "Sharding production actif : configuration=%s, runtime=%s.",
        config.SHARD_COUNT or "auto",
        getattr(bot, "shard_count", None) or "auto",
    )

    real_start_dashboard = bot_main.start_dashboard

    async def already_connected():
        return None

    bot.db.connect = already_connected
    bot_main.start_dashboard = _dashboard_already_started

    await real_start_dashboard(bot)
    logger.info("Dashboard Railway démarré avant la connexion Discord ; /health reste 503 jusqu'à on_ready.")

    try:
        async with bot:
            await bot.start(config.DISCORD_TOKEN)
        if coordinator is not None and not coordinator.owns_lease:
            raise RuntimeError("SentriX actif s'est arrêté après perte du lease failover.")
        if getattr(bot, "_sentrix_live_gate_failed", False):
            detail = str(getattr(bot, "_sentrix_live_gate_detail", "échec live inconnu"))[:2000]
            raise RuntimeError(f"Gate live commandes V19 en échec : {detail}")
    except Exception:
        logger.critical("Le processus Discord s'est arrêté :\n%s", traceback.format_exc())
        raise
    finally:
        for task in (snapshot_task, watchdog_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (snapshot_task, watchdog_task):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning("Tâche failover arrêtée avec une erreur.", exc_info=True)
        try:
            # Apres une perte de lease, ce disque n'est plus la source autoritaire : un
            # nouveau primaire a peut-etre deja restaure/ecrit sa copie. Ne jamais publier
            # alors un dernier snapshot stale qui pourrait gagner par son timestamp.
            may_publish_shutdown_snapshot = bool(
                coordinator is None or coordinator.owns_lease
            )
            if durable.configured and may_publish_shutdown_snapshot:
                await asyncio.wait_for(
                    durable.snapshot(reason="graceful_shutdown", clean_shutdown=True),
                    timeout=45,
                )
        except Exception:
            logger.warning("Snapshot durable d'arrêt impossible :\n%s", traceback.format_exc())
        try:
            infra = getattr(bot, "sentrix_infra", None)
            if infra is not None:
                await infra.close()
        except Exception:
            logger.warning("Fermeture de l'infrastructure Enterprise impossible :\n%s", traceback.format_exc())
        try:
            await bot.db.close()
        except Exception:
            logger.warning("Fermeture de la base impossible :\n%s", traceback.format_exc())
        try:
            await durable.close()
        except Exception:
            logger.warning("Fermeture du stockage durable impossible :\n%s", traceback.format_exc())


async def _start_standby_health(coordinator: RedisFailoverLease):
    """Garde le service Railway sain pendant qu'il attend sans ouvrir Discord."""
    async def health(_request):
        state = coordinator.public_state()
        return aiohttp_web.json_response(
            {
                "ok": True,
                "mode": "standby",
                "discord_ready": False,
                "failover": state,
            }
        )

    app = aiohttp_web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    await aiohttp_web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info("SentriX standby prêt sur le port %s; aucune connexion Discord ouverte.", port)
    return runner


async def run() -> None:
    settings = FailoverSettings.from_env()
    if not settings.enabled:
        await _run_active()
        return

    if config.CANARY_MODE:
        raise RuntimeError("Le Canary séparé ne doit pas activer SENTRIX_FAILOVER_ENABLED.")
    if not config.REDIS_URL:
        raise RuntimeError("Le failover SentriX exige REDIS_URL.")
    if not config.POSTGRES_URL:
        raise RuntimeError("Le failover SentriX exige POSTGRES_URL/DATABASE_URL.")

    coordinator = RedisFailoverLease(settings)
    standby_runner = None
    waited_for_another_process = False
    try:
        await coordinator.connect()

        if settings.role == "standby" and settings.standby_delay:
            standby_runner = await _start_standby_health(coordinator)
            coordinator.status = "standby_delay"
            await asyncio.sleep(settings.standby_delay)

        acquired = await coordinator.try_acquire()
        if not acquired:
            waited_for_another_process = True
            if standby_runner is None:
                standby_runner = await _start_standby_health(coordinator)
            while not await coordinator.try_acquire():
                await asyncio.sleep(settings.poll_interval)

        # Le serveur HTTP d'attente libere le port juste avant que le dashboard complet
        # prenne sa place. Le lease est deja renouvele pendant cette courte transition.
        if standby_runner is not None:
            await standby_runner.cleanup()
            standby_runner = None

        force_restore = waited_for_another_process or settings.role == "standby"
        await _run_active(
            coordinator,
            force_failover_restore=force_restore,
        )
    finally:
        if standby_runner is not None:
            await standby_runner.cleanup()
        await coordinator.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX.")
