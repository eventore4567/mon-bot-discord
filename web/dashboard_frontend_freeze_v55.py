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


def _ensure_v60_features_final(dashboard) -> bool:
    """Post-condition de production : le snapshot final DOIT contenir l'onglet avancé.

    L'intégrateur normal ``dashboard_v60_features_inline.install`` reste utilisé. Ce garde-fou
    travaille directement sur le document final juste avant son gel, afin qu'un ordre de
    chargement historique ou un état d'installation déjà marqué ne puisse plus faire perdre
    l'onglet ``Fonctions avancées`` en production.
    """
    try:
        from . import dashboard_v60_features_inline as features
    except Exception:
        logger.exception("Dashboard V60 : module des fonctions avancées introuvable au gel final.")
        return False

    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    marker = 'id="sentrix-v60-features-inline"'
    injected = False
    if marker not in html:
        if "</style>" not in html or "</body>" not in html:
            logger.error("Dashboard V60 : document final sans points d'insertion pour les fonctions avancées.")
            return False
        html = html.replace("</style>", features.INLINE_CSS + "\n</style>", 1)
        html = html.replace("</body>", features.INLINE_JS + "\n</body>", 1)
        dashboard.INDEX_HTML = html
        injected = True

    try:
        route_ok = bool(features._install_route_redirect())
    except Exception:
        logger.exception("Dashboard V60 : impossible d'armer la redirection de l'ancien centre des fonctions.")
        route_ok = False

    final_html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    present = marker in final_html and 'data-tab="features"' in final_html and "/feature-suite?embed=1&guild=" in final_html
    if not present:
        logger.error("Dashboard V60 : post-condition fonctions avancées ÉCHEC avant gel.")
        return False

    logger.info(
        "Dashboard V60 : fonctions avancées garanties dans le document final (injecté=%s route_redirect=%s octets=%s).",
        injected,
        route_ok,
        len(final_html.encode("utf-8")),
    )
    return route_ok


def _theme_secondary_pages_final() -> bool:
    """Harmonise TOUTES les pages d'administration isolées avec l'identité V60.

    Ce point est volontairement juste avant le gel : les modules Setup/Feature Suite ont déjà
    appliqué leurs anciens reworks, donc la feuille V60 arrive réellement en dernier. Le
    document principal ``/app`` n'est jamais passé à cet installateur.
    """
    try:
        from .dashboard_v60_secondary_theme import install as install_secondary_theme
        from . import setup_center
        from . import setup_dashboard
        from . import design_setup_dashboard
        from . import embed_center
        from . import owner_server_manager
        from . import operations_center
        from . import community_growth
        from . import engagement_hub
        from . import feature_suite_dashboard_v37
        from . import log_settings_dashboard_v32
        from . import ticket_center_v35
        from . import ticket_buttons_editor_v53
        from . import dashboard_control_center
        from . import feature_control_v36
    except Exception:
        logger.exception("Dashboard V60 : impossible de charger le thème commun des pages secondaires.")
        return False

    count = install_secondary_theme(
        setup_center,
        setup_dashboard,
        design_setup_dashboard,
        embed_center,
        owner_server_manager,
        operations_center,
        community_growth,
        engagement_hub,
        feature_suite_dashboard_v37,
        log_settings_dashboard_v32,
        ticket_center_v35,
        ticket_buttons_editor_v53,
        dashboard_control_center,
        feature_control_v36,
    )
    if count <= 0:
        logger.error("Dashboard V60 : aucune page secondaire n'a reçu le thème commun.")
        return False
    logger.info("Dashboard V60 : %s document(s) secondaire(s) utilisent maintenant la même palette et les mêmes formes que /app.", count)
    return True


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
    """Installe V60 final + fonctions avancées intégrées, harmonise les centres puis gèle."""
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
        suite_ok = False
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
                suite_ok = bool(install_v60_suite(dashboard))
                if not suite_ok:
                    logger.error("Dashboard V60 suite : installation refusée avant le gel.")
            except Exception:
                logger.exception("Dashboard V60 suite : installation impossible avant le gel.")
        if suite_ok:
            try:
                from .dashboard_v60_features_inline import install as install_v60_features_inline
                if not install_v60_features_inline(dashboard):
                    logger.error("Dashboard V60 : intégration initiale des fonctions avancées refusée.")
            except Exception:
                logger.exception("Dashboard V60 : intégration initiale des fonctions avancées impossible.")
            try:
                from .dashboard_v60_dm import install as install_v60_dm
                if not install_v60_dm(dashboard):
                    logger.error("Dashboard V60 DM : interface propriétaire non restaurée.")
            except Exception:
                logger.exception("Dashboard V60 DM : restauration impossible.")
            try:
                from .dashboard_v60_bootguard import install as install_v60_bootguard
                if not install_v60_bootguard(dashboard):
                    logger.error("Dashboard V60 bootguard : installation refusée.")
            except Exception:
                logger.exception("Dashboard V60 bootguard : installation impossible.")

        # IMPORTANT : vérification finale indépendante de l'ordre des anciennes couches.
        if v60_ok and not _ensure_v60_features_final(dashboard):
            logger.error("Dashboard V60 : les fonctions avancées ne sont pas garanties ; snapshot signalé incomplet.")

        # Les centres autonomes sont harmonisés après TOUS leurs anciens reworks, mais sans
        # modifier dashboard.INDEX_HTML. L'accueil V60 reste donc inchangé pixel pour pixel.
        if v60_ok and not _theme_secondary_pages_final():
            logger.error("Dashboard V60 : harmonisation visuelle des pages secondaires incomplète.")

        if not install(dashboard):
            logger.error(
                "Dashboard frontend : le gel pré-start a échoué ; /app ne doit pas être considéré stable."
            )

    no_store_then_freeze._sentrix_frontend_freeze_hook_v55 = True
    no_store_then_freeze._sentrix_original = current
    product._install_no_store_index = no_store_then_freeze
    logger.info("Dashboard V60 final armé : accueil + centres secondaires unifiés + fonctions inline + diagnostics + DM + bootguard + gel.")
    return True


__all__ = [
    "install",
    "install_product_prestart_hook",
    "_snapshot_is_usable",
    "_ensure_v60_features_final",
    "_theme_secondary_pages_final",
]
