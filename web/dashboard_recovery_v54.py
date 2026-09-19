"""Dashboard V54 — récupération Railway et démarrage web fail-safe.

Objectifs :
- ne plus dépendre d'un ancien domaine Railway codé en dur quand le service possède un
  RAILWAY_PUBLIC_DOMAIN plus récent ;
- accepter /dashboard et /dashboard/ comme alias stables de /app ;
- si une extension avancée casse build_app(), servir automatiquement le dashboard cœur
  au lieu de laisser le domaine Railway sans serveur HTTP ;
- respecter les wrappers build_app installés APRES Recovery V54 (notamment le proxy HA) ;
- ne jamais afficher une liste de serveurs vide/fausse pendant qu'une instance web HA est
  passive et attend encore la connexion Discord.

Le fallback ne contourne aucune sécurité : il réutilise les middlewares, sessions,
contrôles OAuth/CSRF et handlers canoniques de web.dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from urllib.parse import urlparse

from aiohttp import web

import config

logger = logging.getLogger("bot.dashboard-recovery-v54")


_GUILD_LOADER_OLD = '''async function loadGuilds(){const data=await json("/api/guilds");state.guilds=data.guilds;const select=$("serverSelect");select.innerHTML='<option value="">Choisissez un serveur</option>'+data.guilds.map(g=>`<option value="${g.installed?esc(g.id):"invite:"+esc(g.id)}">${esc(g.name)}${g.installed?"":" — ajouter SentriX"}</option>`).join("");const first=data.guilds.find(g=>g.installed);if(first){select.value=first.id;await selectGuild(first.id);}}'''

_GUILD_LOADER_NEW = '''async function loadGuilds(){const data=await json("/api/guilds");state.guilds=data.guilds||[];const select=$("serverSelect");if(data.discord_ready===false){select.innerHTML='<option value="">Connexion Discord en cours…</option>'+state.guilds.map(g=>`<option value="" disabled>${esc(g.name)} — vérification en cours</option>`).join("");$("pageSubtitle").textContent="SentriX se reconnecte à Discord. La liste des serveurs se mettra à jour automatiquement.";if(window.__sentrixGuildRetry)clearTimeout(window.__sentrixGuildRetry);window.__sentrixGuildRetry=setTimeout(()=>{if(state.user)loadGuilds().catch(()=>{});},Math.max(1500,Number(data.retry_after_ms)||2000));return;}if(window.__sentrixGuildRetry){clearTimeout(window.__sentrixGuildRetry);window.__sentrixGuildRetry=null;}select.innerHTML='<option value="">Choisissez un serveur</option>'+state.guilds.map(g=>`<option value="${g.installed?esc(g.id):"invite:"+esc(g.id)}">${esc(g.name)}${g.installed?"":" — ajouter SentriX"}</option>`).join("");const first=state.guilds.find(g=>g.installed);if(first){select.value=first.id;await selectGuild(first.id);}else{$('pageSubtitle').textContent=state.guilds.length?"Ajoutez SentriX à un serveur pour le configurer.":"Aucun serveur administrable trouvé sur ce compte Discord.";}}'''


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


async def _redirect_to_app(_request: web.Request):
    raise web.HTTPFound("/app")


def _add_dashboard_aliases(app: web.Application) -> None:
    existing = set()
    try:
        for route in app.router.routes():
            resource = getattr(route, "resource", None)
            canonical = getattr(resource, "canonical", None)
            if canonical:
                existing.add(str(canonical))
    except Exception:
        logger.warning("Étape non critique ignorée dans _add_dashboard_aliases", exc_info=True)
    for path in ("/dashboard", "/dashboard/"):
        if path not in existing:
            app.router.add_get(path, _redirect_to_app)


def _install_guild_loading_recovery(dashboard) -> None:
    """Rend /api/guilds et le sélecteur robustes quand le serveur web HA est passif.

    Le service primaire peut répondre en HTTP quelques secondes avant de posséder le lease
    Discord. Dans cet intervalle ``bot.get_guild`` est vide : l'ancien code transformait alors
    chaque serveur OAuth en faux « SentriX non installé ». On expose maintenant explicitement
    l'état indéterminé et le navigateur réessaie jusqu'à ce que la gateway soit prête.

    V54 optimise aussi deux chemins très chauds du dashboard : les permissions de tous les
    serveurs installés sont vérifiées en parallèle avec une concurrence bornée, et les cinq
    compteurs SQL de la fiche serveur sont regroupés dans une seule requête. Les contrôles de
    sécurité restent identiques : aucun serveur n'est retourné avant validation des droits.
    """
    if getattr(dashboard, "_sentrix_guild_loading_recovery_v54", False):
        return

    required = (
        "_manageable_guild",
        "handle_guilds",
        "_require_session",
        "_administrator_member",
        "_invite_url",
        "_json_error",
    )
    if not all(hasattr(dashboard, name) for name in required):
        return

    original_manageable = dashboard._manageable_guild
    original_guild_metrics = getattr(dashboard, "_guild_metrics", None)

    async def manageable_guild_ha_safe(request: web.Request, guild_id: int):
        bot = request.app["bot"]
        if not bot.is_ready():
            session, error = dashboard._require_session(request)
            if error:
                return None, None, error
            return (
                session,
                None,
                dashboard._json_error(
                    "SentriX termine sa connexion à Discord. Réessayez dans quelques secondes.",
                    503,
                ),
            )
        return await original_manageable(request, guild_id)

    async def guild_metrics_fast(db, guild_id: int) -> dict:
        if original_guild_metrics is None:
            return {}
        try:
            row = await db.fetchone(
                """
                SELECT
                    (SELECT COUNT(*) FROM warnings WHERE guild_id = ?) AS warnings,
                    (SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'ouvert') AS open_tickets,
                    (SELECT COUNT(*) FROM levels WHERE guild_id = ?) AS profiles,
                    (SELECT COUNT(*) FROM economy WHERE guild_id = ?) AS economy_accounts,
                    (SELECT COUNT(*) FROM command_logs WHERE guild_id = ? AND timestamp >= ?) AS commands_24h
                """,
                (
                    guild_id,
                    guild_id,
                    guild_id,
                    guild_id,
                    guild_id,
                    dashboard.now() - 86400,
                ),
            )
            if row is None:
                raise RuntimeError("metric query returned no row")
            return {
                "warnings": int(row["warnings"] or 0),
                "open_tickets": int(row["open_tickets"] or 0),
                "profiles": int(row["profiles"] or 0),
                "economy_accounts": int(row["economy_accounts"] or 0),
                "commands_24h": int(row["commands_24h"] or 0),
            }
        except Exception:
            # Une installation plus ancienne peut ne pas encore posséder une des tables.
            # On conserve alors exactement le comportement tolérant du cœur historique.
            return await original_guild_metrics(db, guild_id)

    async def handle_guilds_ha_safe(request: web.Request):
        started = time.perf_counter()
        session, error = dashboard._require_session(request)
        if error:
            return error

        bot = request.app["bot"]
        ready = bool(bot.is_ready())
        user_id = int(session["user"]["id"])
        session_guilds = list(session.get("guilds", []))

        if not ready:
            guilds = [
                {
                    **item,
                    "installed": None,
                    "invite_url": None,
                }
                for item in session_guilds
            ]
            guilds.sort(key=lambda item: item["name"].casefold())
        else:
            permission_gate = asyncio.Semaphore(6)

            async def validated_item(item: dict):
                guild_id = int(item["id"])
                installed_guild = bot.get_guild(guild_id)
                installed = installed_guild is not None
                if installed:
                    async with permission_gate:
                        member = await dashboard._administrator_member(installed_guild, user_id)
                    if member is None:
                        return None
                return {
                    **item,
                    "installed": installed,
                    "invite_url": None if installed else dashboard._invite_url(bot, guild_id),
                }

            results = await asyncio.gather(
                *(validated_item(item) for item in session_guilds),
                return_exceptions=True,
            )
            guilds = []
            for item, result in zip(session_guilds, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Dashboard : vérification du serveur %s impossible (%s).",
                        item.get("id"),
                        type(result).__name__,
                    )
                    continue
                if result is not None:
                    guilds.append(result)
            guilds.sort(key=lambda item: (not bool(item["installed"]), item["name"].casefold()))

        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms >= 1000:
            logger.warning(
                "Dashboard lent : GET /api/guilds %.0f ms pour %s serveur(s) OAuth.",
                elapsed_ms,
                len(session_guilds),
            )
        response = web.json_response({
            "guilds": guilds,
            "discord_ready": ready,
            "retry_after_ms": 2000 if not ready else None,
        })
        response.headers["Server-Timing"] = f"guilds;dur={elapsed_ms:.1f}"
        return response

    dashboard._manageable_guild = manageable_guild_ha_safe
    dashboard.handle_guilds = handle_guilds_ha_safe
    if original_guild_metrics is not None:
        dashboard._guild_metrics = guild_metrics_fast

    html = str(getattr(dashboard, "INDEX_HTML", ""))
    if _GUILD_LOADER_OLD in html:
        dashboard.INDEX_HTML = html.replace(_GUILD_LOADER_OLD, _GUILD_LOADER_NEW, 1)
    elif "Connexion Discord en cours…" not in html:
        logger.warning(
            "Dashboard Recovery V54 : fonction loadGuilds inconnue, correctif frontend non injecté."
        )

    dashboard._sentrix_guild_loading_recovery_v54 = True


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
    _install_guild_loading_recovery(dashboard)

    async def resilient_start_dashboard(bot):
        if getattr(bot, "_sentrix_dashboard_runner_v54", None) is not None:
            return

        last_error: Exception | None = None
        for attempt in range(1, 4):
            runner = None
            mode = "complet"
            try:
                try:
                    app = dashboard.build_app(bot)
                    _add_dashboard_aliases(app)
                except Exception as exc:
                    last_error = exc
                    mode = "secours"
                    logger.exception(
                        "Dashboard complet impossible ; démarrage immédiat du cœur sécurisé."
                    )
                    app = _build_core_app(dashboard, bot)

                # Apply after the final builder AND the recovery path. A plugin failure
                # must never reopen the API or bypass the public hostname boundary.
                from .http_surfaces import apply as apply_http_surfaces
                apply_http_surfaces(app, dashboard)

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
                        "Dashboard local sans OAuth prêt ; en HA passif les requêtes web "
                        "doivent être routées vers le leader. Si cette instance est leader, "
                        "vérifiez DISCORD_CLIENT_SECRET."
                    )
                return
            except Exception as exc:
                last_error = exc
                if runner is not None:
                    try:
                        await runner.cleanup()
                    except Exception:
                        logger.warning("Étape non critique ignorée dans resilient_start_dashboard", exc_info=True)
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


__all__ = ["configure_public_url", "install", "_install_guild_loading_recovery"]