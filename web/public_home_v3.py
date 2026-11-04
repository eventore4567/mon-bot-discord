"""Landing publique SentriX (refonte éditoriale du 04/11/2026).

Surface publique uniquement. Le dashboard canonique reste /app et n'est jamais
réimplémenté ici. La landing reprend volontairement la palette et les principes
visuels du dashboard existant (graphite + bleu SentriX) sans exposer de données privées.
"""
from __future__ import annotations

import html


PAGE_TEMPLATE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f4f1ea">
<meta name="color-scheme" content="light dark">
<title>SentriX — le bot qui garde votre serveur Discord en ordre</title>
<meta name="description" content="SentriX modère, protège contre les raids et les nukes, gère tickets, logs, musique et économie. Réglages avec /setup ou depuis le dashboard. Gratuit.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="__CANONICAL__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — le bot qui garde votre serveur Discord en ordre">
<meta property="og:description" content="Modération, anti-raid, anti-nuke, tickets, logs, musique. Gratuit, en français.">
<meta property="og:url" content="__CANONICAL__">
<meta name="twitter:card" content="summary_large_image">
<style>
/* 04/11/2026 : refonte « éditoriale ». L'ancienne page avait tous les tics d'une
   page générée (slogan en dégradé, halos, cubes 3D, fausse maquette, pastilles) :
   ici du papier, de l'encre, une seule couleur, et le vrai produit. */
