"""Catalogue Premium SentriX — page d'information non transactionnelle.

Isolation intentionnelle :
- aucune modification des fonctions gratuites ou des permissions existantes ;
- aucune intégration Stripe, PayPal, Discord SKU ou checkout ;
- pas de jeton, PII, webhook, cookie ou secret dans cette page ;
- publication publique en lecture seule, désindexée jusqu'au lancement.
"""
from __future__ import annotations

from aiohttp import web

_INSTALLED = False

PAGE_HTML = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b0d10">
<meta name="description" content="Découvrez les offres SentriX en préparation. Les fonctionnalités gratuites restent gratuites.">
<title>SentriX — Offres Premium</title>
<style>
:root {
  color-scheme:dark;
  --bg:#0b0d10; --panel:#15191f; --panel-2:#1a1f27; --line:#2a313c;
  --text:#f2f5f8; --muted:#929dac; --faint:#8291a3;
  --accent:#77bcff; --accent-soft:#4da3ff; --mint:#55d69a;
  --radius:18px;
}
* { box-sizing:border-box }
html { scroll-behavior:smooth; background:var(--bg) }
body {
  margin:0; min-width:320px; color:var(--text);
  font:15px/1.6 system-ui,-apple-system,"Segoe UI",Inter,sans-serif;
  background:radial-gradient(ellipse 800px 350px at 80% -180px,#234c7035,transparent 75%),var(--bg);
  -webkit-font-smoothing:antialiased;
}
a { color:inherit; text-decoration:none }
a:focus-visible {outline:2px solid var(--accent); outline-offset:4px}
button {font:inherit}
.wrap {max-width:1160px; padding:0 28px; margin:0 auto}
.topbar {border-bottom:1px solid #ffffff12; background:#0b0d10eb}
.top-inner {height:76px;display:flex;justify-content:space-between;align-items:center;gap:20px}
.brand {display:flex;align-items:center;gap:12px;font-size:17px;font-weight:790;letter-spacing:-.025em}
.mark {display:grid;place-items:center;width:36px;height:36px;border-radius:11px;
  background:linear-gradient(145deg,#4da3ff,#28679f);color:white;font-size:19px;box-shadow:0 8px 28px #4da3ff28}
.brand small {display:block;font-weight:530;color:var(--muted);font-size:10px;letter-spacing:.14em;text-transform:uppercase;line-height:1.5}
.back {color:#d0d7eb;border:1px solid var(--line);padding:9px 14px;border-radius:10px;font-size:13px;font-weight:660;background:#141828}
.back:hover {border-color:#3c6684;background:#1a1e30}
.hero {padding:76px 0 43px; max-width:780px}
.overline {font-size:11px;letter-spacing:.145em;font-weight:800;text-transform:uppercase;color:#83c3ff;margin:0 0 17px}
.hero h1 {font-weight:790;letter-spacing:-.05em;font-size:clamp(34px,5.1vw,58px);line-height:1.11;margin:0;max-width:740px}
.hero h1 span {color:#77bcff}
.hero p {font-size:16px;color:var(--muted);max-width:650px;line-height:1.75;margin:22px 0 0}
.announcement {margin:0 0 30px;border:1px solid #345776;background:#152536;display:flex;gap:11px;align-items:flex-start;padding:14px 17px;border-radius:12px}
.announcement strong{white-space:nowrap;color:#b8e0ff;font-size:13px}
.announcement span{color:#c5c8d8;font-size:13px;line-height:1.55}
.plans {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:stretch}
.plan {position:relative;border:1px solid var(--line);border-radius:var(--radius);padding:25px 24px 23px;background:linear-gradient(155deg,#17202a,#11161e);display:flex;flex-direction:column;min-width:0}
.plan.featured {border-color:#4a8abb;background:linear-gradient(165deg,#1a2b3b,#121921 57%);box-shadow:0 10px 35px #194b6929}
.plan-top {display:flex;justify-content:space-between;align-items:center;gap:10px}
.plan-name {font-size:16px;font-weight:800;letter-spacing:-.018em}
.plan-state {font-size:10px;font-weight:760;letter-spacing:.06em;text-transform:uppercase;border:1px solid #345f80;border-radius:6px;color:#b9dcf8;padding:3px 7px}
.plan-state.active{border-color:#356a5e;color:#8ce5c5}
.plan-sub {color:var(--muted);margin:13px 0 21px;min-height:45px;font-size:13px;line-height:1.65}
.price {display:flex;align-items:baseline;gap:5px;margin:0 0 6px}
.price strong {font-size:40px;line-height:1.05;letter-spacing:-.06em}
.price span {font-size:14px;color:#ced4e1;font-weight:640}
.per {font-size:12px;color:var(--faint);min-height:18px}
.line {height:1px;background:var(--line);margin:21px 0 19px}
.plan h3 {font-size:12px;color:#cfd5e8;letter-spacing:.04em;text-transform:uppercase;margin:0 0 12px}
.plan ul {padding:0;list-style:none;margin:0 0 27px;display:grid;gap:12px;flex:1}
.plan li {display:grid;grid-template-columns:14px minmax(0,1fr);gap:10px;align-items:start;font-size:13px;color:#d6dbe9;line-height:1.45}
.plan li::before {content:"✓";font-weight:850;color:var(--mint);font-size:13px}
.plan.featured li::before{color:#8fccff}
.cta,.unavailable {min-height:43px;width:100%;display:flex;align-items:center;justify-content:center;padding:10px 14px;border-radius:11px;text-align:center;font-size:13px;font-weight:770}
.cta {background:#2a78b8;color:#fff;border:1px solid #61b2f2}
.cta:hover{background:#3b8dcc}
.unavailable {border:1px solid #343a52;background:#1e2234;color:#a4b3c4;cursor:default}
.meta {font-size:11px;color:#8791a8;text-align:center;margin-top:11px}
.section {padding:69px 0 0}
.heading {display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:22px}
.heading h2{font-size:clamp(23px,3.5vw,31px);font-weight:760;letter-spacing:-.035em;line-height:1.25;margin:0}
.heading p {font-size:14px;color:var(--muted);max-width:490px;margin-top:10px}
.table-shell {border:1px solid var(--line);border-radius:16px;background:var(--panel);overflow-x:auto}
table {width:100%;border-collapse:collapse;text-align:left;min-width:650px}
thead{background:#1b2935}
th {padding:16px 19px;font-size:12px;font-weight:800;color:#e9eafa}
th:not(:first-child),td:not(:first-child){text-align:center}
td {padding:15px 19px;border-top:1px solid #2a313c8a;font-size:13px;vertical-align:middle;color:#cbd3e4}
td:first-child{font-weight:630;color:#e0e5f0;width:34%}
td em{font-style:normal;color:#98e0c2;font-weight:730}
td span {color:#a8b1c6}
.table-foot {color:var(--faint);font-size:12px;margin:12px 0 0}
.faq-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.faq-item {background:#121623;border:1px solid var(--line);border-radius:14px;padding:22px 23px}
.faq-item h3 {font-size:15px;line-height:1.4;font-weight:760;margin:0 0 10px}
.faq-item p {font-size:13px;line-height:1.7;margin:0;color:var(--muted)}
.footer {margin-top:66px;border-top:1px solid #ffffff12;padding:24px 0 34px;color:var(--faint);font-size:12px}
.footer-inner{display:flex;justify-content:space-between;align-items:center;gap:14px}
.footer a:hover {color:var(--accent)}
@media(max-width:930px){.plans{grid-template-columns:1fr 1fr}.plan:last-child{grid-column:span 2}.plan-sub{min-height:auto}}
@media(max-width:640px){
  .wrap{padding:0 18px}.top-inner{height:66px}.back{padding:8px 11px}
  .hero{padding:52px 0 31px}.hero p{font-size:14px}
  .announcement{display:block}.announcement strong{display:block;margin-bottom:5px}
  .plans{grid-template-columns:1fr}.plan:last-child{grid-column:auto}
  .plan{padding:23px 21px}.price strong{font-size:38px}
  .section{padding-top:54px}.heading{display:block}
  .faq-grid{grid-template-columns:1fr}
  .footer-inner{align-items:flex-start;flex-direction:column}
}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
</head>
<body>
<header class="topbar"><div class="wrap top-inner">
  <a class="brand" href="/app" aria-label="SentriX — Retour au dashboard">
    <span class="mark" aria-hidden="true">S</span><span>SentriX<small>Offres Premium</small></span>
  </a>
  <a class="back" href="/app">← Dashboard</a>
</div></header>
<main id="main" class="wrap">
  <section class="hero" aria-labelledby="page-title">
    <p class="overline">SENTRIX · OFFRES À L'ÉTUDE</p>
    <h1 id="page-title">Plus de possibilités, <span>sans sacrifier le gratuit.</span></h1>
    <p>SentriX reste complet pour tous les serveurs. Les futures offres Premium ajouteront de la personnalisation et des outils avancés, sans retirer les fonctionnalités que vous utilisez déjà.</p>
  </section>
  <div class="announcement" role="status">
    <strong>Préparation en cours</strong>
    <span>Les tarifs ci-dessous sont indicatifs. Aucun abonnement, prélèvement ou paiement n'est activé sur cette page.</span>
  </div>
  <section class="plans" aria-label="Offres SentriX">
    <article class="plan">
      <div class="plan-top"><span class="plan-name">SentriX Free</span><span class="plan-state active">Actuel</span></div>
      <p class="plan-sub">Toutes les fonctions essentielles de votre serveur, sans frais.</p>
      <div class="price"><strong>0 €</strong><span>/ mois</span></div>
      <p class="per">Sans carte bancaire</p><div class="line"></div>
      <h3>Comprend notamment</h3>
      <ul>
        <li>Modération et protections essentielles</li>
        <li>Tickets et panneaux de support</li>
        <li>Bienvenue, niveaux et économie</li>
        <li>Logs, jeux et musique déjà accessibles</li>
        <li>Configuration depuis le dashboard</li>
      </ul>
      <a class="cta" href="/app">Accéder au dashboard</a>
      <p class="meta">Aucun changement à votre accès actuel.</p>
    </article>
    <article class="plan featured">
      <div class="plan-top"><span class="plan-name">SentriX Premium</span><span class="plan-state">Projet</span></div>
      <p class="plan-sub">Plus de confort et de contrôle pour les serveurs actifs.</p>
      <div class="price"><strong>2,99 €</strong><span>/ mois</span></div>
      <p class="per">Tarif envisagé · par serveur</p><div class="line"></div>
      <h3>Avantages envisagés</h3>
      <ul>
        <li>Tous les avantages Free conservés</li>
        <li>Modèles avancés de messages et panneaux</li>
        <li>Personnalisation plus poussée</li>
        <li>Historique et exports approfondis</li>
        <li>Automatisations supplémentaires</li>
      </ul>
      <span class="unavailable" aria-disabled="true">Bientôt disponible</span>
      <p class="meta">Aucun achat possible pour le moment.</p>
    </article>
    <article class="plan">
      <div class="plan-top"><span class="plan-name">SentriX Premium+</span><span class="plan-state">Projet</span></div>
      <p class="plan-sub">Des outils enrichis pour les communautés les plus exigeantes.</p>
      <div class="price"><strong>5,99 €</strong><span>/ mois</span></div>
      <p class="per">Tarif envisagé · par serveur</p><div class="line"></div>
      <h3>Avantages envisagés</h3>
      <ul>
        <li>Tous les avantages Premium</li>
        <li>Personnalisation et modèles étendus</li>
        <li>Exports et rapports plus détaillés</li>
        <li>Outils d'administration avancés</li>
        <li>Support prioritaire envisagé</li>
      </ul>
      <span class="unavailable" aria-disabled="true">Bientôt disponible</span>
      <p class="meta">Aucun achat possible pour le moment.</p>
    </article>
  </section>
  <section class="section" aria-labelledby="compare-title">
    <div class="heading"><div><h2 id="compare-title">Les différences, simplement.</h2>
      <p>Les fonctionnalités actuelles restent disponibles. Le tableau présente une proposition d'évolution des offres, pas des restrictions déjà actives.</p></div></div>
    <div class="table-shell" role="region" aria-label="Comparatif des offres" tabindex="0">
      <table>
        <thead><tr><th scope="col">Fonctionnalité</th><th scope="col">Free</th><th scope="col">Premium</th><th scope="col">Premium+</th></tr></thead>
        <tbody>
          <tr><td>Modération et sécurité existantes</td><td><em>Inclus</em></td><td><em>Inclus</em></td><td><em>Inclus</em></td></tr>
          <tr><td>Tickets, logs, accueil, niveaux</td><td><em>Inclus</em></td><td><em>Inclus</em></td><td><em>Inclus</em></td></tr>
          <tr><td>Tableau de bord actuel</td><td><em>Inclus</em></td><td><em>Inclus</em></td><td><em>Inclus</em></td></tr>
          <tr><td>Modèles et personnalisation</td><td><span>Standard</span></td><td>Avancés*</td><td>Étendus*</td></tr>
          <tr><td>Rapports et exports additionnels</td><td><span>Actuels</span></td><td>Avancés*</td><td>Étendus*</td></tr>
          <tr><td>Automatisations supplémentaires</td><td><span>Actuelles</span></td><td>Plus d'options*</td><td>Plus d'options*</td></tr>
          <tr><td>Accompagnement</td><td><span>Communauté</span></td><td><span>À définir*</span></td><td>Prioritaire*</td></tr>
        </tbody>
      </table>
    </div>
    <p class="table-foot">* Avantages à l'étude, non activés et susceptibles d'évoluer.</p>
  </section>
  <section class="section" aria-labelledby="faq-title">
    <div class="heading"><div><h2 id="faq-title">Questions fréquentes</h2>
      <p>Les réponses essentielles avant l'arrivée d'une éventuelle offre payante.</p></div></div>
    <div class="faq-grid">
      <article class="faq-item"><h3>Est-ce que SentriX Free sera limité ?</h3><p>Non. Cette préparation ne supprime aucune commande ni fonctionnalité déjà accessible. Les offres payantes envisagent seulement des options additionnelles.</p></article>
      <article class="faq-item"><h3>Peut-on payer maintenant ?</h3><p>Non. Aucun paiement ni abonnement n'est actif. Les offres ne seront proposées que lorsqu'une solution de facturation conforme et fiable sera prête.</p></article>
      <article class="faq-item"><h3>Les prix sont-ils définitifs ?</h3><p>Non. Les tarifs affichés sont des propositions. Leur montant et les fonctions associées pourront changer avant l'ouverture des ventes.</p></article>
      <article class="faq-item"><h3>Comment seront protégés les paiements ?</h3><p>Le paiement devra passer par un prestataire éligible et sécurisé, sous la responsabilité d'un titulaire de compte autorisé. SentriX ne demandera pas vos numéros de carte dans Discord.</p></article>
    </div>
  </section>
</main>
<footer class="footer"><div class="wrap footer-inner">
  <span>© SentriX · Offres en préparation · Aucun paiement actif</span>
  <a href="/app">Retourner au dashboard →</a>
</div></footer>
</body></html>'''


async def handle_premium_catalog(request: web.Request) -> web.Response:
    """Page publique informative sans transaction, compte ni donnée personnelle."""
    return web.Response(
        text=PAGE_HTML,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        },
    )


def inject_premium_link(html: str) -> str:
    """Ajout de deux liens de navigation sans changer le JavaScript ni les modules."""
    if not isinstance(html, str) or 'data-sentrix-premium-link' in html:
        return html
    style = '''
<style id="sentrix-premium-nav-css">
.nav a.sx-plan-link{display:block;margin:10px 0 3px;padding:11px 12px;border:1px solid #594c91;border-radius:10px;
background:#7c6cff12;color:#c9c2ff;font-size:13px;font-weight:700;text-decoration:none}
.nav a.sx-plan-link:hover{background:#7c6cff24;color:#ece8ff;border-color:#8d7beb}
.nav a.sx-plan-link:focus-visible{outline:2px solid #b3a7ff;outline-offset:2px}
</style>
'''
    if "</head>" in html:
        html = html.replace("</head>", style + "</head>", 1)
    nav_begin = html.find('id="navigation"')
    if nav_begin != -1:
        nav_close = html.find("</nav>", nav_begin)
        if nav_close != -1:
            html = html[:nav_close] + '<a class="sx-plan-link" data-sentrix-premium-link href="/premium">SentriX Premium</a>' + html[nav_close:]
    invitation = '<a class="btn" id="inviteButton"'
    if invitation in html:
        begin = html.find(invitation)
        close = html.find("</a>", begin)
        if close != -1:
            close += len("</a>")
            html = html[:close] + '\n<a class="btn ghost" href="/premium">Découvrir Premium</a>' + html[close:]
    return html


def install(dashboard) -> None:
    """Installation additive, idempotente, sans changer les autorisations existantes."""
    global _INSTALLED
    if _INSTALLED:
        return
    original = dashboard.build_app

    def build_app(bot):
        app = original(bot)
        app.router.add_get("/premium", handle_premium_catalog)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = inject_premium_link(dashboard.INDEX_HTML)
    _INSTALLED = True
