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

from . import sentrix_fx_v1 as fx

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
    """Coquille commune aux pages /start, /stats, /privacy, /terms et /media-kit.

    Ces cinq pages partageaient un fond en dégradé CSS pendant que la landing
    recevait un canvas animé : deux identités visuelles pour un même site.
    Elles passent ici sur ``web.sentrix_fx_v1``, le même moteur que les pages
    d'erreur — un seul canvas, une seule palette, une seule boucle.

    Les noms de classes (``card``, ``grid``, ``legal``, ``media-grid``,
    ``big``, ``status``…) sont conservés à l'identique : les corps de page les
    utilisent et les réécrire aurait cassé cinq pages pour un gain nul.
    """
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
{fx.styles()}
<style>
header{{max-width:1160px;margin:auto;padding:22px 24px;display:flex;justify-content:space-between;align-items:center;gap:14px}}
.brand{{display:flex;align-items:center;gap:11px;font-size:19px;font-weight:900;text-decoration:none;letter-spacing:-.02em}}
.brand img{{width:34px;height:34px;border-radius:11px;box-shadow:0 0 0 1px var(--ligne),0 8px 26px rgba(77,163,255,.22)}}
nav{{display:flex;gap:7px;flex-wrap:wrap}}
nav a,.btn{{border:1px solid var(--ligne);border-radius:11px;padding:10px 14px;text-decoration:none;font-weight:750;font-size:14.5px;
 background:linear-gradient(170deg,rgba(32,45,70,.66),rgba(15,23,39,.66));
 transition:transform .2s cubic-bezier(.2,.7,.3,1),border-color .2s,box-shadow .2s}}
