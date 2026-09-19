"""Autorité finale du dashboard : un seul programme frontend servi sur ``/app``.

Historique : ce module empilait vingt couches (V4 → V27) qui réécrivaient ``INDEX_HTML``
ou la réponse HTTP à chaque requête. Le frontend est maintenant assemblé une fois par
:mod:`web.dashboard_unified_v2` ; ce finalizer remet ce document unique comme snapshot
servi juste avant la construction aiohttp et vérifie qu'aucune ancienne couche ne s'est
réinsérée. Les backends de routes encore utilisés sont installés par
``railway_ha_product_boot`` avant la capture de ``build_app``.

Les fichiers des anciennes couches restent sur disque jusqu'à leur suppression contrôlée
(lot 7 de la refonte) ; ils ne sont plus exécutés pour ``/app``.
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger("bot.dashboard-finalizer-v7")

UNIFIED_MARKER = 'id="sentrix-dashboard-unified-v2"'

# Marqueurs des couches historiques : leur présence dans le document servi est une erreur.
LEGACY_MARKERS = (
    'id="sentrix-control-center-js"',
    'id="sentrix-control-center-v3-js"',
    'id="sentrix-premium-ui-v4-js"',
    'id="sentrix-section-variants-v5-js"',
    'id="sentrix-dashboard-verification-v6-js"',
    'id="sentrix-unified-adapter-v9-js"',
    'id="sentrix-growth-v12-js"',
    'id="sentrix-dashboard-visibility-v13-js"',
    "__sentrixLiveResponseV15",
    "__sentrixActionHubV17",
    "__sentrixProductUiV18",
    'id="sentrix-dashboard-v19-polish-js"',
    'id="sentrix-dashboard-visual-finish-v23-js"',
    'id="sentrix-dashboard-button-system-v24-js"',
    'id="sentrix-dashboard-motion-system-v25-js"',
    'id="sentrix-dashboard-visible-motion-v26-js"',
    'id="sentrix-dashboard-motion-audio-v27-js"',
    'id="sentrix-ticket-simple-v97-js"',
    'id="sentrix-embed-runtime-core"',
    'id="sentrix-ops-suite-js"',
    'id="sentrix-unified-product-ux-v3"',
    'id="sentrix-background-loading-guard-v3-js"',
    "setInterval(loadPublic",
)

def _unified_program() -> str:
    from web import dashboard_unified_v2
    return str(dashboard_unified_v2.INDEX_HTML or "")


def _count(html: str, needle: str) -> int:
    return html.count(needle)


def verify_single_program(html: str) -> list[str]:
    """Retourne la liste des problèmes détectés dans le document servi (vide = OK)."""
    problems: list[str] = []
    if UNIFIED_MARKER not in html:
        problems.append("programme unifié absent")
    scripts = _count(html, "<script") - _count(html, 'type="application/json"')
    if scripts != 1:
        problems.append(f"{scripts} <script> exécutables au lieu de 1")
    if _count(html, "<style") != 1:
        problems.append(f"{_count(html, '<style')} <style> au lieu de 1")
    for marker in LEGACY_MARKERS:
        if marker in html:
            problems.append(f"couche historique présente : {marker}")
    for required in ("async function loadSession()", "async function selectGuild(value)", "/api/me", "/api/guilds"):
        if required not in html:
            problems.append(f"contrat runtime absent : {required}")
    return problems


def _restore_single_program(dashboard) -> str:
    html = _unified_program()
    dashboard.INDEX_HTML = html
    dashboard._sentrix_dashboard_version = "unified-v2"
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
    # Le gel V55 sert ``dashboard._sentrix_frontend_snapshot_v55`` : on le met à jour pour
    # que la requête ``/app`` renvoie exactement ce document.
    dashboard._sentrix_frontend_snapshot_v55 = html
    dashboard._sentrix_frontend_snapshot_sha_v55 = digest
    return digest


def install() -> bool:
    from web import dashboard

    # Les backends de routes encore utilisés (V3 ops, V6 vérification, V12 growth, V18) sont
    # installés par railway_ha_product_boot AVANT la capture de build_app : ici on ne fait
    # que remettre le document unique et vérifier qu'aucune couche ne l'a réécrit.
    digest = _restore_single_program(dashboard)
    problems = verify_single_program(str(dashboard.INDEX_HTML or ""))
    if problems:
        raise RuntimeError("Dashboard : programme unique invalide — " + " ; ".join(problems))

    handler = getattr(dashboard, "handle_index", None)
    chain = []
    while handler is not None:
        chain.append(getattr(handler, "__name__", type(handler).__name__))
        handler = getattr(handler, "_sentrix_previous_handler", None) or getattr(handler, "_sentrix_original", None)
    for forbidden in ("live_index", "native_motion_index"):
        if forbidden in chain:
            raise RuntimeError(f"Dashboard : le patch de réponse {forbidden} est encore branché sur /app")

    logger.warning(
        "Dashboard : programme unique servi (sha=%s, %s octets, chaîne=%s).",
        digest, len(str(dashboard.INDEX_HTML).encode("utf-8")), " > ".join(chain),
    )
    return True


__all__ = ["install", "verify_single_program", "LEGACY_MARKERS", "UNIFIED_MARKER"]
