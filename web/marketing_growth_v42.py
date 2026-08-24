"""Croissance organique SentriX V42.

Pages utiles et indexables autour des intentions de recherche principales : bot Discord,
modération, tickets, IA, sécurité et dashboard. Chaque page reste informative, possède
un CTA vers l'installation et renvoie vers les autres fonctions au lieu d'être une page
porte vide uniquement créée pour les moteurs de recherche.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientTimeout, web

from . import marketing_growth_v40

logger = logging.getLogger("bot.dashboard.marketing-growth-v42")
_INSTALLED = False

PAGES = {
    "/bot-discord": {
        "title": "SentriX — Bot Discord tout-en-un avec dashboard",
        "heading": "Un bot Discord pour gérer tout votre serveur",
        "description": "SentriX réunit modération, sécurité, tickets, IA, logs, niveaux, économie et automatisations dans un seul bot Discord avec dashboard web.",
        "cards": [
            ("Tout-en-un", "Réduisez le nombre de bots à maintenir en centralisant les fonctions essentielles dans SentriX."),
            ("Configuration web", "Activez et réglez les fonctions serveur par serveur depuis un dashboard dédié."),
            ("Pour membres et staff", "Commandes publiques, outils de modération, tickets, jeux, niveaux et outils d'organisation du staff."),
        ],
        "faq": [
            ("SentriX remplace-t-il plusieurs bots Discord ?", "SentriX centralise de nombreuses fonctions courantes : modération, tickets, sécurité, IA, logs, économie, niveaux, jeux et automatisations."),
            ("Faut-il connaître des commandes pour le configurer ?", "Non. Une grande partie de la configuration peut être effectuée depuis le dashboard web SentriX."),
        ],
    },
    "/bot-discord-moderation": {
        "title": "Bot de modération Discord — SentriX",
        "heading": "Modération Discord centralisée et configurable",
        "description": "Ban, kick, mute, warn, historique des sanctions, permissions staff et outils de modération réunis dans SentriX.",
        "cards": [
            ("Sanctions", "Ban, tempban, kick, mute, warn et historique avec permissions adaptées au staff."),
            ("Hiérarchie protégée", "SentriX vérifie les permissions et la position des rôles avant les actions sensibles."),
            ("Logs", "Les actions de modération peuvent être journalisées pour garder une trace exploitable par le staff."),
        ],
        "faq": [
            ("Qui peut utiliser les commandes de modération ?", "Les commandes sensibles sont contrôlées par les permissions Discord, les rôles configurés et la matrice d'accès SentriX."),
            ("Les sanctions sont-elles suivies ?", "Oui. SentriX dispose d'un historique de sanctions et d'outils de suivi depuis le bot et le dashboard."),
        ],
    },
    "/bot-discord-tickets": {
        "title": "Ticket Tool Discord et bot tickets avec dashboard — SentriX",
        "heading": "Un outil de tickets Discord complet avec dashboard",
        "description": "Vous cherchez un ticket tool Discord ? SentriX permet de créer panels, formulaires, claims, transcripts et suivis staff depuis Discord et un dashboard web.",
        "cards": [
            ("Panels de tickets", "Créez des points d'entrée clairs pour ouvrir un ticket selon le type de demande."),
            ("Gestion staff", "Claim, fermeture, notes et suivi des tickets avec règles d'accès adaptées."),
            ("Transcripts", "Conservez une trace des échanges lorsque le système de transcript est activé."),
        ],
        "faq": [
            ("SentriX peut-il servir de Ticket Tool Discord ?", "Oui. SentriX fournit un système de tickets avec panels, formulaires, claim staff, transcripts et configuration web dans le même bot."),
            ("Peut-on avoir plusieurs types de tickets ?", "Oui. SentriX prend en charge des types, formulaires et configurations de tickets différents."),
            ("Les tickets peuvent-ils être gérés depuis le dashboard ?", "Oui. SentriX possède un centre de tickets web en complément des interactions Discord."),
        ],
    },
    "/bot-discord-ia": {
        "title": "Bot IA Discord — SentriX AI",
        "heading": "Une IA directement dans votre serveur Discord",
        "description": "SentriX propose des fonctions IA pour discuter, expliquer, résumer, réécrire, traduire et générer des images selon la configuration du serveur.",
        "cards": [
            ("Assistant", "Posez une question à SentriX et utilisez l'IA directement depuis Discord."),
            ("Outils texte", "Résumé, explication, correction, amélioration, traduction et réécriture."),
            ("Images", "Générez des visuels depuis Discord lorsque la fonction image est activée."),
        ],
        "faq": [
            ("L'IA peut-elle être désactivée ?", "Oui. Les administrateurs peuvent contrôler l'activation des fonctions IA pour leur serveur."),
            ("SentriX limite-t-il les abus IA ?", "Oui. Des limites de débit, de concurrence et des contrôles serveur protègent les ressources IA."),
        ],
    },
    "/bot-discord-securite": {
        "title": "Bot sécurité Discord — Anti-raid, AutoMod et Anti-Nuke | SentriX",
        "heading": "Protégez votre serveur Discord avec SentriX",
        "description": "AutoMod, anti-spam, anti-liens, anti-invitations, anti-raid, anti-scam et anti-nuke configurables depuis SentriX.",
        "cards": [
            ("AutoMod", "Filtres configurables contre spam, liens, invitations, mentions excessives, caps et autres comportements indésirables."),
            ("Anti-raid", "Détection et protections prévues pour limiter les arrivées ou actions anormales."),
            ("Anti-Nuke", "Contrôles supplémentaires pour les opérations serveur sensibles et outils de récupération associés."),
        ],
        "faq": [
            ("La sécurité est-elle configurable ?", "Oui. Les protections SentriX sont activables et configurables serveur par serveur."),
            ("SentriX remplace-t-il les permissions Discord ?", "Non. Il complète les permissions Discord et vérifie les droits avant les actions sensibles."),
        ],
    },
    "/bot-discord-dashboard": {
        "title": "Dashboard bot Discord — Gérez SentriX depuis le web",
        "heading": "Configurez votre bot Discord depuis un vrai dashboard",
        "description": "Le dashboard SentriX centralise la configuration, les tickets, les fonctions communautaires, les logs et les réglages de sécurité de vos serveurs autorisés.",
        "cards": [
            ("Connexion Discord", "Connectez-vous avec Discord et ne voyez que les serveurs que vous êtes autorisé à administrer."),
            ("Configuration centrale", "Retrouvez les réglages principaux au même endroit au lieu de mémoriser des dizaines de commandes."),
            ("Accès contrôlé", "Les permissions sont revérifiées avant les opérations d'administration importantes."),
        ],
        "faq": [
            ("Le dashboard est-il public ?", "La vitrine SentriX est publique, mais les fonctions d'administration nécessitent une connexion Discord et les permissions appropriées."),
            ("Peut-on gérer plusieurs serveurs ?", "Oui, lorsque votre compte Discord possède les permissions nécessaires sur chacun de ces serveurs."),
        ],
    },
}


def _cards_html(cards: list[tuple[str, str]]) -> str:
    return "".join(
        f'<article class="card"><h2>{html.escape(title)}</h2><p class="muted">{html.escape(text)}</p></article>'
        for title, text in cards
    )


def _faq_html(faq: list[tuple[str, str]]) -> str:
    return "".join(
        f'<article class="card"><h2>{html.escape(question)}</h2><p class="muted">{html.escape(answer)}</p></article>'
        for question, answer in faq
    )


def _structured_data(request: web.Request, page: dict) -> str:
    base = marketing_growth_v40._base(request)
    faq_entities = [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
        for q, a in page["faq"]
    ]
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SoftwareApplication",
                "name": "SentriX",
                "applicationCategory": "CommunicationApplication",
                "operatingSystem": "Discord",
                "url": base + request.path,
                "description": page["description"],
            },
            {"@type": "FAQPage", "mainEntity": faq_entities},
        ],
    }
    return '<script type="application/ld+json">' + json.dumps(graph, ensure_ascii=False).replace("</", "<\\/") + "</script>"


async def landing_page(request: web.Request) -> web.Response:
    page = PAGES.get(request.path)
    if page is None:
        raise web.HTTPNotFound()
    invite = html.escape(marketing_growth_v40._invite(request), quote=True)
    related = "".join(
        f'<a class="btn" href="{path}">{html.escape(other["heading"].split(" avec ")[0][:32])}</a>'
        for path, other in PAGES.items() if path != request.path
    )
    body = f'''
<div class="actions"><a class="btn primary" href="{invite}" target="_blank" rel="noopener">Ajouter SentriX</a><a class="btn" href="/app">Ouvrir le dashboard</a></div>
<section class="grid">{_cards_html(page["cards"])}</section>
<h2 style="margin-top:44px">Questions fréquentes</h2><section class="grid two">{_faq_html(page["faq"])}</section>
<h2 style="margin-top:44px">Découvrir SentriX</h2><div class="actions">{related}</div>
'''
    source = marketing_growth_v40._layout(
        request,
        title=page["title"],
        description=page["description"],
        heading=page["heading"],
        body=body,
    )
    source = source.replace("</head>", _structured_data(request, page) + "</head>", 1)
    return web.Response(
        text=source,
        content_type="text/html",
        headers={"Cache-Control": "public, max-age=300", "X-Robots-Tag": "index, follow"},
    )


@web.middleware
async def indexing_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path in PAGES:
        response.headers["X-Robots-Tag"] = "index, follow"
    if isinstance(response, web.Response) and request.path == "/robots.txt":
        text = response.text or ""
        if "Allow: /bot-discord\n" not in text:
            allows = "".join(f"Allow: {path}\n" for path in sorted(PAGES))
            marker = "Disallow: /app\n"
            response.text = text.replace(marker, allows + marker, 1) if marker in text else text + "\n" + allows
    elif isinstance(response, web.Response) and request.path == "/sitemap.xml":
        text = response.text or ""
        dashboard = request.app.get("dashboard_module")
        if dashboard is not None:
            base = str(dashboard._public_url(request)).rstrip("/")
            if base + "/bot-discord" not in text:
                today = datetime.now(timezone.utc).date().isoformat()
                entries = "".join(
                    f"<url><loc>{html.escape(base + path)}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.90</priority></url>"
                    for path in sorted(PAGES)
                )
                response.text = text.replace("</urlset>", entries + "</urlset>", 1)
    return response


async def _submit_indexnow(dashboard) -> None:
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
            "urlList": [base + path for path in sorted(PAGES)],
        }
        async with ClientSession(timeout=ClientTimeout(total=12)) as client:
            async with client.post(endpoint, json=payload) as response:
                if response.status in {200, 202}:
                    logger.info("IndexNow a accepté les pages SEO V42 (%s).", response.status)
                else:
                    logger.warning("IndexNow a refusé les pages SEO V42 (%s).", response.status)
    except Exception:
        logger.exception("Soumission IndexNow V42 impossible.")


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.middlewares.insert(0, indexing_middleware)
        for path in PAGES:
            app.router.add_get(path, landing_page)

        async def submit_pages(_app):
            await _submit_indexnow(dashboard)

        app.on_startup.append(submit_pages)
        return app

    dashboard.build_app = build_app
