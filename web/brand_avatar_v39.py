"""Identité publique SentriX et hub officiel.

La racine / sert de lien unique vers tout SentriX, tandis que /app conserve le dashboard
d'administration. La PP Discord actuelle reste l'image officielle du site, des previews
sociales et du favicon.
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
<title>SentriX — Hub officiel du bot Discord</title>
<meta name="description" content="Le lien officiel unique de SentriX : installation du bot, dashboard, fonctions, statistiques, support et ressources.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website"><meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — Tout au même endroit">
<meta property="og:description" content="Installez SentriX, ouvrez le dashboard, consultez les fonctions, les stats et le support depuis un seul lien.">
<meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary">
<style>
:root{{--bg:#080a11;--panel:#111522;--panel2:#151a29;--line:#283047;--text:#f4f6ff;--muted:#a6afc4;--brand:#6d5dfc;--brand2:#a99cff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 20% -10%,#392b7a66,transparent 36%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:inherit}}header{{max-width:1100px;margin:auto;padding:20px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px}}.brand{{display:flex;align-items:center;gap:11px;text-decoration:none;font-size:20px;font-weight:900}}.brand img{{width:38px;height:38px;border-radius:11px}}.small{{color:var(--muted);font-size:13px}}main{{max-width:1100px;margin:auto;padding:62px 22px 84px}}.hero{{text-align:center;max-width:800px;margin:auto}}.hero img{{width:132px;height:132px;border-radius:28px;border:1px solid var(--line);box-shadow:0 28px 70px #0008}}.eyebrow{{margin-top:22px;color:var(--brand2);font-size:11px;font-weight:900;letter-spacing:.1em;text-transform:uppercase}}h1{{font-size:clamp(38px,7vw,70px);line-height:1;letter-spacing:-.05em;margin:10px 0 16px}}.lead{{font-size:18px;line-height:1.65;color:var(--muted);margin:auto;max-width:720px}}.main-actions{{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:27px}}.btn{{border:1px solid var(--line);background:var(--panel2);border-radius:11px;padding:11px 15px;text-decoration:none;font-weight:800}}.btn.primary{{background:linear-gradient(135deg,var(--brand),#5142d7);border-color:transparent}}.hub-title{{margin:66px 0 15px;font-size:24px;letter-spacing:-.02em}}.hub-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.hub-card{{display:block;border:1px solid var(--line);background:linear-gradient(180deg,var(--panel2),#101420);border-radius:15px;padding:20px;text-decoration:none;transition:.16s ease}}.hub-card:hover{{transform:translateY(-2px);border-color:#5e55a8}}.hub-card strong{{display:block;font-size:17px;margin-bottom:7px}}.hub-card span{{display:block;color:var(--muted);line-height:1.55}}.hub-card.primary-card{{background:linear-gradient(145deg,#29205e,#151a29);border-color:#5c50ba}}footer{{max-width:1100px;margin:auto;padding:0 22px 36px;color:var(--muted);font-size:12px;text-align:center}}@media(max-width:760px){{header{{align-items:flex-start;flex-direction:column}}main{{padding-top:40px}}.hub-grid{{grid-template-columns:1fr}}}}
</style></head><body>
<header><a class="brand" href="/"><img src="/sentrix-avatar.png" alt="Logo SentriX"><span>SentriX</span></a><span class="small">Lien officiel unique</span></header>
<main>
<section class="hero"><img src="/sentrix-avatar.png" alt="PP officielle SentriX"><div class="eyebrow">Hub officiel SentriX</div><h1>Tout SentriX. Un seul lien.</h1><p class="lead">Ajoutez le bot, gérez votre serveur, consultez les fonctions, les statistiques, le support et les ressources depuis cette seule page.</p><div class="main-actions"><a class="btn primary" href="{invite}" target="_blank" rel="noopener">Ajouter SentriX</a><a class="btn" href="/app">Ouvrir le dashboard</a></div></section>
<h2 class="hub-title">Tout SentriX</h2>
<section class="hub-grid">
<a class="hub-card primary-card" href="{invite}" target="_blank" rel="noopener"><strong>Ajouter SentriX</strong><span>Installez le bot sur votre serveur Discord.</span></a>
<a class="hub-card primary-card" href="/app"><strong>Dashboard</strong><span>Configurez et gérez votre serveur depuis le web.</span></a>
<a class="hub-card" href="/sentrix"><strong>Fonctions</strong><span>Découvrez la sécurité, les tickets, l’IA, les niveaux et le reste.</span></a>
<a class="hub-card" href="/start"><strong>Commencer</strong><span>Guide rapide pour installer et configurer SentriX.</span></a>
<a class="hub-card" href="/stats"><strong>Statistiques</strong><span>État du bot, serveurs, membres et latence.</span></a>
<a class="hub-card" href="/support"><strong>Support</strong><span>Aide, diagnostic et accès au support officiel.</span></a>
<a class="hub-card" href="/media-kit"><strong>Media kit</strong><span>Identité officielle et visuels de SentriX.</span></a>
<a class="hub-card" href="/privacy"><strong>Confidentialité</strong><span>Politique de confidentialité de SentriX.</span></a>
<a class="hub-card" href="/terms"><strong>Conditions</strong><span>Conditions d’utilisation du service.</span></a>
</section>
</main><footer>SentriX — bot Discord tout-en-un et dashboard officiel.</footer>
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

    from . import growth_referrals_v43, marketing_growth_indexing_v40, marketing_growth_v40

    marketing_growth_v40.install(dashboard)
    marketing_growth_indexing_v40.install(dashboard)
    growth_referrals_v43.install(dashboard)
