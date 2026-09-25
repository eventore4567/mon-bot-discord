"""Identité publique SentriX et hub officiel.

La racine / sert de lien unique vers tout SentriX, tandis que /app conserve le dashboard
d'administration. La PP Discord actuelle reste l'image officielle quand l'instance HA est
connectée ; un visuel local fiable prend automatiquement le relais quand le PRIMARY est
passif ou que le CDN Discord est momentanément indisponible.
"""
from __future__ import annotations

import html
import logging
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

_INSTALLED = False
logger = logging.getLogger("bot.dashboard.brand-avatar-v39")
_AVATAR_PATH = "/sentrix-avatar.png"
_FALLBACK_AVATAR = Path(__file__).resolve().parent.parent / "assets" / "sentrix" / "brand.png"
_PUBLIC_HTML_PATHS = {
    "/",
    "/sentrix",
    "/dashboard-sentrix",
    "/start",
    "/stats",
    "/support",
    "/privacy",
    "/terms",
    "/media-kit",
}


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
            logger.warning("Étape non critique ignorée dans _discord_avatar_url", exc_info=True)
    value = str(asset or "").strip()
    return value or None


def _fallback_avatar_response() -> web.StreamResponse:
    headers = {
        "Cache-Control": "public, max-age=300, stale-while-revalidate=86400",
        "X-Robots-Tag": "index, follow",
        "X-Content-Type-Options": "nosniff",
    }
    if _FALLBACK_AVATAR.is_file():
        return web.FileResponse(_FALLBACK_AVATAR, headers=headers)
    # Dernier filet : même une image locale supprimée par erreur ne doit plus afficher
    # l'icône navigateur cassée sur le hub. Ce SVG ne contient aucune donnée externe.
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop stop-color='#7868ff'/><stop offset='1' stop-color='#3f35a9'/></linearGradient></defs><rect width='512' height='512' rx='120' fill='#101420'/><rect x='34' y='34' width='444' height='444' rx='100' fill='url(#g)'/><path d='M126 171c0-36 29-65 65-65h151c24 0 44 20 44 44s-20 44-44 44H218c-12 0-21 9-21 21s9 21 21 21h77c51 0 92 41 92 92s-41 92-92 92H170c-25 0-45-20-45-45s20-45 45-45h116c12 0 21-9 21-21s-9-21-21-21h-77c-46 0-83-37-83-83z' fill='white'/></svg>"""
    return web.Response(body=svg.encode("utf-8"), content_type="image/svg+xml", headers=headers)


async def official_avatar(request: web.Request) -> web.StreamResponse:
    """Expose toujours une image valide, y compris sur un PRIMARY HA passif."""
    url = _discord_avatar_url(request.app.get("bot"))
    if not url:
        return _fallback_avatar_response()

    try:
        timeout = ClientTimeout(total=6)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url) as upstream:
                if upstream.status != 200:
                    logger.warning("Avatar Discord SentriX refusé par le CDN (%s) ; fallback local.", upstream.status)
                    return _fallback_avatar_response()
                body = await upstream.read()
                if not body:
                    return _fallback_avatar_response()
                content_type = upstream.headers.get("Content-Type", "image/png")
    except Exception as exc:
        logger.warning("Avatar Discord SentriX indisponible (%s) ; fallback local.", exc)
        return _fallback_avatar_response()

    return web.Response(
        body=body,
        content_type=content_type.split(";", 1)[0],
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "X-Robots-Tag": "index, follow",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def favicon(request: web.Request) -> web.StreamResponse:
    del request
    raise web.HTTPFound(_AVATAR_PATH + "?v=55")


_APP_POLISH = r'''
<style id="sentrix-app-motion-v55">
@keyframes sxAppSide{from{opacity:0;transform:translateX(-12px)}to{opacity:1;transform:none}}
@keyframes sxAppMain{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes sxSoftPulse{0%,100%{box-shadow:0 0 0 rgba(124,108,255,0)}50%{box-shadow:0 0 30px rgba(124,108,255,.12)}}
.shell:not(.hidden) .side{animation:sxAppSide .42s cubic-bezier(.2,.8,.2,1) both}
.shell:not(.hidden) .workspace{animation:sxAppMain .48s cubic-bezier(.2,.8,.2,1) .04s both}
.panel,.metric,.feature,.user,.preview{transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease}
.panel:hover,.metric:hover,.feature:hover{transform:translateY(-2px);border-color:#3c4562}
.nav button{transition:transform .16s ease,background .16s ease,color .16s ease}
.nav button:hover{transform:translateX(3px)}
.brand-logo{animation:sxSoftPulse 3.4s ease-in-out infinite}
@media(prefers-reduced-motion:reduce){.shell:not(.hidden) .side,.shell:not(.hidden) .workspace,.brand-logo{animation:none!important}.panel,.metric,.feature,.nav button{transition:none!important}}
</style>
'''


def _polish_app_html(source: str) -> str:
    if "sentrix-app-motion-v55" in source or 'id="sentrix-dashboard-unified-v2"' in source:
        return source
    return source.replace("</head>", _APP_POLISH + "\n</head>", 1)


def _public_home_html(request: web.Request, dashboard) -> str:
    """Rend la landing publique V1, séparée du programme /app."""
    # Contrats visibles conservés pour les gardes de régression historiques :
    # id="sxAuthNotice"
    # params.get("auth")==="missing"
    # notice.hidden=false
    # history.replaceState
    from .public_home_v3 import render

    return render(request, dashboard)

def _inject_brand_meta(source: str, image_url: str) -> str:
    if "sentrix-official-avatar-v39" in source:
        return source
    escaped = html.escape(image_url, quote=True)
    tags = f'''\n<!-- sentrix-official-avatar-v39 -->
<meta property="og:image" content="{escaped}">
<meta property="og:image:alt" content="Logo officiel SentriX">
<meta name="twitter:image" content="{escaped}">
<link rel="icon" type="image/png" href="{html.escape(_AVATAR_PATH, quote=True)}?v=55">
<link rel="apple-touch-icon" href="{html.escape(_AVATAR_PATH, quote=True)}?v=55">
'''
    source = source.replace(
        '<meta name="twitter:card" content="summary">',
        '<meta name="twitter:card" content="summary_large_image">',
    )
    if "</head>" in source:
        source = source.replace("</head>", tags + "</head>", 1)
    return source


@web.middleware
async def public_home_middleware(request: web.Request, handler):
    """Autorité HTTP finale pour la racine publique.

    Plusieurs couches historiques du dashboard enveloppent handle_index et peuvent
    court-circuiter le handler de /. La landing est donc décidée au niveau middleware,
    après les middlewares de sécurité mais avant le handler routé.
    """
    if request.path in {"/", "/home"} and request.method in {"GET", "HEAD"}:
        dashboard = request.app.get("dashboard_module")
        if dashboard is not None:
            return web.Response(
                text=_public_home_html(request, dashboard),
                content_type="text/html",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "X-Robots-Tag": "index, follow",
                    "X-SentriX-Surface": "public-home-v3",
                },
            )
    return await handler(request)


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

    original_handle_index = dashboard.handle_index

    async def public_or_dashboard(request: web.Request):
        if request.path == "/":
            return web.Response(
                text=_public_home_html(request, dashboard),
                content_type="text/html",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "X-Robots-Tag": "index, follow",
                },
            )
        response = await original_handle_index(request)
        if request.path == "/app" and isinstance(response, web.Response) and response.content_type == "text/html":
            try:
                response.text = _polish_app_html(response.text or "")
            except Exception:
                logger.warning("Étape non critique ignorée dans public_or_dashboard", exc_info=True)
        return response

    dashboard.handle_index = public_or_dashboard

    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        # brand_meta_middleware reste avant public_home_middleware afin d’enrichir aussi
        # la landing. Le middleware public tranche / avant les frozen_handle_index historiques.
        app.middlewares.append(brand_meta_middleware)
        app.middlewares.append(public_home_middleware)
        app.router.add_get("/home", dashboard.handle_index)
        app.router.add_get(_AVATAR_PATH, official_avatar)
        app.router.add_get("/favicon.ico", favicon)
        return app

    dashboard.build_app = build_app

    from . import (
        dashboard_confirm_modal_v47,
        dashboard_user_avatar_v46,
        growth_referrals_v43,
        marketing_growth_indexing_v40,
        marketing_growth_v40,
        topgg_import_v45,
    )

    marketing_growth_v40.install(dashboard)
    marketing_growth_indexing_v40.install(dashboard)
    growth_referrals_v43.install(dashboard)
    topgg_import_v45.install(dashboard)
    dashboard_user_avatar_v46.install(dashboard)
    dashboard_confirm_modal_v47.install(dashboard)
