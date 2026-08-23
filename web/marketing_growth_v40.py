"""Pages publiques de croissance SentriX V40.

Ajoute les éléments utiles aux annuaires, au partage social et à l'onboarding sans exposer
les pages privées du dashboard : démarrage, statistiques, support, confidentialité,
conditions et media kit.
"""
from __future__ import annotations

import html
import os
from pathlib import Path

from aiohttp import web

_INSTALLED = False
_ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets" / "sentrix"
_MEDIA = {
    "moderation": "moderation.png",
    "security": "security.png",
    "tickets": "tickets.png",
    "ai": "ai.png",
    "configuration": "configuration.png",
    "events": "events.png",
}


def _base(request: web.Request) -> str:
    dashboard = request.app["dashboard_module"]
    return str(dashboard._public_url(request)).rstrip("/")


def _invite(request: web.Request) -> str:
    dashboard = request.app["dashboard_module"]
    return str(dashboard._invite_url(request.app["bot"]) or f"{_base(request)}/login")


def _support_url() -> str:
    value = os.getenv("SENTRIX_SUPPORT_URL", "").strip()
    return value if value.startswith(("https://", "http://")) else ""


def _layout(request: web.Request, *, title: str, description: str, heading: str, body: str) -> str:
    base = _base(request)
    canonical = f"{base}{request.path}"
    return f'''<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="{html.escape(canonical, quote=True)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="SentriX">
<meta property="og:title" content="{html.escape(title, quote=True)}">
<meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:url" content="{html.escape(canonical, quote=True)}">
<meta name="twitter:card" content="summary">
<style>
:root{{--bg:#080a11;--panel:#111522;--panel2:#151a2a;--line:#283047;--text:#f4f6ff;--muted:#a3acc2;--brand:#7667ff;--brand2:#a897ff;--ok:#62d99f}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% -10%,#37297366,transparent 34%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}}
a{{color:inherit}}header{{max-width:1120px;margin:auto;padding:20px 22px;display:flex;justify-content:space-between;align-items:center;gap:14px}}.brand{{display:flex;align-items:center;gap:10px;font-size:19px;font-weight:900;text-decoration:none}}.brand img{{width:34px;height:34px;border-radius:10px}}nav{{display:flex;gap:7px;flex-wrap:wrap}}nav a,.btn{{border:1px solid var(--line);background:#151a29;border-radius:10px;padding:9px 12px;text-decoration:none;font-weight:750}}main{{max-width:1120px;margin:auto;padding:58px 22px 78px}}.hero{{max-width:860px}}.eyebrow{{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--brand2);font-weight:850}}h1{{font-size:clamp(34px,6.5vw,62px);line-height:1.04;letter-spacing:-.04em;margin:11px 0 15px}}h2{{font-size:20px;margin:0 0 9px}}h3{{margin:0 0 7px}}p{{line-height:1.65}}.lead{{font-size:18px;color:var(--muted);max-width:800px}}.actions{{display:flex;gap:9px;flex-wrap:wrap;margin:24px 0 8px}}.btn.primary{{background:linear-gradient(135deg,var(--brand),#5647dd);border-color:transparent}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:36px}}.grid.two{{grid-template-columns:repeat(2,minmax(0,1fr))}}.card{{border:1px solid var(--line);background:linear-gradient(180deg,var(--panel2),var(--panel));border-radius:15px;padding:19px}}.muted{{color:var(--muted)}}.big{{font-size:32px;font-weight:950;letter-spacing:-.03em}}.status{{display:inline-flex;align-items:center;gap:7px;font-weight:800}}.dot{{width:8px;height:8px;border-radius:50%;background:var(--ok)}}.legal{{max-width:850px}}.legal h2{{margin-top:30px}}.legal li{{color:var(--muted);line-height:1.65;margin:5px 0}}.media-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:25px}}.media-grid img{{display:block;width:100%;border:1px solid var(--line);border-radius:14px;background:var(--panel)}}code{{background:#151a29;border:1px solid var(--line);padding:2px 6px;border-radius:6px}}footer{{max-width:1120px;margin:auto;padding:0 22px 34px;color:var(--muted);font-size:12px}}footer a{{margin-right:12px}}
@media(max-width:760px){{header{{align-items:flex-start;flex-direction:column}}main{{padding-top:38px}}.grid,.grid.two,.media-grid{{grid-template-columns:1fr}}}}
</style></head><body>
<header><a class="brand" href="/"><img src="/sentrix-avatar.png" alt=""><span>SentriX</span></a><nav><a href="/start">Commencer</a><a href="/stats">Stats</a><a href="/support">Support</a><a href="/dashboard-sentrix">Dashboard</a></nav></header>
<main><section class="hero"><div class="eyebrow">SentriX officiel</div><h1>{html.escape(heading)}</h1><p class="lead">{html.escape(description)}</p></section>{body}</main>
<footer><a href="/sentrix">Bot Discord</a><a href="/media-kit">Media kit</a><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a></footer>
</body></html>'''