nav a:hover,.btn:hover{{transform:translateY(-2px);border-color:rgba(140,203,255,.44);box-shadow:0 14px 34px rgba(2,6,16,.48),0 0 24px rgba(77,163,255,.14)}}
.btn.primary{{background:linear-gradient(135deg,#2f7fd4,var(--bleu),var(--bleu2));color:#04101d;border-color:transparent;font-weight:850}}
main{{max-width:1160px;margin:auto;padding:62px 24px 86px}}
.hero{{max-width:880px}}
.eyebrow{{display:inline-flex;align-items:center;gap:8px;font-size:11px;text-transform:uppercase;letter-spacing:.11em;color:var(--bleu2);font-weight:850;
 border:1px solid var(--ligne);border-radius:999px;padding:7px 13px;background:rgba(14,22,38,.62)}}
h1{{font-size:clamp(36px,6.6vw,66px);line-height:1.03;letter-spacing:-.045em;margin:16px 0 16px;
 background:linear-gradient(168deg,#fff 12%,var(--bleu2) 58%,var(--bleu));-webkit-background-clip:text;background-clip:text;color:transparent;
 filter:drop-shadow(0 14px 38px rgba(77,163,255,.20))}}
h2{{font-size:21px;margin:0 0 10px;letter-spacing:-.02em}}h3{{margin:0 0 8px}}
p{{line-height:1.68}}
.lead{{font-size:18px;color:var(--doux);max-width:820px}}
.actions{{display:flex;gap:10px;flex-wrap:wrap;margin:28px 0 8px}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:40px}}
.grid.two{{grid-template-columns:repeat(2,minmax(0,1fr))}}
.card{{position:relative;border:1px solid var(--ligne);border-radius:18px;padding:21px;overflow:hidden;
 background:linear-gradient(165deg,rgba(28,39,62,.72),rgba(13,20,34,.68));
 box-shadow:0 22px 58px rgba(2,6,16,.42),inset 0 1px 0 rgba(160,200,255,.08);
 backdrop-filter:blur(13px) saturate(118%);-webkit-backdrop-filter:blur(13px) saturate(118%);
 transform-style:preserve-3d;transition:border-color .2s ease,box-shadow .2s ease}}
.card::before{{content:"";position:absolute;inset:-42% -28%;pointer-events:none;
 background:linear-gradient(112deg,transparent 40%,rgba(140,203,255,.09) 50%,transparent 61%);
 transform:translateX(-78%) rotate(8deg);transition:transform .9s cubic-bezier(.2,.7,.3,1)}}
.card:hover::before{{transform:translateX(78%) rotate(8deg)}}
.card:hover{{border-color:rgba(140,203,255,.40);box-shadow:0 26px 66px rgba(2,6,16,.54),0 0 30px rgba(77,163,255,.10)}}
.muted{{color:var(--doux)}}
.big{{font-size:34px;font-weight:950;letter-spacing:-.035em;
 background:linear-gradient(168deg,#fff,var(--bleu2));-webkit-background-clip:text;background-clip:text;color:transparent}}
.status{{display:inline-flex;align-items:center;gap:8px;font-weight:800}}
.dot{{width:9px;height:9px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px rgba(85,214,154,.15)}}
.legal{{max-width:870px;border:1px solid var(--ligne);border-radius:20px;padding:30px 36px 36px;background:linear-gradient(168deg,rgba(26,36,58,.70),rgba(12,18,32,.66));box-shadow:0 26px 70px rgba(2,6,16,.44),inset 0 1px 0 rgba(160,200,255,.07)}}.legal h2{{margin-top:32px;padding-top:26px;border-top:1px solid var(--ligne);display:flex;align-items:center;gap:11px;font-size:19px}}.legal h2::before{{content:"";flex:none;width:3px;height:17px;border-radius:2px;background:linear-gradient(180deg,#8ccbff,#7b6cff)}}.legal h2:first-of-type{{margin-top:2px;padding-top:0;border-top:0}}.legal p{{color:var(--doux);line-height:1.72}}.legal li{{color:var(--doux);line-height:1.68;margin:6px 0}}
.media-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:28px}}
.media-grid img{{display:block;width:100%;border:1px solid var(--ligne);border-radius:16px;background:rgba(14,22,38,.6);
 transition:transform .2s cubic-bezier(.2,.7,.3,1),border-color .2s,box-shadow .2s}}
.media-grid img:hover{{transform:translateY(-3px);border-color:rgba(140,203,255,.40);box-shadow:0 22px 52px rgba(2,6,16,.5)}}
code{{background:rgba(10,17,30,.82);border:1px solid var(--ligne);padding:3px 7px;border-radius:7px;color:var(--bleu2);font:13.5px ui-monospace,SFMono-Regular,Menlo,monospace}}
footer{{max-width:1160px;margin:auto;padding:0 24px 38px;color:var(--doux);font-size:12.5px}}
footer a{{margin-right:14px;text-decoration:none}}footer a:hover{{color:var(--bleu2)}}
.hero .eyebrow{{animation:sxMonte .7s cubic-bezier(.16,.84,.31,1) both}}
.hero h1{{animation:sxMonte .8s .06s cubic-bezier(.16,.84,.31,1) both}}
.hero .lead{{animation:sxMonte .8s .13s cubic-bezier(.16,.84,.31,1) both}}
.hero .actions{{animation:sxMonte .8s .2s cubic-bezier(.16,.84,.31,1) both}}
.grid .card,.media-grid img{{animation:sxMonte .72s cubic-bezier(.16,.84,.31,1) both}}
.grid .card:nth-child(2){{animation-delay:.07s}}.grid .card:nth-child(3){{animation-delay:.14s}}
.grid .card:nth-child(4){{animation-delay:.21s}}.grid .card:nth-child(5){{animation-delay:.28s}}
.grid .card:nth-child(6){{animation-delay:.35s}}
.public-pointer{{display:none}}
@media(max-width:1024px){{header,main,footer{{padding-inline:20px}}}}
@media(max-width:760px){{header{{align-items:flex-start;flex-direction:column}}main{{padding-top:40px}}
 .grid,.grid.two,.media-grid{{grid-template-columns:1fr}}
 nav{{width:100%;overflow-x:auto;padding-bottom:3px}}nav a{{white-space:nowrap}}}}
@media(max-width:430px){{header{{padding:16px 15px}}main{{padding:36px 15px 68px}}.legal{{padding:22px 19px 26px;border-radius:16px}}
 h1{{font-size:clamp(32px,11vw,46px)}}.lead{{font-size:16px}}.card{{padding:17px}}
 .actions .btn{{width:100%;text-align:center}}footer{{padding-inline:15px}}}}
@media(max-width:360px){{header,main,footer{{padding-inline:12px}}.brand{{font-size:17px}}}}
@media(pointer:coarse){{.card,.media-grid img{{will-change:auto}}}}
@media(prefers-reduced-motion:reduce){{
 .hero .eyebrow,.hero h1,.hero .lead,.hero .actions,.grid .card,.media-grid img{{animation:none!important}}
 .card,.media-grid img,nav a,.btn{{transition:none!important;transform:none!important}}
 .card::before{{display:none}}}}
</style></head><body>{fx.fond()}
<div class="sx-shell">
<header><a class="brand" href="/"><img src="/sentrix-avatar.png" alt="" width="34" height="34"><span>SentriX</span></a><nav><a href="/start">Commencer</a><a href="/docs">Documentation</a><a href="/stats">Stats</a><a href="/support">Support</a><a href="/app">Dashboard</a></nav></header>
<main><section class="hero"><div class="eyebrow">SentriX officiel</div><h1>{html.escape(heading)}</h1><p class="lead">{html.escape(description)}</p></section>{body}</main>
<footer><a href="/sentrix">Bot Discord</a><a href="/docs">Documentation</a><a href="/media-kit">Media kit</a><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a></footer>
</div>
{fx.script()}
<script>(()=>{{"use strict";
// Inclinaison 3D des cartes au survol. Elle existait deja et reste ici : le
// fond anime donne la profondeur de la page, ceci donne celle des elements.
// L'ancien element publicPointer a disparu : il etait display:none dans les
// trois media queries, donc jamais visible. C'etait de la decoration morte.
if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;
const items=Array.from(document.querySelectorAll(".card,.media-grid img")),etats=new WeakMap();
function etat(el){{let s=etats.get(el);if(!s){{s={{rx:0,ry:0,crx:0,cry:0,raf:0}};etats.set(el,s);}}return s;}}
function frame(el){{const s=etat(el),k=.15;
 s.rx+=(s.crx-s.rx)*k;s.ry+=(s.cry-s.ry)*k;
 el.style.transform="perspective(900px) rotateX("+s.rx.toFixed(2)+"deg) rotateY("+s.ry.toFixed(2)+"deg) translateY(-2px)";
 if(Math.abs(s.crx-s.rx)+Math.abs(s.cry-s.ry)>.04){{s.raf=requestAnimationFrame(()=>frame(el));}}
 else{{s.raf=0;if(!s.crx&&!s.cry)el.style.transform="";}}}}
function viser(el,e,f){{f=f||1;const r=el.getBoundingClientRect(),
 x=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))-.5,
 y=Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))-.5,s=etat(el);
 s.crx=-y*4.4*f;s.cry=x*4.4*f;if(!s.raf)s.raf=requestAnimationFrame(()=>frame(el));}}
function relacher(el){{const s=etat(el);s.crx=0;s.cry=0;if(!s.raf)s.raf=requestAnimationFrame(()=>frame(el));}}
items.forEach(el=>{{
 el.addEventListener("pointermove",e=>{{if(e.pointerType!=="touch")viser(el,e);}});
 el.addEventListener("pointerleave",()=>relacher(el));
 el.addEventListener("pointerdown",e=>{{if(e.pointerType==="touch"){{viser(el,e,.7);setTimeout(()=>relacher(el),200);}}}});
}});
}})();</script>
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


async def short_panel(request: web.Request) -> web.Response:
    raise web.HTTPFound("/app")


async def docs_page(request: web.Request) -> web.Response:
    from .public_docs_v1 import render as render_docs

    dashboard = request.app["dashboard_module"]
    return web.Response(
        text=render_docs(request, dashboard),
        content_type="text/html",
        headers={
            "Cache-Control": "public, max-age=180",
            "X-SentriX-Surface": "docs-v1",
        },
    )


async def short_docs(request: web.Request) -> web.Response:
    raise web.HTTPFound("/commands")


async def short_support(request: web.Request) -> web.Response:
    raise web.HTTPFound("/support")


async def short_add(request: web.Request) -> web.Response:
    raise web.HTTPFound(_invite(request))


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
    from .public_support_v2 import render as render_support

    dashboard = request.app["dashboard_module"]
    return web.Response(
        text=render_support(request, dashboard, _support_url()),
        content_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-SentriX-Surface": "support-v2",
        },
    )


async def privacy_page(request: web.Request) -> web.Response:
    body = '''<section class="legal"><h2>Données nécessaires au fonctionnement</h2><p class="muted">SentriX peut enregistrer des identifiants Discord de serveurs, utilisateurs, rôles, salons et messages lorsque cela est nécessaire aux fonctions activées. Selon les réglages d’un serveur, cela peut inclure configurations, sanctions, tickets et transcripts, niveaux, économie, logs techniques et données liées aux automatisations.</p><h2>Dashboard</h2><p class="muted">La connexion au dashboard utilise Discord OAuth afin d’identifier l’utilisateur, ses serveurs et ses permissions. Des données de session techniques peuvent être conservées pour maintenir la connexion et sécuriser les actions.</p><h2>Fonctions IA</h2><p class="muted">Lorsqu’une fonction IA est utilisée, le contenu nécessaire à la demande peut être transmis au fournisseur IA configuré afin de produire la réponse. Évitez d’envoyer des secrets ou données sensibles dans les prompts.</p><h2>Conservation</h2><p class="muted">La durée dépend du type de donnée et de la fonctionnalité. Certaines données opérationnelles disposent de règles de rétention, tandis que des configurations ou historiques nécessaires peuvent rester jusqu’à leur suppression ou celle du serveur concerné.</p><h2>Partage et vente</h2><p class="muted">SentriX n’a pas pour fonction de vendre les données des utilisateurs. Les données ne sont transmises à des services tiers que lorsque cela est nécessaire au fonctionnement d’une fonction activée ou à l’infrastructure du service.</p><h2>Suppression</h2><p class="muted">Un propriétaire ou administrateur de serveur peut demander la suppression de données associées à son serveur via le support officiel. Certaines informations peuvent être conservées lorsqu’elles sont nécessaires à la sécurité, à la prévention des abus ou à des obligations applicables.</p><h2>Où les données sont stockées</h2><p class="muted">SentriX est hébergé sur Railway. Les données de configuration et d’historique sont conservées dans une base PostgreSQL gérée ; les sessions du dashboard et la coordination entre les deux instances passent par Redis. Des sauvegardes de la base sont réalisées vers un espace de stockage dédié au projet. Aucune de ces données n’est hébergée dans le dépôt de code.</p><h2>Haute disponibilité</h2><p class="muted">Deux instances du service tournent en parallèle et une seule traite les commandes à un instant donné. Les deux accèdent aux mêmes données : un basculement ne crée pas de copie supplémentaire.</p><h2>Sécurité</h2><p class="muted">Les secrets du bot et les clés API ne sont pas destinés à être stockés dans le dépôt public. Les accès d’administration du dashboard sont contrôlés avec les permissions Discord.</p><h2>Nous contacter</h2><p class="muted">Pour une question sur vos données ou une demande de suppression, passez par le serveur de support officiel, accessible depuis la page <a href="/support">Support</a>.</p></section>'''
    return web.Response(text=_layout(request, title="Politique de confidentialité SentriX", description="Politique de confidentialité du bot Discord et du dashboard SentriX.", heading="Politique de confidentialité", body=body), content_type="text/html")


async def terms_page(request: web.Request) -> web.Response:
    body = '''<section class="legal"><h2>Utilisation du service</h2><p class="muted">SentriX doit être utilisé conformément aux règles de Discord et aux lois applicables. L’utilisation pour contourner des restrictions, harceler, spammer, frauder ou nuire à d’autres utilisateurs n’est pas autorisée.</p><h2>Responsabilité des administrateurs</h2><p class="muted">Les propriétaires et administrateurs restent responsables de la configuration de leur serveur, des permissions accordées au bot et des décisions de modération prises avec ses outils.</p><h2>Disponibilité</h2><p class="muted">Le service est fourni sans garantie de disponibilité permanente. Des maintenances, limites Discord, incidents réseau ou mises à jour peuvent interrompre temporairement certaines fonctions.</p><h2>Fonctions automatisées</h2><p class="muted">Les protections et automatisations doivent être testées avant un déploiement important. Un administrateur doit vérifier que les rôles, salons, seuils et permissions correspondent à son serveur.</p><h2>Limitation d’usage</h2><p class="muted">Certaines commandes appliquent un délai entre deux utilisations, et les récompenses de jeux sont plafonnées par jour et par serveur. Ces limites protègent le service et l’équilibre des serveurs ; les contourner volontairement, par automatisation ou par comptes multiples, n’est pas autorisé.</p><h2>Suspension</h2><p class="muted">L’accès peut être restreint pour un utilisateur ou un serveur en cas d’abus manifeste, d’usage contraire aux règles de Discord ou de tentative de nuire au service ou à ses autres utilisateurs.</p><h2>Évolutions</h2><p class="muted">Les fonctions, limites et présentes conditions peuvent évoluer avec SentriX. La version publiée sur cette page constitue la version publique actuelle.</p><h2>Contact et support</h2><p class="muted">Les questions, signalements et demandes passent par le serveur de support officiel, accessible depuis la page <a href="/support">Support</a>.</p></section>'''
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
        app.router.add_get("/docs", docs_page)
        app.router.add_get("/support", support_page)
        app.router.add_get("/p", short_panel)
        app.router.add_get("/d", short_docs)
        app.router.add_get("/s", short_support)
        app.router.add_get("/add", short_add)
        app.router.add_get("/privacy", privacy_page)
        app.router.add_get("/terms", terms_page)
        app.router.add_get("/media-kit", media_page)
        app.router.add_get("/api/public-growth", public_growth)
        app.router.add_get("/sentrix-media/{name}", media_asset)
        return app

    dashboard.build_app = build_app
