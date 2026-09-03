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
            pass
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
    if "sentrix-app-motion-v55" in source:
        return source
    return source.replace("</head>", _APP_POLISH + "\n</head>", 1)


def _public_home_html(request: web.Request, dashboard) -> str:
    bot = request.app.get("bot")
    base = str(dashboard._public_url(request)).rstrip("/")
    invite = dashboard._invite_url(bot) or "/login"
    invite = html.escape(str(invite), quote=True)
    canonical = html.escape(base + "/", quote=True)
    return f'''<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#080a11">
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
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;min-height:100vh;overflow-x:hidden;background:radial-gradient(circle at 20% -10%,#392b7a66,transparent 36%),radial-gradient(circle at 85% 28%,#1f3c7450,transparent 32%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:inherit}}body:before{{content:"";position:fixed;inset:-30%;pointer-events:none;z-index:-1;background:conic-gradient(from 150deg at 50% 50%,transparent,#7969ff10,transparent,#4076ff0c,transparent);animation:sxAmbient 18s linear infinite}}
header{{max-width:1100px;margin:auto;padding:20px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px;animation:sxDrop .45s cubic-bezier(.2,.8,.2,1) both}}.brand{{display:flex;align-items:center;gap:11px;text-decoration:none;font-size:20px;font-weight:900}}.brand img{{width:38px;height:38px;border-radius:11px;object-fit:cover;box-shadow:0 8px 25px #0005}}.small{{color:var(--muted);font-size:13px}}main{{max-width:1100px;margin:auto;padding:62px 22px 84px}}.hero{{text-align:center;max-width:800px;margin:auto;animation:sxRise .62s cubic-bezier(.2,.8,.2,1) .06s both}}.hero>img{{width:132px;height:132px;object-fit:cover;border-radius:28px;border:1px solid var(--line);box-shadow:0 28px 70px #0008;animation:sxFloat 5s ease-in-out infinite}}.eyebrow{{margin-top:22px;color:var(--brand2);font-size:11px;font-weight:900;letter-spacing:.1em;text-transform:uppercase}}h1{{font-size:clamp(38px,7vw,70px);line-height:1;letter-spacing:-.05em;margin:10px 0 16px}}.lead{{font-size:18px;line-height:1.65;color:var(--muted);margin:auto;max-width:720px}}.main-actions{{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:27px}}.btn{{position:relative;display:inline-flex;align-items:center;justify-content:center;gap:9px;border:1px solid var(--line);background:var(--panel2);border-radius:11px;padding:11px 15px;text-decoration:none;font-weight:800;transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease,background .18s ease}}.btn:hover{{transform:translateY(-2px);border-color:#514a81;box-shadow:0 12px 34px #0005}}.btn.primary{{background:linear-gradient(135deg,var(--brand),#5142d7);border-color:transparent;box-shadow:0 12px 30px #5e50e62c}}.hub-title{{margin:66px 0 15px;font-size:24px;letter-spacing:-.02em;animation:sxRise .5s ease .16s both}}.hub-notice{{margin:0 0 22px;padding:14px 18px;border:1px solid #5c3a3a;border-radius:12px;background:#241419;color:#ffd9d9;font-size:14px;animation:sxRise .4s ease both}}.hub-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.hub-card{{display:block;border:1px solid var(--line);background:linear-gradient(180deg,var(--panel2),#101420);border-radius:15px;padding:20px;text-decoration:none;opacity:0;animation:sxCard .5s cubic-bezier(.2,.8,.2,1) forwards;transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease,background .2s ease}}.hub-card:nth-child(1){{animation-delay:.18s}}.hub-card:nth-child(2){{animation-delay:.23s}}.hub-card:nth-child(3){{animation-delay:.28s}}.hub-card:nth-child(4){{animation-delay:.33s}}.hub-card:nth-child(5){{animation-delay:.38s}}.hub-card:nth-child(6){{animation-delay:.43s}}.hub-card:nth-child(7){{animation-delay:.48s}}.hub-card:nth-child(8){{animation-delay:.53s}}.hub-card:nth-child(9){{animation-delay:.58s}}.hub-card:hover{{transform:translateY(-5px) scale(1.008);border-color:#675cba;box-shadow:0 16px 42px #0005}}.hub-card strong{{display:block;font-size:17px;margin-bottom:7px}}.hub-card span{{display:block;color:var(--muted);line-height:1.55}}.hub-card.primary-card{{background:linear-gradient(145deg,#29205e,#151a29);border-color:#5c50ba}}footer{{max-width:1100px;margin:auto;padding:0 22px 36px;color:var(--muted);font-size:12px;text-align:center}}
.sx-loader{{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:rgba(5,7,13,.82);backdrop-filter:blur(12px);opacity:0;visibility:hidden;transition:opacity .2s ease,visibility .2s ease}}.sx-loader.show{{opacity:1;visibility:visible}}.sx-loader-card{{min-width:min(340px,calc(100vw - 36px));padding:28px 26px;text-align:center;border:1px solid #343a55;border-radius:18px;background:linear-gradient(180deg,#151a29,#0d111b);box-shadow:0 24px 80px #0009;transform:translateY(8px) scale(.98);transition:transform .22s ease}}.sx-loader.show .sx-loader-card{{transform:none}}.sx-spinner{{width:42px;height:42px;margin:0 auto 16px;border-radius:50%;border:3px solid #ffffff20;border-top-color:#8d80ff;border-right-color:#6c5dfd;animation:sxSpin .72s linear infinite}}.sx-loader b{{display:block;font-size:17px}}.sx-loader span{{display:block;margin-top:7px;color:var(--muted);font-size:12px}}.sx-loader-line{{height:3px;margin-top:18px;border-radius:999px;overflow:hidden;background:#ffffff0e}}.sx-loader-line:after{{content:"";display:block;width:42%;height:100%;background:linear-gradient(90deg,transparent,#8e80ff,transparent);animation:sxLoad 1s ease-in-out infinite}}
@keyframes sxDrop{{from{{opacity:0;transform:translateY(-8px)}}to{{opacity:1;transform:none}}}}@keyframes sxRise{{from{{opacity:0;transform:translateY(15px)}}to{{opacity:1;transform:none}}}}@keyframes sxCard{{from{{opacity:0;transform:translateY(14px) scale(.985)}}to{{opacity:1;transform:none}}}}@keyframes sxFloat{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-7px)}}}}@keyframes sxSpin{{to{{transform:rotate(360deg)}}}}@keyframes sxLoad{{from{{transform:translateX(-130%)}}to{{transform:translateX(330%)}}}}@keyframes sxAmbient{{to{{transform:rotate(360deg)}}}}
@media(max-width:760px){{header{{align-items:flex-start;flex-direction:column}}main{{padding-top:40px}}.hub-grid{{grid-template-columns:1fr}}.hero>img{{width:112px;height:112px}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}body:before,.hero>img,.hub-card,header,.hero,.hub-title,.sx-spinner,.sx-loader-line:after{{animation:none!important}}.hub-card{{opacity:1}}.btn,.hub-card,.sx-loader,.sx-loader-card{{transition:none!important}}}}
</style></head><body>
<header><a class="brand" href="/"><img src="/sentrix-avatar.png?v=55" alt="Logo SentriX" width="38" height="38"><span>SentriX</span></a><span class="small">Lien officiel unique</span></header>
<main>
<section class="hero"><img src="/sentrix-avatar.png?v=55" alt="PP officielle SentriX" width="132" height="132"><div class="eyebrow">Hub officiel SentriX</div><h1>Tout SentriX. Un seul lien.</h1><p class="lead">Ajoutez le bot, gérez votre serveur, consultez les fonctions, les statistiques, le support et les ressources depuis cette seule page.</p><div class="main-actions"><a class="btn primary" href="{invite}" target="_blank" rel="noopener">Ajouter SentriX</a><a class="btn" href="/login" data-dashboard-entry>Ouvrir le dashboard</a></div></section>
<h2 class="hub-title">Tout SentriX</h2>
<p id="sxAuthNotice" class="hub-notice" hidden></p>
<section class="hub-grid">
<a class="hub-card primary-card" href="{invite}" target="_blank" rel="noopener"><strong>Ajouter SentriX</strong><span>Installez le bot sur votre serveur Discord.</span></a>
<a class="hub-card primary-card" href="/login" data-dashboard-entry><strong>Dashboard</strong><span>Configurez et gérez votre serveur depuis le web.</span></a>
<a class="hub-card" href="/sentrix"><strong>Fonctions</strong><span>Découvrez la sécurité, les tickets, l’IA, les niveaux et le reste.</span></a>
<a class="hub-card" href="/start"><strong>Commencer</strong><span>Guide rapide pour installer et configurer SentriX.</span></a>
<a class="hub-card" href="/stats"><strong>Statistiques</strong><span>État du bot, serveurs, membres et latence.</span></a>
<a class="hub-card" href="/support"><strong>Support</strong><span>Aide, diagnostic et accès au support officiel.</span></a>
<a class="hub-card" href="/media-kit"><strong>Media kit</strong><span>Identité officielle et visuels de SentriX.</span></a>
<a class="hub-card" href="/privacy"><strong>Confidentialité</strong><span>Politique de confidentialité de SentriX.</span></a>
<a class="hub-card" href="/terms"><strong>Conditions</strong><span>Conditions d’utilisation du service.</span></a>
</section>
</main><footer>SentriX — bot Discord tout-en-un et dashboard officiel.</footer>
<div class="sx-loader" id="sxDashboardLoader" aria-hidden="true"><div class="sx-loader-card"><div class="sx-spinner"></div><b>Ouverture du dashboard</b><span id="sxDashboardLoaderText">Vérification de votre session Discord…</span><div class="sx-loader-line"></div></div></div>
<script>
(()=>{{
  "use strict";
  const overlay=document.getElementById("sxDashboardLoader");
  const text=document.getElementById("sxDashboardLoaderText");
  let opening=false;
  function hide(){{opening=false;overlay?.classList.remove("show");overlay?.setAttribute("aria-hidden","true");}}
  async function openDashboard(event){{
    if(opening)return;
    event.preventDefault();opening=true;
    overlay?.classList.add("show");overlay?.setAttribute("aria-hidden","false");
    if(text)text.textContent="Vérification de votre session Discord…";
    let target="/login";
    try{{
      const response=await fetch("/api/me",{{cache:"no-store",credentials:"same-origin"}});
      if(response.ok){{target="/app";if(text)text.textContent="Session trouvée. Chargement de votre serveur…";}}
      else if(text)text.textContent="Connexion Discord sécurisée…";
    }}catch(_){{if(text)text.textContent="Connexion Discord sécurisée…";}}
    window.setTimeout(()=>window.location.assign(target),260);
  }}
  document.querySelectorAll("[data-dashboard-entry]").forEach(link=>link.addEventListener("click",openDashboard));
  window.addEventListener("pageshow",hide);

  // handle_login redirige ici avec ?auth=missing quand DISCORD_CLIENT_SECRET
  // n'est pas configure sur Railway. Sans ce bloc, cliquer sur "Dashboard"
  // affichait le loader "Verification de votre session...", rechargeait
  // silencieusement CETTE MEME page une fois le redirect termine, et rien
  // n'indiquait pourquoi — exactement ce qui ressemblait a "le dashboard ne
  // s'ouvre pas".
  const params=new URLSearchParams(location.search);
  if(params.get("auth")==="missing"){{
    const notice=document.getElementById("sxAuthNotice");
    if(notice){{
      notice.textContent="Connexion Discord momentanement indisponible. Reessayez dans quelques instants ou contactez le support.";
      notice.hidden=false;
    }}
    history.replaceState(null,"",location.pathname);
  }}
}})();
</script>
</body></html>'''


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
                pass
        return response

    dashboard.handle_index = public_or_dashboard

    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.middlewares.append(brand_meta_middleware)
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