async def start_page(request: web.Request) -> web.Response:
    invite = html.escape(_invite(request), quote=True)
    body = f'''
<div class="actions"><a class="btn primary" href="{invite}" target="_blank" rel="noopener">Ajouter SentriX à Discord</a><a class="btn" href="/login">Se connecter au dashboard</a></div>
<section class="grid">
<div class="card"><div class="big">1</div><h2>Ajoutez SentriX</h2><p class="muted">Choisissez votre serveur Discord et autorisez uniquement les permissions nécessaires à votre configuration.</p></div>
<div class="card"><div class="big">2</div><h2>Connectez-vous</h2><p class="muted">Ouvrez le dashboard avec Discord. Les droits du serveur sont revérifiés avant les actions d'administration.</p></div>
<div class="card"><div class="big">3</div><h2>Configurez</h2><p class="muted">Activez sécurité, tickets, logs, IA, niveaux, économie, automatisations et outils communautaires serveur par serveur.</p></div>
</section>'''
    return web.Response(text=_layout(request, title="Commencer avec SentriX — Bot Discord", description="Ajoutez SentriX à votre serveur Discord puis configurez sécurité, tickets, IA, logs et communauté depuis le dashboard.", heading="Installez SentriX en quelques minutes", body=body), content_type="text/html", headers={"Cache-Control":"public, max-age=300"})