:root{
  --paper:#f4f1ea;--paper2:#ebe6db;--ink:#17161b;--soft:#4c4955;--muted:#7a7684;
  --line:#d9d2c3;--accent:#4b3fd1;--accent-ink:#ffffff;--red:#d23f3f;
  --discord:#313338;--discord2:#2b2d31;--discord-text:#dbdee1;--discord-muted:#949ba4;
  --serif:ui-serif,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
}
@media(prefers-color-scheme:dark){:root{
  --paper:#151412;--paper2:#1d1b18;--ink:#efebe3;--soft:#c3bdb2;--muted:#8f897e;
  --line:#33302b;--accent:#8f86ff;--accent-ink:#151412;
}}
*{box-sizing:border-box}
html{background:var(--paper)}
body{margin:0;color:var(--ink);background:var(--paper);font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
code,kbd{font:500 .92em/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.skip{position:absolute;left:-999px;top:8px;background:var(--ink);color:var(--paper);padding:8px 12px;border-radius:6px;z-index:10}
.skip:focus{left:8px}
.wrap{width:min(1080px,calc(100% - 40px));margin:0 auto}
header.top{border-bottom:1px solid var(--line)}
.nav{display:flex;align-items:center;gap:28px;height:64px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;text-decoration:none;letter-spacing:-.01em}
.brand img{width:28px;height:28px;border-radius:7px}
.nav-links{display:flex;gap:22px;margin-left:auto;font-size:15px}
.nav-links a{text-decoration:none;color:var(--soft)}
.nav-links a:hover{color:var(--ink);text-decoration:underline;text-underline-offset:4px}
.menu{display:none;margin-left:auto;background:none;border:1px solid var(--line);border-radius:8px;padding:6px 10px;color:var(--ink);font:inherit}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:0 18px;border-radius:8px;border:1px solid var(--ink);color:var(--ink);text-decoration:none;font-weight:600;font-size:15px;white-space:nowrap}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.btn.ghost{border-color:var(--line)}
.btn:hover{filter:brightness(.94)}
.btn:focus-visible,.nav-links a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.auth-notice{width:min(1080px,calc(100% - 40px));margin:14px auto 0;padding:10px 14px;border:1px solid var(--line);border-radius:8px;background:var(--paper2);font-size:14px}
.hero{display:grid;grid-template-columns:1.05fr .95fr;gap:56px;align-items:center;padding:72px 0 64px}
h1,h2,h3{font-family:var(--serif);font-weight:600;letter-spacing:-.015em;line-height:1.08;margin:0}
h1{font-size:clamp(40px,5vw,64px)}
h2{font-size:clamp(30px,3.4vw,42px)}
h3{font-size:22px}
.lead{font-size:19px;color:var(--soft);margin:22px 0 28px;max-width:34em}
.actions{display:flex;flex-wrap:wrap;gap:12px}
.proof{margin:22px 0 0;color:var(--muted);font-size:15px}
.proof strong{color:var(--ink);font-variant-numeric:tabular-nums}
/* Conversation Discord : le vrai rendu de SentriX, pas une maquette inventée. */
.chat{background:var(--discord);color:var(--discord-text);border-radius:10px;padding:18px 18px 20px;font-size:15px;line-height:1.45;box-shadow:0 1px 0 rgba(0,0,0,.08)}
.msg{display:grid;grid-template-columns:40px 1fr;gap:12px}
.msg+.msg{margin-top:16px}
.avatar{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;font-weight:700;color:#fff}
.avatar.user{background:#5865f2}
.avatar.bot{background:#2a2470;overflow:hidden}
.avatar.bot img{width:100%;height:100%}
.who{font-weight:600;color:#f2f3f5}
.who .tag{display:inline-block;margin-left:6px;padding:0 5px;border-radius:4px;background:#5865f2;color:#fff;font-size:11px;font-weight:700;vertical-align:2px}
.who time{margin-left:8px;color:var(--discord-muted);font-size:12px;font-weight:400}
.slash{color:var(--discord-muted);font-size:13px}
.slash b{color:#c9cdfb;font-weight:600}
.mention{background:rgba(88,101,242,.3);color:#c9cdfb;border-radius:3px;padding:0 2px}
.card{margin-top:6px;background:var(--discord2);border-radius:8px;border-left:4px solid var(--red);padding:12px 14px}
.card.blue{border-left-color:#5865f2}
.card h4{margin:0 0 4px;font:600 16px/1.3 ui-sans-serif,system-ui,sans-serif;color:#f2f3f5}
.card p{margin:4px 0;color:var(--discord-text)}
.card small{color:var(--discord-muted)}
.card hr{border:0;border-top:1px solid #3f4147;margin:10px 0}
section.block{padding:72px 0;border-top:1px solid var(--line)}
.kicker{display:block;font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin-bottom:12px}
.intro{max-width:40em;color:var(--soft);margin:14px 0 0}
.commands{margin-top:36px;border-top:1px solid var(--ink)}
.commands div{display:grid;grid-template-columns:minmax(220px,.8fr) 1.2fr;gap:24px;padding:18px 0;border-bottom:1px solid var(--line)}
.commands code{font-size:16px;color:var(--ink)}
.commands p{margin:0;color:var(--soft)}
.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:40px;margin-top:40px}
.facts .n{font-family:var(--serif);font-size:15px;color:var(--muted);display:block;margin-bottom:8px}
.facts p{color:var(--soft);margin:10px 0 0}
.split{display:grid;grid-template-columns:1fr 1fr;gap:56px;align-items:start;margin-top:40px}
.list{margin:0;padding:0;list-style:none}
.list li{padding:12px 0;border-bottom:1px solid var(--line)}
.list li:first-child{border-top:1px solid var(--line)}
details{border-bottom:1px solid var(--line);padding:18px 0}
details:first-of-type{border-top:1px solid var(--ink);margin-top:32px}
summary{cursor:pointer;font-weight:600;font-size:18px;list-style:none}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";float:right;color:var(--muted);font-weight:400}
details[open] summary::after{content:"–"}
details p{color:var(--soft);margin:12px 0 0;max-width:46em}
.final{padding:80px 0;border-top:1px solid var(--line)}
.final p{color:var(--soft);margin:14px 0 26px;max-width:36em}
footer{border-top:1px solid var(--line);padding:28px 0 40px;color:var(--muted);font-size:14px}
footer .wrap{display:flex;flex-wrap:wrap;gap:12px 24px;justify-content:space-between}
footer nav{display:flex;flex-wrap:wrap;gap:8px 20px}
footer a{text-decoration:none}
footer a:hover{color:var(--ink);text-decoration:underline}
@media(max-width:1180px){.hero{gap:40px}}
@media(max-width:900px){.hero,.split{grid-template-columns:1fr}.facts{grid-template-columns:1fr;gap:28px}.hero{padding:48px 0}}
@media(max-width:720px){
  .nav-links{display:none;position:absolute;left:0;right:0;top:64px;flex-direction:column;gap:0;background:var(--paper);border-bottom:1px solid var(--line);padding:6px 20px 14px;z-index:5}
  .nav-links.open{display:flex}
  .nav-links a{padding:10px 0}
  .menu{display:inline-flex}
  header.top{position:relative}
  .nav .btn{display:none}
  .commands div{grid-template-columns:1fr;gap:6px}
  section.block{padding:56px 0}
}
@media(max-width:430px){.wrap{width:calc(100% - 32px)}.lead{font-size:17px}.actions .btn{flex:1 1 100%}}
@media(max-width:380px){h1{font-size:36px}.chat{padding:14px}}
@media(pointer:coarse){.nav-links a{min-height:44px;display:flex;align-items:center}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>
</head>
<body>
<a class="skip" href="#main">Aller au contenu</a>
<header class="top">
  <div class="wrap nav">
    <a class="brand" href="/"><img src="/sentrix-avatar.png?v=55" alt="" width="28" height="28">SentriX</a>
    <button class="menu" type="button" aria-expanded="false" aria-controls="navLinks">Menu</button>
    <nav class="nav-links" id="navLinks" aria-label="Navigation principale">
      <a href="#commandes">Commandes</a>
      <a href="#securite">Sécurité</a>
      <a href="#dashboard">Dashboard</a>
      <a href="/docs">Documentation</a>
      <a href="/support">Support</a>
    </nav>
    <a class="btn primary" href="/app" data-dashboard-entry>Dashboard</a>
  </div>
</header>
<p id="sxAuthNotice" class="auth-notice" hidden></p>
<main id="main">
<div class="wrap hero">
  <div>
    <h1>Le bot qui garde votre serveur Discord en ordre.</h1>
    <p class="lead">SentriX modère, bloque les raids et les nukes, gère les tickets, les logs, la musique et l'économie. Tout se règle avec <code>/setup</code> ou depuis le dashboard. C'est gratuit.</p>
    <div class="actions">
      <a class="btn primary" href="__INVITE__" target="_blank" rel="noopener">Ajouter à Discord</a>
      <a class="btn" href="/app" data-dashboard-entry>Ouvrir le dashboard</a>
    </div>
    <p class="proof">Actif sur <strong id="publicGuilds">—</strong> serveurs, pour <strong id="publicMembers">—</strong> membres.</p>
  </div>
  <div class="chat" aria-label="Exemple de modération dans Discord">
    <div class="msg">
      <div class="avatar user" aria-hidden="true">T</div>
      <div><div class="who">tomioka<time>aujourd'hui à 16:22</time></div>
        <div class="slash">a utilisé <b>/moderation ban</b></div>
        <div>membre : <span class="mention">@raider</span> raison : spam de liens</div></div>
    </div>
    <div class="msg">
      <div class="avatar bot" aria-hidden="true"><img src="/sentrix-avatar.png?v=55" alt=""></div>
      <div><div class="who">SentriX<span class="tag">APP</span><time>aujourd'hui à 16:22</time></div>
        <div class="card"><h4>🔨 Bannissement effectué</h4>
          <p>🔴 raider · <span class="mention">@raider</span></p><hr>
          <p><b>📝 Motif</b><br>spam de liens</p>
          <small>🛡️ Par tomioka · 📁 Dossier #42 · visible par vous seul</small></div></div>
    </div>
  </div>
</div>

<section class="block" id="commandes">
  <div class="wrap">
    <span class="kicker">Commandes</span>
    <h2>Ce que vous tapez, ce qui se passe.</h2>
    <p class="intro">Toutes les commandes existent en <code>/</code> et avec le préfixe <code>+</code>. La liste complète est sur la page <a href="/commands">Commandes</a>.</p>
    <div class="commands">
      <div><code>/moderation ban @membre</code><p>Le membre est banni, un dossier numéroté part dans vos logs et il reçoit un message privé.</p></div>
      <div><code>/security strict</code><p>Le propriétaire soumet aussi les administrateurs à l'AutoMod.</p></div>
      <div><code>+music saif</code><p>Le bon titre est retrouvé même mal écrit, puis joué dans votre salon vocal.</p></div>
      <div><code>/role menu</code><p>Un panneau de rôles en deux clics, avec des modèles prêts : couleurs, jeux, notifications.</p></div>
      <div><code>/setup</code><p>Tous les réglages au même endroit, sans quitter Discord.</p></div>
      <div><code>/bot bug</code><p>Votre signalement arrive directement chez le développeur.</p></div>
    </div>
  </div>
</section>

<section class="block" id="securite">
  <div class="wrap">
    <span class="kicker">Sécurité</span>
    <h2>Pensé pour les vraies attaques.</h2>
    <div class="facts">
      <div><span class="n">01</span><h3>Anti-spam</h3><p>Les rafales sont comptées à l'heure d'envoi : même un compte qui lag est sanctionné, dès la première fois. Majuscules, pings répétés et liens d'invitation aussi.</p></div>
      <div><span class="n">02</span><h3>Anti-nuke</h3><p>Un compte qui supprime des salons ou des rôles en masse est sanctionné, puis tout est recréé : noms, catégories, positions et permissions.</p></div>
      <div><span class="n">03</span><h3>Logs lisibles</h3><p>Qui, quoi, où, avec la bonne mention. Les messages supprimés, les rôles déplacés, les arrivées et les départs.</p></div>
    </div>
    <div class="split">
      <div class="chat" aria-label="Exemple de log">
        <div class="msg">
          <div class="avatar bot" aria-hidden="true"><img src="/sentrix-avatar.png?v=55" alt=""></div>
          <div><div class="who">Rôles<span class="tag">APP</span><time>aujourd'hui à 17:13</time></div>
            <div class="card blue"><h4>Rôle déplacé</h4>
              <p><span class="mention">@Modérateur</span> · 11 → 3 (⬇️ descendu de 8)</p>
              <p><b>Autres rôles</b> · 8 décalé(s) d'un cran</p>
              <p><b>Modérateur</b> · <span class="mention">@tomioka</span></p></div></div>
        </div>
      </div>
      <ul class="list">
        <li>Anti-raid, anti-bot et filtre des nouveaux comptes.</li>
        <li>Mode strict : seul le propriétaire peut l'activer.</li>
        <li>Les réponses de modération ne sont visibles que par le staff.</li>
        <li>Chaque filtre se règle salon par salon, avec des rôles exemptés.</li>
      </ul>
    </div>
  </div>
</section>

<section class="block" id="dashboard">
  <div class="wrap split" style="margin-top:0">
    <div>
      <span class="kicker">Dashboard</span>
      <h2>Les mêmes réglages, sur grand écran.</h2>
      <p class="intro">Le dashboard reprend ce que fait <code>/setup</code> : modules, logs, AutoMod, tickets, bienvenue, niveaux et économie. Vous vous connectez avec Discord et vous ne voyez que les serveurs que vous gérez.</p>
      <div class="actions" style="margin-top:26px"><a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a><a class="btn ghost" href="/support">Support</a></div>
    </div>
    <ul class="list">
      <li>Activer ou couper une commande pour tout le serveur.</li>
      <li>Choisir un salon de logs par catégorie d'événements.</li>
      <li>Préparer les messages de bienvenue et de départ.</li>
      <li>Suivre les sanctions et les tickets.</li>
    </ul>
  </div>
</section>

<section class="block" id="faq">
  <div class="wrap">
    <span class="kicker">Questions</span>
    <h2>Questions fréquentes.</h2>
    <details><summary>C'est vraiment gratuit ?</summary><p>Oui. La modération, la sécurité, les logs, les tickets, la musique et l'économie sont gratuits. La page <a href="/premium">Premium</a> détaille les options en plus.</p></details>
    <details><summary>De quelles permissions SentriX a-t-il besoin ?</summary><p>Celles des modules que vous activez. Pour sanctionner, son rôle doit être placé au-dessus des membres concernés.</p></details>
    <details><summary>Le bot parle-t-il français ?</summary><p>Oui, par défaut. Un administrateur peut passer le serveur en anglais : les messages et l'IA suivent.</p></details>
    <details><summary>Que faites-vous de nos données ?</summary><p>SentriX garde ce qu'il faut pour fonctionner (réglages, sanctions, logs). Tout est expliqué dans la <a href="/privacy">politique de confidentialité</a>.</p></details>
  </div>
</section>

<section class="final">
  <div class="wrap">
    <h2>Essayez-le sur votre serveur.</h2>
    <p>L'ajout prend une minute. Ensuite, lancez <code>/setup</code> et choisissez ce que vous voulez activer.</p>
    <div class="actions"><a class="btn primary" href="__INVITE__" target="_blank" rel="noopener">Ajouter à Discord</a><a class="btn ghost" href="/support">Support</a></div>
  </div>
</section>
</main>
<footer>
  <div class="wrap">
    <span>SentriX</span>
    <nav aria-label="Liens du site">
      <a href="/commands">Commandes</a><a href="/docs">Documentation</a><a href="/support">Support</a><a href="/premium">Premium</a><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a>
    </nav>
  </div>
</footer>
<script>
const $=s=>document.querySelector(s),$$=s=>Array.from(document.querySelectorAll(s));
const nombre=v=>Number(v||0).toLocaleString("fr-FR");
async function loadPublic(){try{const r=await fetch("/api/public",{cache:"no-store",credentials:"same-origin"});if(!r.ok)return;const d=await r.json();if(Number(d.guilds)>0){$("#publicGuilds").textContent=nombre(d.guilds);$("#publicMembers").textContent=nombre(d.members)}}catch(_){}}
let opening=false;
async function openDashboard(e){if(opening)return;e.preventDefault();opening=true;let target="/login";try{const r=await fetch("/api/me",{cache:"no-store",credentials:"same-origin"});if(r.ok)target="/app"}catch(_){}location.assign(target)}
$$("[data-dashboard-entry]").forEach(a=>a.addEventListener("click",openDashboard));
const menu=$(".menu"),links=$("#navLinks");
if(menu&&links){menu.addEventListener("click",()=>{const ouvert=links.classList.toggle("open");menu.setAttribute("aria-expanded",ouvert?"true":"false")});links.addEventListener("click",e=>{if(e.target.closest("a")){links.classList.remove("open");menu.setAttribute("aria-expanded","false")}})}
const params=new URLSearchParams(location.search);
if(params.get("auth")==="missing"){const notice=$("#sxAuthNotice");if(notice){notice.textContent="Connexion Discord momentanément indisponible. Réessayez ou consultez le support.";notice.hidden=false}history.replaceState(null,"",location.pathname)}
loadPublic();
</script>
</body>
</html>
'''


def render(request, dashboard) -> str:
    bot = request.app.get("bot")
    base = str(dashboard._public_url(request)).rstrip("/")
    invite = dashboard._invite_url(bot) or "/login"
    canonical = base + "/"
    return (
        PAGE_TEMPLATE
        .replace("__INVITE__", html.escape(str(invite), quote=True))
        .replace("__CANONICAL__", html.escape(canonical, quote=True))
    )
