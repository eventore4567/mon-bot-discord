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
    "/commands",
}
_PRIORITIES = {
    "/start": "0.95",
    "/stats": "0.75",
    "/support": "0.75",
    "/privacy": "0.55",
    "/terms": "0.50",
    "/media-kit": "0.80",
    "/commands": "0.95",
}


def _patch_robots(text: str) -> str:
    if "Allow: /start" in text and "Allow: /commands" in text:
        return text
    additions = "".join(f"Allow: {path}\n" for path in sorted(_PUBLIC_PAGES))
    marker = "Disallow: /app\n"
    if marker in text:
        return text.replace(marker, additions + marker, 1)
    return text + "\n" + additions


def _patch_sitemap(text: str, base: str) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    missing = [path for path in sorted(_PUBLIC_PAGES) if f"{base}{path}" not in text]
    if not missing:
        return text
    entries = "".join(
        f"<url><loc>{html.escape(base + path)}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>{_PRIORITIES[path]}</priority></url>"
        for path in missing
    )
    return text.replace("</urlset>", entries + "</urlset>", 1)


@web.middleware
async def public_growth_indexing(request: web.Request, handler):
    response = await handler(request)
    path = request.path

    if path in _PUBLIC_PAGES or path.startswith("/sentrix-media/"):
        response.headers["X-Robots-Tag"] = "index, follow"

    if isinstance(response, web.Response) and path == "/robots.txt":
        response.text = _patch_robots(response.text or "")
    elif isinstance(response, web.Response) and path == "/sitemap.xml":
        dashboard = request.app.get("dashboard_module")
        if dashboard is not None:
            base = str(dashboard._public_url(request)).rstrip("/")
            response.text = _patch_sitemap(response.text or "", base)
    return response


async def _submit_indexnow(dashboard) -> None:
    """Signale les pages publiques au réseau IndexNow au démarrage."""
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
                    logger.info("IndexNow a accepté les pages publiques SentriX (%s).", response.status)
                else:
                    logger.warning("IndexNow a refusé les pages publiques SentriX (%s).", response.status)
    except Exception:
        logger.exception("Soumission IndexNow SentriX impossible.")


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

    from . import bot_directory_stats_v44, marketing_growth_v42, public_commands_v46

    marketing_growth_v42.install(dashboard)
    public_commands_v46.install(dashboard)
    bot_directory_stats_v44.install(dashboard)
