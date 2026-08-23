"""Identité publique SentriX et séparation site/dashboard.

La racine / sert maintenant une vraie page vitrine publique, tandis que /app conserve
le dashboard d'administration. La PP Discord actuelle reste l'image officielle du site,
des previews sociales et du favicon.
"""
from __future__ import annotations

import html
import logging

from aiohttp import ClientSession, ClientTimeout, web

_INSTALLED = False
logger = logging.getLogger("bot.dashboard.brand-avatar-v39")
_AVATAR_PATH = "/sentrix-avatar.png"
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


def _public_home_html(request: web.Request, dashboard) -> str:
    bot = request.app.get("bot")
    base = str(dashboard._public_url(request)).rstrip("/")
    invite = dashboard._invite_url(bot) or "/login"
    invite = html.escape(str(invite), quote=True)
    canonical = html.escape(base + "/", quote=True)
    return f'''<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentriX — Bot Discord tout-en-un & Dashboard officiel</title>
<meta name="description" content="SentriX est un bot Discord tout-en-un avec dashboard : modération, sécurité, tickets, IA, logs, niveaux, économie et automatisations.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website"><meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — Bot Discord tout-en-un">
<meta property="og:description" content="Gérez votre serveur Discord avec SentriX : sécurité, tickets, IA, logs, automatisations et dashboard web.">
<meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary">
<style>
:root{{--bg:#080a11;--panel:#111522;--line:#283047;--text:#f4f6ff;--muted:#a6afc4;--brand:#6d5dfc;--brand2:#a99cff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 20% -10%,#392b7a66,transparent 36%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:inherit}}header{{max-width:1160px;margin:auto;padding:20px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px}}.brand{{display:flex;align-items:center;gap:11px;text-decoration:none;font-size:20px;font-weight:900}}.brand img{{width:38px;height:38px;border-radius:11px}}nav{{display:flex;gap:8px;flex-wrap:wrap}}nav a,.btn{{border:1px solid var(--line);background:#151a29;border-radius:10px;padding:10px 13px;text-decoration:none;font-weight:760}}main{{max-width:1160px;margin:auto;padding:72px 22px 84px}}.hero{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr);gap:40px;align-items:center}}.eyebrow{{color:var(--brand2);font-size:11px;font-weight:900;letter-spacing:.1em;text-transform:uppercase}}h1{{font-size:clamp(42px,7vw,78px);line-height:.98;letter-spacing:-.05em;margin:12px 0 19px;max-width:820px}}.lead{{font-size:19px;line-height:1.65;color:var(--muted);max-width:760px}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:27px}}.btn.primary{{background:linear-gradient(135deg,var(--brand),#5142d7);border-color:transparent}}.logo-panel{{display:flex;justify-content:center}}.logo-panel img{{width:min(300px,72vw);aspect-ratio:1;object-fit:cover;border-radius:30px;border:1px solid var(--line);box-shadow:0 35px 90px #0008}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:70px}}.card{{border:1px solid var(--line);background:linear-gradient(180deg,#151a29,#101420);border-radius:15px;padding:20px}}.card h2{{font-size:17px;margin:0 0 8px}}.card p{{margin:0;color:var(--muted);line-height:1.6}}.strip{{margin-top:22px;border:1px solid var(--line);background:#101420;border-radius:15px;padding:18px 20px;display:flex;justify-content:space-between;gap:18px;align-items:center;flex-wrap:wrap}}footer{{max-width:1160px;margin:auto;padding:0 22px 36px;color:var(--muted);font-size:12px}}footer a{{margin-right:14px}}@media(max-width:850px){{.hero{{grid-template-columns:1fr}}.logo-panel{{order:-1;justify-content:flex-start}}.logo-panel img{{width:150px;border-radius:22px}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{header{{align-items:flex-start;flex-direction:column}}main{{padding-top:45px}}.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<header><a class="brand" href="/"><img src="/sentrix-avatar.png" alt="Logo SentriX"><span>SentriX</span></a><nav><a href="/sentrix">Fonctions</a><a href="/stats">Stats</a><a href="/support">Support</a><a href="/app">Dashboard</a></nav></header>
<main>
<section class="hero"><div><div class="eyebrow">Bot Discord officiel</div><h1>Tout votre serveur Discord. Un seul bot.</h1><p class="lead">SentriX centralise la modération, la sécurité, les tickets, l’IA, les logs, les niveaux, l’économie, les automatisations et les outils staff dans un dashboard web complet.</p><div class="actions"><a class="btn primary" href="{invite}" target="_blank" rel="noopener">Ajouter SentriX</a><a class="btn" href="/app">Ouvrir le dashboard</a><a class="btn" href="/start">Voir le démarrage</a></div></div><div class="logo-panel"><img src="/sentrix-avatar.png" alt="PP officielle SentriX"></div></section>
<section class="grid"><article class="card"><h2>Sécurité</h2><p>AutoMod, anti-spam, anti-raid, anti-nuke et protections configurables.</p></article><article class="card"><h2>Tickets</h2><p>Panels, formulaires, claims, transcripts et suivi depuis le dashboard.</p></article><article class="card"><h2>IA & automatisations</h2><p>Assistant IA, FAQ, notifications et règles automatiques sans code.</p></article><article class="card"><h2>Communauté</h2><p>Niveaux, économie, jeux, événements, recrutements, rôles et vocaux temporaires.</p></article></section>
<section class="strip"><div><strong>Vous administrez déjà un serveur avec SentriX ?</strong><div style="color:var(--muted);margin-top:5px">Le dashboard privé reste séparé du site officiel.</div></div><a class="btn primary" href="/app">Accéder au dashboard</a></section>
</main><footer><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a><a href="/media-kit">Media kit</a><a href="/support">Support</a></footer>
</body></html>'''


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

    # / et /app utilisaient historiquement le même handler. On garde exactement le handler
    # stable du dashboard pour /app, mais on sert une vraie vitrine distincte sur la racine.
    original_handle_index = dashboard.handle_index

    async def public_or_dashboard(request: web.Request):
        if request.path == "/":
            return web.Response(
                text=_public_home_html(request, dashboard),
                content_type="text/html",
                headers={"Cache-Control": "public, max-age=180", "X-Robots-Tag": "index, follow"},
            )
        return await original_handle_index(request)

    dashboard.handle_index = public_or_dashboard

    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.middlewares.append(brand_meta_middleware)
        app.router.add_get(_AVATAR_PATH, official_avatar)
        app.router.add_get("/favicon.ico", favicon)
        return app

    dashboard.build_app = build_app

    # Pages publiques de croissance et leur indexation.
    from . import marketing_growth_indexing_v40, marketing_growth_v40

    marketing_growth_v40.install(dashboard)
    marketing_growth_indexing_v40.install(dashboard)
