"""Gel final du dashboard SentriX.

V61 conserve le mécanisme de snapshot immuable introduit en V55, mais remplace définitivement
les anciens centres visuels par une seule application ``/app``. Les routes/API historiques
restent disponibles au backend ; leurs pages autonomes sont redirigées par V61.
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


def _ensure_v60_features_final(dashboard) -> bool:
    """Compatibilité ancienne : la Feature Suite générique est volontairement supprimée.

    Cette fonction existait dans quelques audits. Elle ne doit plus injecter quoi que ce soit :
    V61 expose directement les réglages utiles dans le dashboard principal.
    """
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    return 'data-tab="features"' not in html and 'id="sentrix-v60-features-inline"' not in html


def _theme_secondary_pages_final() -> bool:
    """Compatibilité ancienne : V61 ne sert plus les centres comme interfaces utilisateur."""
    return True


def install(dashboard) -> bool:
    """Fige le HTML de ``/app`` avant que le serveur aiohttp ne lie ses routes."""
    current = dashboard.handle_index
    if getattr(current, "_sentrix_frontend_freeze_v55", False):
        return True

    snapshot = str(getattr(dashboard, "INDEX_HTML", "") or "")
    usable, missing = _snapshot_is_usable(snapshot)
    if not usable:
        logger.error("Dashboard frontend non figé : snapshot pré-start incomplet, marqueurs absents=%s.", missing)
        return False

    # Post-conditions V61 : une seule interface et aucun retour de la Feature Suite générique.
    required_v61 = ('id="sentrix-v61-unified"', 'data-tab="setup"', 'data-tab="games"', 'data-tab="design"', 'data-tab="status"')
    absent = [marker for marker in required_v61 if marker not in snapshot]
    forbidden = [marker for marker in ('data-tab="features"', 'id="sentrix-v60-features-inline"') if marker in snapshot]
    if absent or forbidden:
        logger.error("Dashboard V61 non figé : requis absents=%s interdits présents=%s.", absent, forbidden)
        return False

    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]
    version = str(getattr(dashboard, "_sentrix_dashboard_version", "v61"))

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
    logger.info("Dashboard %s figé : %s octets, sha256=%s.", version, len(snapshot.encode("utf-8")), digest)
    return True


def install_product_prestart_hook() -> bool:
    """Construit V60, ajoute les fonctions sûres, pose V61 en dernier puis fige ``/app``."""
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
        v60_ok = max_ok = suite_ok = False
        try:
            from .dashboard_rework_v60 import install as install_v60
            v60_ok = bool(install_v60(dashboard))
        except Exception:
            logger.exception("Dashboard V60 : installation impossible.")
        if v60_ok:
            try:
                from .dashboard_v60_max import install as install_v60_max
                max_ok = bool(install_v60_max(dashboard))
            except Exception:
                logger.exception("Dashboard V60 MAX : installation impossible.")
            try:
                from .dashboard_v60_diagnostics import install as install_v60_diagnostics
                install_v60_diagnostics(dashboard)
            except Exception:
                logger.exception("Dashboard diagnostics : installation impossible.")
        if max_ok:
            try:
                from .dashboard_v60_suite import install as install_v60_suite
                suite_ok = bool(install_v60_suite(dashboard))
            except Exception:
                logger.exception("Dashboard V60 suite : installation impossible.")
        if suite_ok:
            try:
                from .dashboard_v60_dm import install as install_v60_dm
                install_v60_dm(dashboard)
            except Exception:
                logger.exception("Dashboard DM : restauration impossible.")
            try:
                from .dashboard_v60_bootguard import install as install_v60_bootguard
                install_v60_bootguard(dashboard)
            except Exception:
                logger.exception("Dashboard bootguard : installation impossible.")

        # V61 est TOUJOURS la dernière couche visuelle. Elle reconstruit la navigation,
        # supprime « Fonctions avancées » et redirige les anciens centres vers /app.
        v61_ok = False
        if suite_ok:
            try:
                from .dashboard_v61_unified import install as install_v61
                v61_ok = bool(install_v61(dashboard))
            except Exception:
                logger.exception("Dashboard V61 : installation impossible.")

        if not v61_ok:
            logger.error("Dashboard V61 absent : refus de considérer le frontend comme final.")
        elif not _ensure_v60_features_final(dashboard):
            logger.error("Dashboard V61 : l'ancien onglet Fonctions avancées est encore présent.")

        if not install(dashboard):
            logger.error("Dashboard frontend : gel final échoué.")

    no_store_then_freeze._sentrix_frontend_freeze_hook_v55 = True
    no_store_then_freeze._sentrix_original = current
    product._install_no_store_index = no_store_then_freeze
    logger.info("Dashboard V61 armé : interface DraftBot-like unique, anciens centres retirés, gel final activé.")
    return True


__all__ = ["install", "install_product_prestart_hook", "_snapshot_is_usable", "_ensure_v60_features_final", "_theme_secondary_pages_final"]