async def public_growth(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    guilds = list(getattr(bot, "guilds", []) or [])
    members = sum(max(0, int(getattr(guild, "member_count", 0) or 0)) for guild in guilds)
    latency = getattr(bot, "latency", None)
    try:
        latency_ms = round(float(latency) * 1000) if latency is not None else None
    except (TypeError, ValueError):
        latency_ms = None
    return web.json_response({
        "bot_name": getattr(getattr(bot, "user", None), "name", None) or "SentriX",
        "online": bool(getattr(bot, "user", None)) and not bot.is_closed(),
        "guild_count": len(guilds),
        "member_count": members,
        "latency_ms": latency_ms,
        "invite_url": _invite(request),
    }, headers={"Cache-Control":"public, max-age=60"})


async def stats_page(request: web.Request) -> web.Response:
    body = '''
<section class="grid" id="stats"><div class="card"><div class="big" id="guilds">—</div><h2>Serveurs</h2></div><div class="card"><div class="big" id="members">—</div><h2>Membres accessibles</h2></div><div class="card"><div class="big" id="latency">—</div><h2>Latence Discord</h2></div></section>
<div class="actions"><span class="status"><span class="dot" id="dot"></span><span id="state">Chargement…</span></span><a class="btn primary" id="invite" href="/start">Ajouter SentriX</a></div>
<script>(()=>{const fmt=n=>new Intl.NumberFormat('fr-FR').format(n||0);async function load(){try{const r=await fetch('/api/public-growth',{cache:'no-store'});const d=await r.json();document.getElementById('guilds').textContent=fmt(d.guild_count);document.getElementById('members').textContent=fmt(d.member_count);document.getElementById('latency').textContent=d.latency_ms==null?'—':d.latency_ms+' ms';document.getElementById('state').textContent=d.online?'SentriX est en ligne':'SentriX redémarre';document.getElementById('dot').style.background=d.online?'var(--ok)':'#f0b35a';if(d.invite_url)document.getElementById('invite').href=d.invite_url;}catch(e){document.getElementById('state').textContent='Stats temporairement indisponibles';}}load();setInterval(load,60000);})();</script>'''
    return web.Response(text=_layout(request, title="Statistiques SentriX — Bot Discord", description="Consultez les statistiques publiques et l'état actuel du bot Discord SentriX.", heading="SentriX en chiffres", body=body), content_type="text/html", headers={"Cache-Control":"public, max-age=120"})


async def support_page(request: web.Request) -> web.Response:
    support = _support_url()
    support_button = f'<a class="btn primary" href="{html.escape(support, quote=True)}" target="_blank" rel="noopener">Rejoindre le serveur support</a>' if support else '<a class="btn primary" href="/login">Ouvrir le dashboard</a>'
    note = "Le serveur support officiel est disponible via le bouton ci-dessus." if support else "Le lien du serveur support public n’est pas encore configuré. Les administrateurs peuvent utiliser le dashboard en attendant."
    body = f'''<div class="actions">{support_button}<a class="btn" href="/start">Guide de démarrage</a></div><section class="grid two"><div class="card"><h2>Avant de signaler un problème</h2><p class="muted">Vérifiez les permissions du bot, le rôle de SentriX dans la hiérarchie Discord et les réglages du serveur dans le dashboard.</p></div><div class="card"><h2>Support</h2><p class="muted">{html.escape(note)}</p></div><div class="card"><h2>Sécurité</h2><p class="muted">Ne partagez jamais le token du bot, un secret OAuth, une clé API ou un mot de passe dans un ticket ou un message.</p></div><div class="card"><h2>Informations utiles</h2><p class="muted">Pour accélérer un diagnostic, indiquez le serveur concerné, la fonction utilisée, le résultat attendu et le message d’erreur exact sans publier de secret.</p></div></section>'''
    return web.Response(text=_layout(request, title="Support SentriX — Aide pour le bot Discord", description="Centre de support officiel de SentriX : démarrage, diagnostic et accès au support du bot Discord.", heading="Support SentriX", body=body), content_type="text/html")


async def privacy_page(request: web.Request) -> web.Response:
    body = '''<section class="legal"><h2>Données nécessaires au fonctionnement</h2><p class="muted">SentriX peut enregistrer des identifiants Discord de serveurs, utilisateurs, rôles, salons et messages lorsque cela est nécessaire aux fonctions activées. Selon les réglages d’un serveur, cela peut inclure configurations, sanctions, tickets et transcripts, niveaux, économie, logs techniques et données liées aux automatisations.</p><h2>Dashboard</h2><p class="muted">La connexion au dashboard utilise Discord OAuth afin d’identifier l’utilisateur, ses serveurs et ses permissions. Des données de session techniques peuvent être conservées pour maintenir la connexion et sécuriser les actions.</p><h2>Fonctions IA</h2><p class="muted">Lorsqu’une fonction IA est utilisée, le contenu nécessaire à la demande peut être transmis au fournisseur IA configuré afin de produire la réponse. Évitez d’envoyer des secrets ou données sensibles dans les prompts.</p><h2>Conservation</h2><p class="muted">La durée dépend du type de donnée et de la fonctionnalité. Certaines données opérationnelles disposent de règles de rétention, tandis que des configurations ou historiques nécessaires peuvent rester jusqu’à leur suppression ou celle du serveur concerné.</p><h2>Partage et vente</h2><p class="muted">SentriX n’a pas pour fonction de vendre les données des utilisateurs. Les données ne sont transmises à des services tiers que lorsque cela est nécessaire au fonctionnement d’une fonction activée ou à l’infrastructure du service.</p><h2>Suppression</h2><p class="muted">Un propriétaire ou administrateur de serveur peut demander la suppression de données associées à son serveur via le support officiel. Certaines informations peuvent être conservées lorsqu’elles sont nécessaires à la sécurité, à la prévention des abus ou à des obligations applicables.</p><h2>Sécurité</h2><p class="muted">Les secrets du bot et les clés API ne sont pas destinés à être stockés dans le dépôt public. Les accès d’administration du dashboard sont contrôlés avec les permissions Discord.</p></section>'''
    return web.Response(text=_layout(request, title="Politique de confidentialité SentriX", description="Politique de confidentialité du bot Discord et du dashboard SentriX.", heading="Politique de confidentialité", body=body), content_type="text/html")


async def terms_page(request: web.Request) -> web.Response:
    body = '''<section class="legal"><h2>Utilisation du service</h2><p class="muted">SentriX doit être utilisé conformément aux règles de Discord et aux lois applicables. L’utilisation pour contourner des restrictions, harceler, spammer, frauder ou nuire à d’autres utilisateurs n’est pas autorisée.</p><h2>Responsabilité des administrateurs</h2><p class="muted">Les propriétaires et administrateurs restent responsables de la configuration de leur serveur, des permissions accordées au bot et des décisions de modération prises avec ses outils.</p><h2>Disponibilité</h2><p class="muted">Le service est fourni sans garantie de disponibilité permanente. Des maintenances, limites Discord, incidents réseau ou mises à jour peuvent interrompre temporairement certaines fonctions.</p><h2>Fonctions automatisées</h2><p class="muted">Les protections et automatisations doivent être testées avant un déploiement important. Un administrateur doit vérifier que les rôles, salons, seuils et permissions correspondent à son serveur.</p><h2>Évolutions</h2><p class="muted">Les fonctions, limites et présentes conditions peuvent évoluer avec SentriX. La version publiée sur cette page constitue la version publique actuelle.</p></section>'''
    return web.Response(text=_layout(request, title="Conditions d’utilisation SentriX", description="Conditions d’utilisation du bot Discord et du dashboard SentriX.", heading="Conditions d’utilisation", body=body), content_type="text/html")


async def media_asset(request: web.Request) -> web.StreamResponse:
    key = request.match_info.get("name", "")
    filename = _MEDIA.get(key)
    if not filename:
        raise web.HTTPNotFound()
    path = _ASSET_ROOT / filename
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control":"public, max-age=86400"})


async def media_page(request: web.Request) -> web.Response:
    body = '''<section class="grid two"><div class="card"><h2>Nom officiel</h2><div class="big">SentriX</div><p class="muted">À écrire exactement ainsi. Signature : « Tout votre serveur Discord, au même endroit. »</p></div><div class="card"><h2>Description courte</h2><p class="muted">Bot Discord tout-en-un avec dashboard, modération, sécurité, tickets, IA, logs, niveaux, économie et automatisations.</p></div><div class="card"><h2>Identité</h2><p class="muted">La PP officielle est toujours disponible sur <code>/sentrix-avatar.png</code> et suit automatiquement l’avatar Discord actuel du bot.</p></div><div class="card"><h2>Liens publics</h2><p class="muted">Site, démarrage, dashboard, stats, support, confidentialité et conditions sont accessibles depuis ce domaine officiel.</p></div></section><section class="media-grid"><img src="/sentrix-media/moderation" alt="Présentation modération SentriX"><img src="/sentrix-media/security" alt="Présentation sécurité SentriX"><img src="/sentrix-media/tickets" alt="Présentation tickets SentriX"><img src="/sentrix-media/ai" alt="Présentation IA SentriX"></section>'''
    return web.Response(text=_layout(request, title="Media Kit SentriX — Logo, présentation et ressources", description="Media kit officiel de SentriX avec identité, description et visuels pour annuaires, vidéos et partenaires.", heading="Media kit officiel SentriX", body=body), content_type="text/html")


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get("/start", start_page)
        app.router.add_get("/stats", stats_page)
        app.router.add_get("/support", support_page)
        app.router.add_get("/privacy", privacy_page)
        app.router.add_get("/terms", terms_page)
        app.router.add_get("/media-kit", media_page)
        app.router.add_get("/api/public-growth", public_growth)
        app.router.add_get("/sentrix-media/{name}", media_asset)
        return app

    dashboard.build_app = build_app
