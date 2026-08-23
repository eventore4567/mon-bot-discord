"""Indexation et découverte des pages publiques SentriX V40."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientTimeout, web

_INSTALLED = False
logger = logging.getLogger("bot.dashboard.marketing-growth-indexing-v40")
_PUBLIC_PAGES = {
    "/start",
    "/stats",
    "/support",
    "/privacy",
    "/terms",
    "/media-kit",
}
_PRIORITIES = {
    "/start": "0.95",
    "/stats": "0.75",
    "/support": "0.75",
    "/privacy": "0.55",
    "/terms": "0.50",
    "/media-kit": "0.80",
}


def _patch_robots(text: str) -> str:
    if "Allow: /start" in text:
        return text
    additions = "".join(f"Allow: {path}\n" for path in sorted(_PUBLIC_PAGES))
    marker = "Disallow: /app\n"
    if marker in text:
        return text.replace(marker, additions + marker, 1)
    return text + "\n" + additions


def _patch_sitemap(text: str, base: str) -> str:
    if f"{base}/start" in text:
        return text
    today = datetime.now(timezone.utc).date().isoformat()
    entries = "".join(
        f"<url><loc>{html.escape(base + path)}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>{_PRIORITIES[path]}</priority></url>"
        for path in sorted(_PUBLIC_PAGES)
    )
    return text.replace("</urlset>", entries + "</urlset>", 1)


@web.middleware
async def public_growth_indexing(request: web.Request, handler):
    response = await handler(request)
    path = request.path

    # Ce middleware est inséré en première position. Il s'exécute donc en dernier lors du
    # retour de réponse et peut corriger le noindex volontaire appliqué aux pages privées.
    if path in _PUBLIC_PAGES or path.startswith("/sentrix-media/"):
        response.headers["X-Robots-Tag"] = "index, follow"

    # Ne lire response.text que pour les deux réponses textuelles que nous devons modifier.
    # Cela évite de tenter de décoder la PP ou un autre fichier binaire en UTF-8.
    if isinstance(response, web.Response) and path == "/robots.txt":
        response.text = _patch_robots(response.text or "")
    elif isinstance(response, web.Response) and path == "/sitemap.xml":
        dashboard = request.app.get("dashboard_module")
        if dashboard is not None:
            base = str(dashboard._public_url(request)).rstrip("/")
            response.text = _patch_sitemap(response.text or "", base)
    return response


async def _submit_indexnow(dashboard) -> None:
    """Signale les nouvelles pages V40 au réseau IndexNow au démarrage."""
    try:
        from . import seo_v38

        base = str(getattr(getattr(dashboard, "config", None), "DASHBOARD_PUBLIC_URL", "") or "").strip().rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return
        key = str(getattr(seo_v38, "_INDEXNOW_KEY", "") or "")
        key_path = str(getattr(seo_v38, "_INDEXNOW_PATH", "") or "")
        endpoint = str(getattr(seo_v38, "_INDEXNOW_ENDPOINT", "https://api.indexnow.org/indexnow"))
        if not key or not key_path:
            return
        payload = {
            "host": parsed.netloc,
            "key": key,
            "keyLocation": base + key_path,
            "urlList": [base + path for path in sorted(_PUBLIC_PAGES)],
        }
        async with ClientSession(timeout=ClientTimeout(total=12)) as client:
            async with client.post(endpoint, json=payload) as response:
                if response.status in {200, 202}:
                    logger.info("IndexNow a accepté les pages publiques V40 (%s).", response.status)
                else:
                    logger.warning("IndexNow a refusé les pages V40 (%s).", response.status)
    except Exception:
        logger.exception("Soumission IndexNow V40 impossible.")


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.middlewares.insert(0, public_growth_indexing)

        async def submit_growth_pages(_app):
            await _submit_indexnow(dashboard)

        app.on_startup.append(submit_growth_pages)
        return app

    dashboard.build_app = build_app
