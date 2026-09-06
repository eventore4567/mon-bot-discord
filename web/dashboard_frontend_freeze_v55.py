"""Gel final du dashboard SentriX.

V62 conserve le mécanisme de snapshot immuable introduit en V55. V61 remplace les anciens
centres visuels par une seule application ``/app`` et V62 termine cette application avec les
éditeurs denses Vérification/Tickets et la navigation sans raccourcis externes.
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
    """Compatibilité ancienne : vérifie qu'aucune vraie UI Feature Suite ne reste."""
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    try:
        from .dashboard_v61_postfix import _legacy_feature_ui_present
        return not _legacy_feature_ui_present(html)
    except Exception:
        return 'id="sentrix-v60-features-inline"' not in html and 'id="sxFeaturesFrame"' not in html


def _theme_secondary_pages_final() -> bool:
    """Compatibilité ancienne : V61/V62 ne servent plus les centres comme interfaces utilisateur."""
    return True


def _is_v61_document(dashboard, html: str) -> bool:
    version = str(getattr(dashboard, "_sentrix_dashboard_version", "") or "")
    return version.startswith(("v61", "v62")) or 'id="sentrix-v61-unified"' in html


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

    if _is_v61_document(dashboard, snapshot):
        required_v61 = (
            'id="sentrix-v61-unified"',
            "Configuration serveur",
            "Mini-jeux",
            "Design",
            "Statut SentriX",
            "v61Built",
        )
        absent = [marker for marker in required_v61 if marker not in snapshot]
        try:
            from .dashboard_v61_postfix import _legacy_feature_ui_present
            legacy_present = _legacy_feature_ui_present(snapshot)
        except Exception:
            legacy_present = 'id="sentrix-v60-features-inline"' in snapshot or 'id="sxFeaturesFrame"' in snapshot
        if absent or legacy_present:
            logger.error("Dashboard V61/V62 non figé : requis absents=%s ancienne UI features=%s.", absent, legacy_present)
            return False

    version = str(getattr(dashboard, "_sentrix_dashboard_version", "") or "")
    if version.startswith("v62"):
        required_v62 = (
            'id="sentrix-v62-dense"',
            "Vérification & règlement",
            "Tickets v2 inline",
            "/api/guilds/${encodeURIComponent(state.guildId)}/v62",
        )
        absent_v62 = [marker for marker in required_v62 if marker not in snapshot]
        if absent_v62:
            logger.error("Dashboard V62 non figé : marqueurs finaux absents=%s.", absent_v62)
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
    logger.info("Dashboard %s figé : %s octets, sha256=%s.", version, len(snapshot.encode("utf-8")), digest)
    return True


def install_product_prestart_hook() -> bool:
    """Construit V60, pose V61 puis V62 en dernier et fige ``/app``."""
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
            logger.debug("Dashboard V60 non applicable à ce document minimal.", exc_info=True)
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

        v61_ok = False
        if suite_ok:
            try:
                from .dashboard_v61_unified import install as install_v61
                v61_ok = bool(install_v61(dashboard))
            except Exception:
                logger.exception("Dashboard V61 : installation impossible.")

        postfix_ok = False
        if v61_ok:
            try:
                from .dashboard_v61_postfix import install as install_v61_postfix
                postfix_ok = bool(install_v61_postfix(dashboard))
            except Exception:
                logger.exception("Dashboard V61 postfix : installation impossible.")

        v62_ok = False
        if postfix_ok:
            try:
                from .dashboard_v62_dense import install as install_v62
                v62_ok = bool(install_v62(dashboard))
            except Exception:
                logger.exception("Dashboard V62 dense : installation impossible.")

        if v61_ok and not postfix_ok:
            logger.error("Dashboard V61 final absent : refus de considérer le frontend comme final.")
        elif postfix_ok and not _ensure_v60_features_final(dashboard):
            logger.error("Dashboard V61 : l'ancienne Feature Suite est encore rendue après postfix.")
        elif postfix_ok and not v62_ok:
            logger.error("Dashboard V62 dense absent : Tickets/Vérification ne sont pas considérés finalisés.")

        if not install(dashboard):
            logger.error("Dashboard frontend : gel final échoué.")

    no_store_then_freeze._sentrix_frontend_freeze_hook_v55 = True
    no_store_then_freeze._sentrix_original = current
    product._install_no_store_index = no_store_then_freeze
    logger.info("Dashboard V62 armé : V61 unifié + configuration dense + gel final.")
    return True


__all__ = ["install", "install_product_prestart_hook", "_snapshot_is_usable", "_ensure_v60_features_final", "_theme_secondary_pages_final"]
