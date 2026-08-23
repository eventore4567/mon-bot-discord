"""Identité visuelle publique SentriX V39.

Utilise l'avatar Discord courant du bot comme image officielle du site, des previews
Open Graph/Twitter et du favicon. Ainsi l'identité publique reste synchronisée avec la
PP Discord sans dupliquer un fichier image dans plusieurs endroits.
"""
from __future__ import annotations

import html
import logging

from aiohttp import ClientSession, ClientTimeout, web

_INSTALLED = False
logger = logging.getLogger("bot.dashboard.brand-avatar-v39")
_AVATAR_PATH = "/sentrix-avatar.png"
_PUBLIC_HTML_PATHS = {"/", "/sentrix", "/dashboard-sentrix"}


def _discord_avatar_url(bot) -> str | None:
    user = getattr(bot, "user", None)
    if user is None:
        return None
    asset = getattr(user, "display_avatar", None) or getattr(user, "avatar", None)
    if asset is None:
        return None
    try:
        asset = asset.replace(size=512, format="png")
    except Exception:
        try:
            asset = asset.with_size(512).with_format("png")
        except Exception:
            pass
    value = str(asset or "").strip()
    return value or None


async def official_avatar(request: web.Request) -> web.Response:
    """Expose la PP Discord actuelle de SentriX sous une URL stable du site officiel."""
    url = _discord_avatar_url(request.app.get("bot"))
    if not url:
        raise web.HTTPNotFound(text="Avatar SentriX indisponible")

    try:
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url) as upstream:
                if upstream.status != 200:
                    raise web.HTTPBadGateway(text="Avatar SentriX temporairement indisponible")
                body = await upstream.read()
                content_type = upstream.headers.get("Content-Type", "image/png")
    except web.HTTPException:
        raise
    except Exception as exc:
        logger.warning("Impossible de récupérer l'avatar Discord SentriX: %s", exc)
        raise web.HTTPBadGateway(text="Avatar SentriX temporairement indisponible") from exc

    return web.Response(
        body=body,
        content_type=content_type.split(";", 1)[0],
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "X-Robots-Tag": "index, follow",
        },
    )


async def favicon(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound(_AVATAR_PATH)


def _inject_brand_meta(source: str, image_url: str) -> str:
    if "sentrix-official-avatar-v39" in source:
        return source
    escaped = html.escape(image_url, quote=True)
    tags = f'''\n<!-- sentrix-official-avatar-v39 -->
<meta property="og:image" content="{escaped}">
<meta property="og:image:alt" content="Logo officiel SentriX">
<meta name="twitter:image" content="{escaped}">
<link rel="icon" type="image/png" href="{html.escape(_AVATAR_PATH, quote=True)}">
<link rel="apple-touch-icon" href="{html.escape(_AVATAR_PATH, quote=True)}">
'''
    source = source.replace(
        '<meta name="twitter:card" content="summary">',
        '<meta name="twitter:card" content="summary_large_image">',
    )
    if "</head>" in source:
        source = source.replace("</head>", tags + "</head>", 1)
    return source


@web.middleware
async def brand_meta_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path not in _PUBLIC_HTML_PATHS:
        return response
    if not isinstance(response, web.Response) or response.content_type != "text/html":
        return response
    try:
        source = response.text
    except Exception:
        return response
    if not source:
        return response

    dashboard = request.app.get("dashboard_module")
    if dashboard is None:
        return response
    base = str(dashboard._public_url(request)).rstrip("/")
    response.text = _inject_brand_meta(source, base + _AVATAR_PATH)
    return response


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.middlewares.append(brand_meta_middleware)
        app.router.add_get(_AVATAR_PATH, official_avatar)
        app.router.add_get("/favicon.ico", favicon)
        return app

    dashboard.build_app = build_app
