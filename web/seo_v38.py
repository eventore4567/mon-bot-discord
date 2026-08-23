"""SEO public V38 pour rendre SentriX découvrable depuis les moteurs de recherche.

Le dashboard privé reste noindex. Seules les pages publiques de présentation, robots.txt
et sitemap.xml sont exposées à l'indexation.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from aiohttp import web

_INSTALLED = False

_DESCRIPTION = (
    "SentriX est un bot Discord complet avec dashboard : modération, sécurité, AutoMod, "
    "tickets, IA, logs, niveaux, économie, notifications, automatisations et outils staff."
)

_ROOT_SEO = r'''
<meta name="description" content="SentriX est un bot Discord complet avec dashboard : modération, sécurité, AutoMod, tickets, IA, logs, niveaux, économie, notifications et outils staff.">
<meta name="keywords" content="SentriX, Sentrix bot, SentriX Discord, bot Discord, dashboard SentriX, bot modération Discord, bot tickets Discord, bot sécurité Discord">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
<meta name="googlebot" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
<link rel="canonical" href="/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — Bot Discord complet & Dashboard">
<meta property="og:description" content="Gérez votre serveur Discord avec SentriX : modération, sécurité, tickets, IA, logs, automatisations et dashboard complet.">
<meta property="og:url" content="/">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="SentriX — Bot Discord complet & Dashboard">
<meta name="twitter:description" content="Bot Discord complet avec dashboard, sécurité, tickets, IA, logs et outils staff.">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"SoftwareApplication","name":"SentriX","applicationCategory":"CommunicationApplication","operatingSystem":"Discord","description":"SentriX est un bot Discord complet avec dashboard pour la modération, la sécurité, les tickets, l'IA, les logs, les niveaux, l'économie, les notifications et les outils staff."}</script>
<style id="sentrix-seo-v38-css">.sx-seo-links{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px!important;font-size:12px!important}.sx-seo-links a{color:var(--brand2,#a897ff);text-decoration:underline;text-underline-offset:3px}</style>
'''

_ROOT_LINKS = '''<p class="sx-seo-links"><a href="/sentrix">Découvrir SentriX Bot Discord</a><a href="/dashboard-sentrix">Découvrir le Dashboard SentriX</a></p>'''


def _inject_root(source: str) -> str:
    if 'sentrix-seo-v38-css' in source:
        return source
    source = source.replace(
        '<title>SentriX — Dashboard</title>',
        '<title>SentriX — Bot Discord complet & Dashboard officiel</title>',
        1,
    )
    source = source.replace('</head>', _ROOT_SEO + '\n</head>', 1)
    marker = '<p id="authMessage" style="font-size:13px;margin-top:14px"></p>'
    if marker in source:
        source = source.replace(marker, marker + '\n        ' + _ROOT_LINKS, 1)
    return source


def _page(title: str, description: str, canonical: str, body_title: str, intro: str, sections: list[tuple[str, str]], invite_url: str | None) -> str:
    cards = ''.join(
        f'<article><h2>{html.escape(head)}</h2><p>{html.escape(text)}</p></article>'
        for head, text in sections
    )
    invite = html.escape(invite_url or '/login', quote=True)
    return f'''<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="{html.escape(canonical, quote=True)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="SentriX">
<meta property="og:title" content="{html.escape(title, quote=True)}"><meta property="og:description" content="{html.escape(description, quote=True)}"><meta property="og:url" content="{html.escape(canonical, quote=True)}">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebPage","name":"{html.escape(body_title)}","description":"{html.escape(description)}","isPartOf":{{"@type":"WebSite","name":"SentriX"}}}}</script>
<style>
:root{{--bg:#090b12;--panel:#111522;--line:#283047;--text:#f2f4ff;--muted:#9aa3b8;--brand:#7c6cff}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% -10%,#33266b55,transparent 35%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:inherit}}header{{max-width:1120px;margin:auto;padding:22px 22px 0;display:flex;justify-content:space-between;align-items:center;gap:16px}}.brand{{font-size:20px;font-weight:900;text-decoration:none}}nav{{display:flex;gap:8px;flex-wrap:wrap}}nav a,.btn{{border:1px solid var(--line);background:#171c2c;border-radius:10px;padding:9px 12px;text-decoration:none;font-weight:750}}main{{max-width:1120px;margin:auto;padding:70px 22px}}.hero{{max-width:830px}}.kicker{{color:#aa9cff;font-weight:850;text-transform:uppercase;letter-spacing:.08em;font-size:11px}}h1{{font-size:clamp(36px,7vw,68px);line-height:1.02;letter-spacing:-.04em;margin:12px 0 16px}}.lead{{font-size:18px;color:var(--muted);line-height:1.65}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}}.btn.primary{{background:linear-gradient(135deg,var(--brand),#5e4ee5);border-color:transparent}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:54px}}article{{border:1px solid var(--line);background:var(--panel);border-radius:14px;padding:20px}}article h2{{font-size:17px;margin:0 0 8px}}article p{{margin:0;color:var(--muted);line-height:1.6}}footer{{max-width:1120px;margin:auto;padding:0 22px 36px;color:var(--muted);font-size:12px}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}header{{align-items:flex-start;flex-direction:column}}main{{padding-top:48px}}}}
</style></head><body>
<header><a class="brand" href="/">SentriX</a><nav><a href="/sentrix">Bot Discord</a><a href="/dashboard-sentrix">Dashboard</a><a href="/login">Connexion</a></nav></header>
<main><section class="hero"><div class="kicker">SentriX officiel</div><h1>{html.escape(body_title)}</h1><p class="lead">{html.escape(intro)}</p><div class="actions"><a class="btn primary" href="{invite}" target="_blank" rel="noopener">Ajouter SentriX à Discord</a><a class="btn" href="/login">Ouvrir le dashboard</a></div></section><section class="grid">{cards}</section></main>
<footer>SentriX — bot Discord et dashboard de gestion de serveur.</footer>
</body></html>'''


async def sentrix_page(request: web.Request) -> web.Response:
    dashboard = request.app['dashboard_module']
    base = dashboard._public_url(request)
    return web.Response(
        text=_page(
            'SentriX Bot Discord — Modération, sécurité, tickets, IA et dashboard',
            _DESCRIPTION,
            f'{base}/sentrix',
            'SentriX, le bot Discord pensé pour gérer tout un serveur',
            'SentriX centralise les outils essentiels d’un serveur Discord dans un seul bot et un dashboard web : sécurité, support, automatisations, communauté et gestion du staff.',
            [
                ('Modération et sécurité', 'AutoMod, anti-spam, anti-liens, anti-raid, anti-nuke, sanctions, surveillance et outils de protection configurables.'),
                ('Tickets et support', 'Panels de tickets, formulaires, claim staff, transcripts, historique, évaluations et configuration depuis le dashboard.'),
                ('IA et automatisations', 'Assistant IA, FAQ du serveur et règles automatiques avec déclencheurs et actions configurables.'),
                ('Communauté', 'Niveaux, économie, mini-jeux, notifications sociales, événements, recrutements, rôles et panneaux personnalisés.'),
                ('Vocaux et rôles', 'Salons vocaux temporaires, Sticky Roles, vérification et gestion avancée des rôles.'),
                ('Dashboard web', 'Les administrateurs peuvent configurer SentriX sans mémoriser des commandes Discord.'),
            ],
            dashboard._invite_url(request.app['bot']),
        ),
        content_type='text/html',
        headers={'Cache-Control': 'public, max-age=300', 'X-Robots-Tag': 'index, follow'},
    )


async def dashboard_page(request: web.Request) -> web.Response:
    dashboard = request.app['dashboard_module']
    base = dashboard._public_url(request)
    return web.Response(
        text=_page(
            'Dashboard SentriX — Gérez votre serveur Discord depuis le web',
            'Le Dashboard SentriX permet de configurer le bot Discord SentriX : tickets, logs, sécurité, IA, rôles, niveaux, économie, automatisations, recrutements et plus.',
            f'{base}/dashboard-sentrix',
            'Dashboard SentriX : configurez votre bot Discord sans commandes compliquées',
            'Connectez-vous avec Discord, choisissez votre serveur puis pilotez les fonctions de SentriX depuis une interface web centralisée et protégée par les permissions administrateur.',
            [
                ('Centre des fonctionnalités', 'Activez ou désactivez les grands systèmes et accédez directement à leurs réglages.'),
                ('Tickets', 'Gérez les panels, types, tickets ouverts, claims, transcripts et statistiques de support.'),
                ('Sécurité', 'Configurez AutoMod, anti-nuke, sauvegardes, incidents et protections du serveur.'),
                ('Staff et opérations', 'Consultez sanctions, dossiers, surveillance, planning, candidatures et outils internes.'),
                ('Personnalisation', 'Réglez rôles, salons, messages, panels, embeds, notifications et design.'),
                ('Accès protégé', 'Les pages d’administration ne sont accessibles qu’aux personnes autorisées sur le serveur Discord.'),
            ],
            dashboard._invite_url(request.app['bot']),
        ),
        content_type='text/html',
        headers={'Cache-Control': 'public, max-age=300', 'X-Robots-Tag': 'index, follow'},
    )


async def robots(request: web.Request) -> web.Response:
    dashboard = request.app['dashboard_module']
    base = dashboard._public_url(request)
    text = f'''User-agent: *
Allow: /
Allow: /sentrix
Allow: /dashboard-sentrix
Disallow: /app
Disallow: /api/
Disallow: /login
Disallow: /logout
Disallow: /oauth/
Disallow: /setup-center
Disallow: /operations
Disallow: /feature-suite
Disallow: /community
Disallow: /engagement
Disallow: /enterprise
Disallow: /embed-builder
Disallow: /owner-servers
Sitemap: {base}/sitemap.xml
'''
    return web.Response(text=text, content_type='text/plain', headers={'Cache-Control': 'public, max-age=3600'})


async def sitemap(request: web.Request) -> web.Response:
    dashboard = request.app['dashboard_module']
    base = dashboard._public_url(request)
    today = datetime.now(timezone.utc).date().isoformat()
    urls = [('', '1.0'), ('/sentrix', '0.9'), ('/dashboard-sentrix', '0.9')]
    body = ''.join(
        f'<url><loc>{html.escape(base + path)}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>{priority}</priority></url>'
        for path, priority in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return web.Response(text=xml, content_type='application/xml', headers={'Cache-Control': 'public, max-age=3600'})


@web.middleware
async def indexing_headers(request: web.Request, handler):
    response = await handler(request)
    public_paths = {'/', '/sentrix', '/dashboard-sentrix', '/robots.txt', '/sitemap.xml'}
    if request.path in public_paths:
        if request.path not in {'/robots.txt', '/sitemap.xml'}:
            response.headers.setdefault('X-Robots-Tag', 'index, follow')
    else:
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    dashboard.INDEX_HTML = _inject_root(dashboard.INDEX_HTML)
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app['dashboard_module'] = dashboard
        app.middlewares.append(indexing_headers)
        app.router.add_get('/sentrix', sentrix_page)
        app.router.add_get('/dashboard-sentrix', dashboard_page)
        app.router.add_get('/robots.txt', robots)
        app.router.add_get('/sitemap.xml', sitemap)
        return app

    dashboard.build_app = build_app
