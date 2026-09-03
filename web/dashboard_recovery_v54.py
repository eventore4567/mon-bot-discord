"""Dashboard V54 — récupération Railway et démarrage web fail-safe.

Objectifs :
- ne plus dépendre d'un ancien domaine Railway codé en dur quand le service possède un
  RAILWAY_PUBLIC_DOMAIN plus récent ;
- accepter /dashboard et /dashboard/ comme alias stables de /app ;
- si une extension avancée casse build_app(), servir automatiquement le dashboard cœur
  au lieu de laisser le domaine Railway sans serveur HTTP.

Le fallback ne contourne aucune sécurité : il réutilise les middlewares, sessions,
contrôles OAuth/CSRF et handlers canoniques de web.dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlparse

from aiohttp import web

import config

logger = logging.getLogger("bot.dashboard-recovery-v54")


def _strip_dashboard_suffix(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    for suffix in ("/oauth/callback", "/dashboard", "/app"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
    return value


def _railway_url() -> str:
    domain = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().strip("/")
    if not domain:
        return ""
    if domain.startswith(("https://", "http://")):
        return domain.rstrip("/")
    return f"https://{domain}"


def configure_public_url() -> str:
    """Choisit une URL dashboard qui suit le domaine réel du service principal Railway."""
    explicit = _strip_dashboard_suffix(os.getenv("DASHBOARD_PUBLIC_URL") or "")
    railway = _railway_url()
    role = (os.getenv("SENTRIX_FAILOVER_ROLE") or "").strip().casefold()

    selected = explicit
    if explicit and railway and role == "primary":
        # Une ancienne URL *.up.railway.app enregistrée manuellement devient obsolète si
        # Railway régénère/change le domaine du service. Un domaine custom reste prioritaire.
        try:
            explicit_host = (urlparse(explicit).hostname or "").casefold()
            railway_host = (urlparse(railway).hostname or "").casefold()
        except Exception:
            explicit_host = railway_host = ""
        if (
            explicit_host.endswith(".up.railway.app")
            and railway_host.endswith(".up.railway.app")
            and explicit_host != railway_host
        ):
            selected = railway
            logger.warning(
                "Dashboard : ancienne URL Railway %s remplacée par le domaine courant %s.",
                explicit_host,
                railway_host,
            )
    elif not selected and railway and role != "standby":
        selected = railway

    if not selected:
        selected = _strip_dashboard_suffix(getattr(config, "DASHBOARD_PUBLIC_URL", ""))
    if not selected:
        selected = "http://127.0.0.1:8080"

    if not selected.startswith(("https://", "http://")):
        selected = f"https://{selected.lstrip('/')}"

    config.DASHBOARD_PUBLIC_URL = selected.rstrip("/")
    config.DASHBOARD_APP_URL = f"{config.DASHBOARD_PUBLIC_URL}/app"
    config.DASHBOARD_CALLBACK_URL = f"{config.DASHBOARD_PUBLIC_URL}/oauth/callback"
    return config.DASHBOARD_PUBLIC_URL


def _redirect_to_app(_request: web.Request):
    raise web.HTTPFound("/app")


def _add_dashboard_aliases(app: web.Application) -> None:
    # Les alias sont ajoutés seulement s'ils n'existent pas déjà. aiohttp lève RuntimeError
    # sur une route dupliquée ; cette vérification évite qu'un correctif de compatibilité
    # devienne lui-même une cause de panne.
    existing = set()
    try:
        for route in app.router.routes():
            resource = getattr(route, "resource", None)
            canonical = getattr(resource, "canonical", None)
            if canonical:
                existing.add(str(canonical))
    except Exception:
        pass
    for path in ("/dashboard", "/dashboard/"):
        if path not in existing:
            app.router.add_get(path, _redirect_to_app)


def _build_core_app(dashboard, bot) -> web.Application:
    """Reconstruit uniquement le cœur officiel quand un plugin avancé casse build_app."""
    app = web.Application(
        middlewares=[dashboard.security_headers],
        client_max_size=64 * 1024,
    )
    app["bot"] = bot
    app["sessions"] = {}
    app["oauth_states"] = {}
    app["write_limits"] = {}

    app.router.add_get("/", dashboard.handle_index)
    app.router.add_get("/app", dashboard.handle_index)
    app.router.add_get("/dashboard", _redirect_to_app)
    app.router.add_get("/dashboard/", _redirect_to_app)
    app.router.add_get("/health", dashboard.handle_health)
    app.router.add_get("/login", dashboard.handle_login)
    app.router.add_get("/oauth/callback", dashboard.handle_callback)
    app.router.add_post("/logout", dashboard.handle_logout)
    app.router.add_get("/api/public", dashboard.handle_public)
    app.router.add_get("/api/me", dashboard.handle_me)
    app.router.add_get("/api/guilds", dashboard.handle_guilds)
    app.router.add_get("/api/guilds/{guild_id}", dashboard.handle_guild)
    app.router.add_put("/api/guilds/{guild_id}/settings", dashboard.handle_update_guild)
    app.router.add_post(
        "/api/guilds/{guild_id}/notifications",
        dashboard.handle_create_social_notification,
    )
    app.router.add_delete(
        "/api/guilds/{guild_id}/notifications/{notification_id}",
        dashboard.handle_delete_social_notification,
    )
    app.router.add_get(
        "/api/guilds/{guild_id}/sanctions",
        dashboard.handle_sanctions,
    )
    app.router.add_post(
        "/api/guilds/{guild_id}/sanctions/{user_id}/{action}",
        dashboard.handle_sanction_action,
    )
    return app


def install(dashboard) -> None:
    if getattr(dashboard, "_sentrix_dashboard_recovery_v54", False):
        return

    public_url = configure_public_url()
    full_build_app = dashboard.build_app

    async def resilient_start_dashboard(bot):
        if getattr(bot, "_sentrix_dashboard_runner_v54", None) is not None:
            return

        last_error: Exception | None = None
        for attempt in range(1, 4):
            runner = None
            mode = "complet"
            try:
                try:
                    app = full_build_app(bot)
                    _add_dashboard_aliases(app)
                except Exception as exc:
                    last_error = exc
                    mode = "secours"
                    logger.exception(
                        "Dashboard complet impossible ; démarrage immédiat du cœur sécurisé."
                    )
                    app = _build_core_app(dashboard, bot)

                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, "0.0.0.0", config.DASHBOARD_PORT)
                await site.start()

                bot._sentrix_dashboard_runner_v54 = runner
                bot._sentrix_dashboard_site_v54 = site
                bot._sentrix_dashboard_mode_v54 = mode
                logger.info(
                    "Dashboard SentriX actif (%s) port=%s url=%s/app",
                    mode,
                    config.DASHBOARD_PORT,
                    public_url,
                )
                if not dashboard._oauth_ready(bot):
                    logger.warning(
                        "Dashboard ouvert mais OAuth indisponible : DISCORD_CLIENT_SECRET manque."
                    )
                return
            except Exception as exc:
                last_error = exc
                if runner is not None:
                    try:
                        await runner.cleanup()
                    except Exception:
                        pass
                logger.exception(
                    "Démarrage dashboard tentative %s/3 impossible.", attempt
                )
                if attempt < 3:
                    await asyncio.sleep(float(attempt))

        logger.error(
            "Dashboard indisponible après 3 tentatives (%s). Le bot Discord continue.",
            type(last_error).__name__ if last_error else "erreur inconnue",
        )

    resilient_start_dashboard._sentrix_dashboard_recovery_v54 = True
    resilient_start_dashboard._sentrix_original = dashboard.start_dashboard
    dashboard.start_dashboard = resilient_start_dashboard
    dashboard._sentrix_dashboard_recovery_v54 = True
    logger.info("Dashboard Recovery V54 installé ; URL publique=%s", public_url)


__all__ = ["configure_public_url", "install"]
