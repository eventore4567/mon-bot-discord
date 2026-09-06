"""Dashboard V55 — frontend immuable pendant tout le runtime.

Le dashboard SentriX démarre volontairement avant Discord sur Railway. Plusieurs couches
chargées ensuite par les cogs historiques peuvent encore modifier ``dashboard.INDEX_HTML``.
Comme l'ancien handler relisait cette variable globale à CHAQUE requête, deux ouvertures de
``/app`` au sein du même déploiement pouvaient recevoir deux programmes JavaScript différents.

V55 prend un snapshot une seule fois, après l'installation des fonctions dashboard pré-start
mais AVANT ``build_app()``. La route aiohttp ``/app`` est ensuite liée à un handler qui sert
uniquement ce snapshot. Les cogs tardifs peuvent conserver leurs routes/backend sans pouvoir
réécrire le programme frontend déjà publié.
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
    """Fige le HTML de ``/app`` avant que le serveur aiohttp ne lie ses routes.

    L'installation est idempotente. ``/`` continue d'utiliser le handler public courant ;
    seul ``/app`` est figé, car c'est la surface d'administration qui subissait les
    réécritures tardives.
    """
    current = dashboard.handle_index
    if getattr(current, "_sentrix_frontend_freeze_v55", False):
        return True

    snapshot = str(getattr(dashboard, "INDEX_HTML", "") or "")
    usable, missing = _snapshot_is_usable(snapshot)
    if not usable:
        logger.error(
            "Dashboard V55 non installé : snapshot pré-start incomplet, marqueurs absents=%s.",
            missing,
        )
        return False

    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]

    async def frozen_handle_index(request: web.Request):
        if request.path == "/app":
            response = web.Response(text=snapshot, content_type="text/html")
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-SentriX-Dashboard"] = "v55-frozen"
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
        "Dashboard V55 figé avant build_app : %s octets, sha256=%s. Les mutations tardives de INDEX_HTML ne seront plus servies sur /app.",
        len(snapshot.encode("utf-8")),
        digest,
    )
    return True


__all__ = ["install", "_snapshot_is_usable"]
