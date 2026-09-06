"""Dashboard frontend freeze — publication immuable de ``/app``.

Le gel V55 reste le mécanisme de stabilité : le document final est capturé une seule fois
avant ``build_app()`` puis servi tel quel pendant tout le runtime. Depuis V60, le frontend
reconstruit est installé exactement à ce point, après les routes produit (Tickets, Embeds,
ping-role...) mais avant le snapshot. Les anciennes couches conservent donc leurs endpoints
sans pouvoir réécrire l'interface finalement publiée.
"""
from __future__ import annotations

import hashlib
import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard-frontend-v55")

_REQUIRED_MARKERS = (
    'async function loadSession()',
    'async function loadGuilds()',
    'async function selectGuild(value)',
    '"/api/me"',
    '"/api/guilds"',
)


def _snapshot_is_usable(html: str) -> tuple[bool, list[str]]:
    missing = [marker for marker in _REQUIRED_MARKERS if marker not in html]
    return not missing, missing


def install(dashboard) -> bool:
    """Fige le HTML de ``/app`` avant que le serveur aiohttp ne lie ses routes."""
    current = dashboard.handle_index
    if getattr(current, "_sentrix_frontend_freeze_v55", False):
        return True

    snapshot = str(getattr(dashboard, "INDEX_HTML", "") or "")
    usable, missing = _snapshot_is_usable(snapshot)
    if not usable:
        logger.error(
            "Dashboard frontend non figé : snapshot pré-start incomplet, marqueurs absents=%s.",
            missing,
        )
        return False

    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]
    version = str(getattr(dashboard, "_sentrix_dashboard_version", "v55"))

    async def frozen_handle_index(request: web.Request):
        if request.path == "/app":
            response = web.Response(text=snapshot, content_type="text/html")
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-SentriX-Dashboard"] = f"{version}-frozen"
            response.headers["X-SentriX-Frontend-SHA"] = digest
            return response
        return await current(request)

    frozen_handle_index._sentrix_frontend_freeze_v55 = True
    frozen_handle_index._sentrix_original = current
    frozen_handle_index._sentrix_snapshot_sha = digest

    dashboard.handle_index = frozen_handle_index
    dashboard._sentrix_frontend_snapshot_v55 = snapshot
    dashboard._sentrix_frontend_snapshot_sha_v55 = digest
    logger.info(
        "Dashboard %s figé avant build_app : %s octets, sha256=%s.",
        version,
        len(snapshot.encode("utf-8")),
        digest,
    )
    return True


def install_product_prestart_hook() -> bool:
    """Installe V60 MAX suite + diagnostics après les routes produit puis fige le document."""
    try:
        import sentrix_product_update as product
    except Exception:
        logger.exception("Dashboard freeze : sentrix_product_update indisponible.")
        return False

    current = product._install_no_store_index
    if getattr(current, "_sentrix_frontend_freeze_hook_v55", False):
        return True

    def no_store_then_freeze(dashboard) -> None:
        current(dashboard)
        v60_ok = False
        max_ok = False
        try:
            from .dashboard_rework_v60 import install as install_v60
            v60_ok = bool(install_v60(dashboard))
            if not v60_ok:
                logger.error("Dashboard V60 : installation refusée avant le gel.")
        except Exception:
            logger.exception("Dashboard V60 : installation impossible avant le gel.")
        if v60_ok:
            try:
                from .dashboard_v60_max import install as install_v60_max
                max_ok = bool(install_v60_max(dashboard))
                if not max_ok:
                    logger.error("Dashboard V60 MAX : installation refusée avant le gel.")
            except Exception:
                logger.exception("Dashboard V60 MAX : installation impossible avant le gel.")
            try:
                from .dashboard_v60_diagnostics import install as install_v60_diagnostics
                if not install_v60_diagnostics(dashboard):
                    logger.error("Dashboard V60 diagnostics : installation refusée avant le bind HTTP.")
            except Exception:
                logger.exception("Dashboard V60 diagnostics : installation impossible avant le bind HTTP.")
        if max_ok:
            try:
                from .dashboard_v60_suite import install as install_v60_suite
                if not install_v60_suite(dashboard):
                    logger.error("Dashboard V60 suite : installation refusée avant le gel.")
            except Exception:
                logger.exception("Dashboard V60 suite : installation impossible avant le gel.")
        if not install(dashboard):
            logger.error(
                "Dashboard frontend : le gel pré-start a échoué ; /app ne doit pas être considéré stable."
            )

    no_store_then_freeze._sentrix_frontend_freeze_hook_v55 = True
    no_store_then_freeze._sentrix_original = current
    product._install_no_store_index = no_store_then_freeze
    logger.info("Dashboard V60 MAX suite armé : rework + diagnostics + accès commandes + gel pré-start.")
    return True


__all__ = ["install", "install_product_prestart_hook", "_snapshot_is_usable"]
