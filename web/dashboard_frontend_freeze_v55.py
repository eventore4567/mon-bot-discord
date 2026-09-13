"""Gel final du dashboard SentriX.

Le backend historique conserve ses routes/API, mais ``/app`` est désormais servi depuis une
seule source frontend : :mod:`web.dashboard_unified_v2`. Les anciennes couches V60 -> V64
ne sont plus empilées pour fabriquer l'interface finale.
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
_UNIFIED_MARKER = 'id="sentrix-dashboard-unified-v2"'


def _snapshot_is_usable(html: str) -> tuple[bool, list[str]]:
    missing = [marker for marker in _REQUIRED_MARKERS if marker not in html]
    return not missing, missing


def _ensure_v60_features_final(dashboard) -> bool:
    """Compatibilité avec les anciens gates : l'UI héritée ne doit plus être rendue."""
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if _UNIFIED_MARKER in html:
        return True
    try:
        from .dashboard_v61_postfix import _legacy_feature_ui_present
        return not _legacy_feature_ui_present(html)
    except Exception:
        return 'id="sentrix-v60-features-inline"' not in html and 'id="sxFeaturesFrame"' not in html


def _theme_secondary_pages_final() -> bool:
    return True


def _is_unified_document(dashboard, html: str) -> bool:
    version = str(getattr(dashboard, "_sentrix_dashboard_version", "") or "")
    return version.startswith("unified-v2") or _UNIFIED_MARKER in html


def install(dashboard) -> bool:
    current = dashboard.handle_index
    if getattr(current, "_sentrix_frontend_freeze_v55", False):
        return True

    snapshot = str(getattr(dashboard, "INDEX_HTML", "") or "")
    usable, missing = _snapshot_is_usable(snapshot)
    if not usable:
        logger.error("Dashboard frontend non figé : marqueurs runtime absents=%s.", missing)
        return False

    if _is_unified_document(dashboard, snapshot):
        if _UNIFIED_MARKER not in snapshot:
            logger.error("Dashboard unifié non figé : marqueur principal absent.")
            return False
        forbidden = (
            'id="sentrix-v60-features-inline"',
            'id="sxFeaturesFrame"',
        )
        present = [marker for marker in forbidden if marker in snapshot]
        if present:
            logger.error("Dashboard unifié non figé : ancienne UI encore présente=%s.", present)
            return False
    else:
        # Fallback de compatibilité si un environnement ancien appelle directement install().
        version = str(getattr(dashboard, "_sentrix_dashboard_version", "") or "")
        if version.startswith("v64") and 'id="sentrix-v64-final"' not in snapshot:
            logger.error("Dashboard V64 non figé : verrou de navigation absent.")
            return False

    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]
    version = str(getattr(dashboard, "_sentrix_dashboard_version", "unified-v2"))

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


def _install_backend_compatibility(dashboard) -> None:
    """Conserve uniquement les extensions qui apportent des APIs réellement utilisées.

    Les modules ci-dessous peuvent encore injecter du HTML, mais cette sortie est remplacée
    ensuite par ``dashboard_unified_v2``. Leurs routes restent donc disponibles sans empiler
    leurs anciennes interfaces dans le document servi au navigateur.
    """
    try:
        from .dashboard_v60_diagnostics import install as install_diagnostics
        install_diagnostics(dashboard)
    except Exception:
        logger.exception("Dashboard unifié : API diagnostics impossible à installer.")

    try:
        from .dashboard_v62_compat import install as install_v62_compat
        install_v62_compat(dashboard)
    except Exception:
        logger.exception("Dashboard unifié : compatibilité V62 impossible à installer.")

    try:
        from .dashboard_v62_dense import install as install_v62
        install_v62(dashboard)
    except Exception:
        logger.exception("Dashboard unifié : API Tickets/Vérification V62 impossible à installer.")


def install_product_prestart_hook() -> bool:
    """Branche le frontend unifié au véritable pré-démarrage produit Railway."""
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
        _install_backend_compatibility(dashboard)

        try:
            from .dashboard_unified_v2 import install as install_unified
            unified_ok = bool(install_unified(dashboard))
        except Exception:
            unified_ok = False
            logger.exception("Dashboard unifié V2 : installation impossible.")

        if not unified_ok:
            logger.error("Dashboard unifié V2 absent : le gel final est refusé.")
            return

        if not install(dashboard):
            logger.error("Dashboard frontend : gel final échoué.")

    no_store_then_freeze._sentrix_frontend_freeze_hook_v55 = True
    no_store_then_freeze._sentrix_original = current
    product._install_no_store_index = no_store_then_freeze
    logger.info("Dashboard unifié V2 armé : APIs historiques conservées, frontend unique + gel immuable.")
    return True


__all__ = [
    "install",
    "install_product_prestart_hook",
    "_snapshot_is_usable",
    "_ensure_v60_features_final",
    "_theme_secondary_pages_final",
]
