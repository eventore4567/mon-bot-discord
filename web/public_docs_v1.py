"""Documentation publique SentriX V1.

Documentation autonome et publique. Elle décrit les parcours et modules sans exposer
la configuration privée d'un serveur. La liste exacte des commandes reste sur /commands.
"""
from __future__ import annotations

import html


PAGE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0d10">
<title>Documentation SentriX — Guide complet du bot Discord</title>
<meta name="description" content="Documentation complète de SentriX : installation, permissions Discord, dashboard, modération, sécurité, tickets, logs, rôles, niveaux, économie, jeux, musique, IA et automatisations.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="__CANONICAL__">
<style>
:root{--bg:#0b0d10;--bg2:#101318;--panel:#15191f;--panel2:#1a1f27;--line:#2a313c;--line2:#343d49;--text:#f2f5f8;--soft:#bac3cf;--muted:#929dac;--blue:#4da3ff;--blue2:#77bcff;--blue-bg:#12253a;--green:#55d69a;--amber:#efbd61}
*{box-sizing:border-box}html{scroll-behavior:smooth;background:var(--bg)}body{margin:0;color:var(--text);font:14px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;background:
radial-gradient(1000px 700px at 85% -8%,rgba(77,163,255,.22),transparent 60%),
radial-gradient(760px 520px at 8% 28%,rgba(89,110,255,.10),transparent 66%),
linear-gradient(180deg,#080b10,#0b1016 48%,#090c11);-webkit-font-smoothing:antialiased;overflow-x:hidden}
.docs-space{position:fixed;inset:0;z-index:-2;pointer-events:none;overflow:hidden}
.docs-space:before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(119,188,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(119,188,255,.025) 1px,transparent 1px);background-size:68px 68px;transform:perspective(900px) rotateX(66deg) scale(1.45) translateY(23%);transform-origin:center bottom;animation:docsGrid 10s linear infinite}
.docs-orb{position:absolute;border-radius:50%;filter:blur(16px);mix-blend-mode:screen}
.docs-orb.one{width:38vw;height:38vw;left:-10vw;top:12%;background:radial-gradient(circle,rgba(77,163,255,.16),transparent 68%);animation:docsOrbOne 17s ease-in-out infinite}
.docs-orb.two{width:31vw;height:31vw;right:-6vw;top:48%;background:radial-gradient(circle,rgba(86,105,255,.13),transparent 68%);animation:docsOrbTwo 20s ease-in-out infinite}
.docs-beam{position:absolute;height:1px;background:linear-gradient(90deg,transparent,rgba(119,188,255,.72),transparent);filter:drop-shadow(0 0 7px rgba(77,163,255,.5));opacity:.16}
.docs-beam.b1{width:68vw;left:-8vw;top:24%;transform:rotate(-10deg);animation:docsBeam 13s ease-in-out infinite}.docs-beam.b2{width:62vw;right:-12vw;top:67%;transform:rotate(8deg);animation:docsBeamB 16s ease-in-out infinite}
.docs-symbol{position:absolute;color:rgba(119,188,255,.11);font:800 9px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.18em;text-transform:uppercase}.docs-symbol.s1{left:4vw;top:42%;animation:docsCode 12s ease-in-out infinite}.docs-symbol.s2{right:5vw;top:17%;animation:docsCodeB 15s ease-in-out infinite}
.hero{position:relative}.hero:after{content:"";position:absolute;right:4%;top:18px;width:230px;height:230px;border-radius:50%;border:1px solid rgba(119,188,255,.16);box-shadow:0 0 70px rgba(77,163,255,.08);background:repeating-radial-gradient(circle,transparent 0 29px,rgba(119,188,255,.055) 30px 31px);animation:docsRadar 12s linear infinite}
.doc-section{position:relative;overflow:hidden;transform-style:preserve-3d;transition:border-color .2s ease,transform .2s ease,box-shadow .2s ease}
.doc-section:before{content:"";position:absolute;inset:-55% -25%;pointer-events:none;background:linear-gradient(112deg,transparent 39%,rgba(119,188,255,.07) 49%,transparent 59%);transform:translateX(-75%) rotate(7deg);transition:transform .8s ease}
.doc-section:hover:before{transform:translateX(75%) rotate(7deg)}.doc-section:hover{border-color:#40516a;box-shadow:0 22px 54px rgba(0,0,0,.28),0 0 28px rgba(77,163,255,.05)}
.doc-section.enter{animation:docEnter .68s cubic-bezier(.16,.84,.31,1) both}
.doc-section.enter h2{animation:docTitle .8s cubic-bezier(.16,.84,.31,1) both}
.doc-card,.step{transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}.doc-card:hover,.step:hover{transform:translateY(-3px);border-color:#3f4b5c;box-shadow:0 14px 28px rgba(0,0,0,.20)}
.sidebar{box-shadow:0 18px 50px rgba(0,0,0,.18)}.side-link.active{box-shadow:inset 3px 0 0 var(--blue),0 0 22px rgba(77,163,255,.07)}
.search{transition:border-color .16s ease,box-shadow .16s ease}.search:focus{box-shadow:0 0 0 3px rgba(77,163,255,.08),0 0 24px rgba(77,163,255,.08)}

a{color:inherit;text-decoration:none}button,input{font:inherit;color:inherit}:focus-visible{outline:2px solid var(--blue2);outline-offset:2px}.wrap{width:min(1260px,calc(100% - 36px));margin:auto}
header{position:sticky;top:0;z-index:20;border-bottom:1px solid rgba(255,255,255,.055);background:rgba(11,13,16,.9);backdrop-filter:blur(14px)}.nav{height:66px;display:flex;align-items:center;gap:15px}.brand{display:flex;align-items:center;gap:9px;font-size:17px;font-weight:850;white-space:nowrap}.brand img{width:36px;height:36px;border-radius:11px;border:1px solid var(--line)}.navlinks{display:flex;align-items:center;gap:3px;margin-left:auto}.navlinks a{padding:8px 10px;border-radius:9px;color:var(--muted);font-size:12px;font-weight:700}.navlinks a:hover{background:var(--panel);color:#fff}.btn{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:8px 12px;border:1px solid var(--line);border-radius:9px;background:var(--panel);font-weight:750;font-size:12px}.btn.primary{border-color:rgba(77,163,255,.5);background:linear-gradient(135deg,#2f7fd4,var(--blue),var(--blue2));color:#06111c}
.hero{padding:62px 0 36px}.eyebrow{color:var(--blue2);font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.11em}.hero h1{max-width:900px;margin:9px 0 14px;font-size:clamp(38px,6vw,68px);line-height:1;letter-spacing:-.05em}.hero p{max-width:820px;margin:0;color:var(--muted);font-size:16px}.hero-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}
.docs{display:grid;grid-template-columns:255px minmax(0,1fr);gap:22px;padding:20px 0 80px}.sidebar{position:sticky;top:84px;align-self:start;max-height:calc(100vh - 100px);overflow:auto;padding:12px;border:1px solid var(--line);border-radius:14px;background:rgba(16,19,24,.84)}.search{width:100%;height:40px;padding:0 11px;border:1px solid var(--line);border-radius:9px;background:#0d1116;outline:none}.search:focus{border-color:var(--blue)}.side-title{margin:13px 8px 5px;color:var(--muted);font-size:9px;font-weight:850;text-transform:uppercase;letter-spacing:.1em}.side-link{display:block;padding:7px 9px;border-radius:8px;color:var(--soft);font-size:11px;font-weight:650}.side-link:hover,.side-link.active{background:var(--blue-bg);color:#dceeff}
.content{min-width:0}.doc-section{scroll-margin-top:86px;margin-bottom:18px;padding:21px;border:1px solid var(--line);border-radius:15px;background:linear-gradient(145deg,var(--panel),#11151a)}.doc-section h2{margin:0 0 7px;font-size:22px;letter-spacing:-.025em}.doc-section>p{margin:0;color:var(--muted)}.doc-section h3{margin:19px 0 7px;font-size:14px}.doc-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:14px}.doc-card{padding:13px;border:1px solid var(--line);border-radius:11px;background:#101318}.doc-card b{display:block;font-size:11px}.doc-card p{margin:4px 0 0;color:var(--muted);font-size:10px}.steps{display:grid;gap:8px;margin-top:14px}.step{display:grid;grid-template-columns:31px 1fr;gap:10px;align-items:start;padding:10px;border:1px solid var(--line);border-radius:10px;background:#101318}.step i{width:29px;height:29px;border-radius:8px;background:var(--blue-bg);display:grid;place-items:center;color:#9ed0ff;font-style:normal;font-size:8px;font-weight:850}.step b{display:block;font-size:11px}.step span{display:block;margin-top:2px;color:var(--muted);font-size:10px}.callout{margin-top:13px;padding:11px 12px;border-left:3px solid var(--blue);border-radius:8px;background:var(--blue-bg);color:#cbe6ff;font-size:10px}.callout.warn{border-left-color:var(--amber);background:rgba(239,189,97,.08);color:#efd197}.perm-table{width:100%;border-collapse:separate;border-spacing:0;margin-top:12px;overflow:hidden;border:1px solid var(--line);border-radius:10px}.perm-table th,.perm-table td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:10px}.perm-table th{background:#101318;color:var(--soft)}.perm-table td{color:var(--muted)}.perm-table tr:last-child td{border-bottom:0}code{padding:2px 6px;border:1px solid var(--line);border-radius:6px;background:#0d1116;color:#cbe6ff;font:10px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.anchor-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px}.empty{display:none;padding:24px;border:1px dashed var(--line2);border-radius:13px;color:var(--muted);text-align:center}
footer{padding:34px 0;border-top:1px solid rgba(255,255,255,.05);color:var(--muted);font-size:11px}.foot{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.foot a:hover{color:#fff}

@keyframes docsGrid{to{background-position:68px 0,0 68px}}
@keyframes docsOrbOne{0%,100%{transform:translate3d(0,0,0) scale(.95);opacity:.55}50%{transform:translate3d(20vw,13vh,0) scale(1.14);opacity:.95}}
@keyframes docsOrbTwo{0%,100%{transform:translate3d(0,0,0) scale(1);opacity:.48}50%{transform:translate3d(-18vw,-16vh,0) scale(1.18);opacity:.9}}
@keyframes docsBeam{0%,100%{transform:translateX(-8vw) rotate(-10deg);opacity:.08}50%{transform:translateX(38vw) rotate(-5deg);opacity:.34}}
@keyframes docsBeamB{0%,100%{transform:translateX(8vw) rotate(8deg);opacity:.07}50%{transform:translateX(-36vw) rotate(4deg);opacity:.30}}
@keyframes docsCode{0%,100%{transform:translateY(0);opacity:.05}50%{transform:translateY(-40px);opacity:.18}}
@keyframes docsCodeB{0%,100%{transform:translateY(0);opacity:.05}50%{transform:translateY(34px);opacity:.16}}
@keyframes docsRadar{to{transform:rotate(360deg)}}
@keyframes docEnter{0%{opacity:0;filter:blur(8px);transform:translateY(52px) rotateX(7deg) scale(.97)}100%{opacity:1;filter:none;transform:none}}
@keyframes docTitle{0%{letter-spacing:.02em;opacity:.25;transform:translateX(-22px)}100%{letter-spacing:-.025em;opacity:1;transform:none}}

@media(max-width:900px){.docs{grid-template-columns:1fr}.sidebar{position:relative;top:0;max-height:none}.side-list{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}.side-title{grid-column:1/-1}.doc-grid{grid-template-columns:1fr}.navlinks{display:none}}
@media(max-width:560px){.wrap{width:min(calc(100% - 22px),1260px)}.hero{padding-top:42px}.hero h1{font-size:39px}.hero p{font-size:14px}.side-list{grid-template-columns:1fr 1fr}.doc-section{padding:16px}.hero-actions .btn{width:100%}.perm-table{display:block;overflow-x:auto}.nav .btn{margin-left:auto}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.docs-space:before,.docs-orb,.docs-beam,.docs-symbol,.hero:after,.doc-section.enter,.doc-section.enter h2{animation:none!important}.doc-section,.doc-card,.step{transition:none!important}}
</style>
</head>
<body>
<div class="docs-space" aria-hidden="true"><div class="docs-orb one"></div><div class="docs-orb two"></div><div class="docs-beam b1"></div><div class="docs-beam b2"></div><div class="docs-symbol s1">SENTRIX // DOCS // ACTIVE</div><div class="docs-symbol s2">DISCORD // SYSTEMS // GUIDE</div></div>
<header><div class="wrap nav"><a class="brand" href="/"><img src="/sentrix-avatar.png?v=55" alt=""><span>SentriX Docs</span></a><nav class="navlinks"><a href="/">Accueil</a><a href="/commands">Commandes</a><a href="/support">Support</a><a href="/app">Dashboard</a></nav><a class="btn primary" href="/app">Ouvrir le dashboard</a></div></header>
<main class="wrap">
<section class="hero"><span class="eyebrow">Documentation officielle SentriX</span><h1>Comprendre, configurer et utiliser SentriX.</h1><p>Une vraie documentation pour le bot, le dashboard et les principaux systèmes Discord. Pour la liste exacte des commandes actuellement chargées, utilisez la page Commandes.</p><div class="hero-actions"><a class="btn primary" href="/start">Commencer</a><a class="btn" href="/commands">Toutes les commandes</a><a class="btn" href="/support">Support</a></div></section>
<div class="docs">
<aside class="sidebar"><input class="search" id="docSearch" type="search" placeholder="Rechercher dans la documentation" aria-label="Rechercher dans la documentation"><div class="side-list" id="sideList">
<div class="side-title">Fondations</div><a class="side-link" href="#installation">Installation</a><a class="side-link" href="#discord">Discord & permissions</a><a class="side-link" href="#dashboard">Dashboard</a>
<div class="side-title">Staff</div><a class="side-link" href="#moderation">Modération</a><a class="side-link" href="#security">Sécurité / AutoMod</a><a class="side-link" href="#tickets">Tickets</a><a class="side-link" href="#logs">Logs</a>
<div class="side-title">Communauté</div><a class="side-link" href="#roles">Rôles</a><a class="side-link" href="#welcome">Bienvenue</a><a class="side-link" href="#levels">Niveaux</a><a class="side-link" href="#economy">Économie</a><a class="side-link" href="#games">Jeux</a>
<div class="side-title">Outils</div><a class="side-link" href="#music">Musique</a><a class="side-link" href="#notifications">Notifications</a><a class="side-link" href="#automation">Automatisations</a><a class="side-link" href="#ai">IA</a><a class="side-link" href="#troubleshooting">Dépannage</a>
</div></aside>
<div class="content" id="docContent">

<section class="doc-section" id="installation" data-doc="installation ajouter bot démarrage oauth setup serveur">
<h2>Installation & premier démarrage</h2><p>Le parcours recommandé est simple : ajouter le bot, vérifier sa position dans la hiérarchie Discord, se connecter au dashboard, puis activer seulement les modules utiles.</p>
<div class="steps"><div class="step"><i>01</i><div><b>Ajoutez SentriX</b><span>Utilisez le lien officiel d’invitation et choisissez le bon serveur.</span></div></div><div class="step"><i>02</i><div><b>Placez le rôle SentriX correctement</b><span>Pour agir sur un membre ou un rôle, SentriX doit être au-dessus de sa cible dans la hiérarchie.</span></div></div><div class="step"><i>03</i><div><b>Ouvrez le dashboard</b><span>Discord OAuth sert à identifier vos serveurs et à vérifier vos droits d’administration.</span></div></div><div class="step"><i>04</i><div><b>Configurez module par module</b><span>Commencez par les logs et la sécurité, puis ajoutez tickets, rôles, niveaux, économie ou automatisations.</span></div></div></div>
<div class="anchor-actions"><a class="btn" href="/start">Guide rapide</a><a class="btn" href="/app">Dashboard</a></div></section>

<section class="doc-section" id="discord" data-doc="discord permissions hiérarchie rôles salons manage guild ban kick moderate members oauth">
<h2>Discord & permissions</h2><p>Une grande partie des erreurs d’un bot Discord viennent de la hiérarchie ou des permissions, pas du code.</p>
<table class="perm-table"><thead><tr><th>Action</th><th>Permission Discord habituelle</th><th>Point à vérifier</th></tr></thead><tbody><tr><td>Ban / kick</td><td>Ban Members / Kick Members</td><td>Le rôle du bot doit être au-dessus de la cible.</td></tr><tr><td>Timeout / mute</td><td>Moderate Members</td><td>La cible ne doit pas être au-dessus du bot.</td></tr><tr><td>Rôles</td><td>Manage Roles</td><td>Le bot ne peut gérer que les rôles placés sous son rôle.</td></tr><tr><td>Salons / logs</td><td>View Channel + Send Messages</td><td>Vérifier les permissions du salon et des catégories.</td></tr><tr><td>Webhooks / notifications</td><td>Selon le module</td><td>La permission doit exister dans le salon cible.</td></tr></tbody></table>
<div class="callout warn">Administrateur n’annule pas la hiérarchie des rôles : Discord bloque toujours certaines actions si le rôle de SentriX est sous la cible.</div></section>

<section class="doc-section" id="dashboard" data-doc="dashboard app oauth serveur configuration paramètres enregistrer">
<h2>Dashboard</h2><p>Le dashboard canonique est <code>/app</code>. La landing publique et la documentation ne remplacent jamais cette interface.</p>
<div class="doc-grid"><div class="doc-card"><b>Sélection du serveur</b><p>Choisissez un serveur où votre compte possède les droits nécessaires.</p></div><div class="doc-card"><b>Modules indépendants</b><p>Chaque serveur possède sa propre configuration.</p></div><div class="doc-card"><b>Enregistrement</b><p>Les pages qui modifient une configuration indiquent quand une action doit être sauvegardée.</p></div><div class="doc-card"><b>Permissions</b><p>Le dashboard ne contourne pas les permissions Discord du membre connecté.</p></div></div>
<div class="anchor-actions"><a class="btn primary" href="/app">Ouvrir le dashboard</a></div></section>

<section class="doc-section" id="moderation" data-doc="modération ban kick warn mute timeout unmute sanctions staff raison durée">
<h2>Modération</h2><p>SentriX regroupe les actions staff courantes : avertissement, timeout, unmute, kick, ban et autres outils exposés par la surface de commandes.</p>
<div class="doc-grid"><div class="doc-card"><b>Préfixe et slash</b><p>Les commandes peuvent exister en préfixe et en slash selon la surface active. Consultez /commands pour l’état réel.</p></div><div class="doc-card"><b>Raison & durée</b><p>Donnez une raison claire et une durée valide pour les sanctions temporaires.</p></div><div class="doc-card"><b>MP de sanction</b><p>Selon l’action, SentriX peut prévenir le membre et conserver une trace staff.</p></div><div class="doc-card"><b>Logs</b><p>Configurez les logs de modération pour garder le contexte de chaque action.</p></div></div>
<div class="anchor-actions"><a class="btn" href="/commands">Voir les commandes exactes</a></div></section>

<section class="doc-section" id="security" data-doc="sécurité automod anti spam raid lien insulte nuke panic blacklist protection">
<h2>Sécurité & AutoMod</h2><p>Les protections automatiques complètent la modération manuelle. Elles doivent être adaptées au serveur afin d’éviter les faux positifs.</p>
<div class="doc-grid"><div class="doc-card"><b>Anti-spam</b><p>Détecte les répétitions ou volumes anormaux selon la configuration.</p></div><div class="doc-card"><b>Anti-liens</b><p>Filtre les liens selon les règles et listes autorisées configurées.</p></div><div class="doc-card"><b>Anti-raid / anti-nuke</b><p>Surveille certains comportements sensibles et changements rapides.</p></div><div class="doc-card"><b>Protection staff</b><p>Les permissions et la hiérarchie sont vérifiées avant les actions sensibles.</p></div></div>
<div class="callout">Testez chaque protection avec un compte de test avant de durcir les seuils sur un serveur actif.</div></section>

<section class="doc-section" id="tickets" data-doc="tickets panneau type support formulaire claim close transcript ping rôle">
<h2>Tickets</h2><p>Le système de tickets permet de créer des panneaux, types de demandes, formulaires et flux staff.</p>
<div class="steps"><div class="step"><i>01</i><div><b>Créez un panneau</b><span>Définissez le panneau visible par les membres.</span></div></div><div class="step"><i>02</i><div><b>Ajoutez au moins un type</b><span>Chaque type décrit une demande : support, achat, signalement, partenariat, etc.</span></div></div><div class="step"><i>03</i><div><b>Configurez le staff</b><span>Choisissez les rôles ou règles de prise en charge.</span></div></div><div class="step"><i>04</i><div><b>Publiez et testez</b><span>Ouvrez un ticket de test avant de rendre le panneau public.</span></div></div></div></section>

<section class="doc-section" id="logs" data-doc="logs journal messages membres salons rôles vocal tickets automod spam raid ressources">
<h2>Logs</h2><p>Les logs donnent au staff une trace des événements importants. Une catégorie peut être routée vers un salon précis.</p>
<div class="doc-grid"><div class="doc-card"><b>Modération</b><p>Sanctions, timeout, unmute et actions staff.</p></div><div class="doc-card"><b>Messages & membres</b><p>Événements de messages, arrivées, départs et changements utiles.</p></div><div class="doc-card"><b>Serveur</b><p>Salons, rôles, vocal, ressources et autres catégories prises en charge.</p></div><div class="doc-card"><b>Validation</b><p>Le bot doit voir le salon et pouvoir y envoyer des messages.</p></div></div></section>

<section class="doc-section" id="roles" data-doc="rôles autorole reaction rôle bouton role react hiérarchie">
<h2>Rôles</h2><p>SentriX peut automatiser l’attribution de rôles et proposer des interactions de rôle selon les modules activés.</p><div class="callout warn">SentriX ne peut jamais attribuer ou modifier un rôle placé au-dessus de son propre rôle Discord.</div></section>

<section class="doc-section" id="welcome" data-doc="bienvenue départ welcome goodbye image embed message nouveau membre">
<h2>Bienvenue & départs</h2><p>Configurez les messages d’arrivée et de départ, leur salon et leur présentation. Testez le rendu avant de l’activer pour tous les membres.</p></section>

<section class="doc-section" id="levels" data-doc="niveaux xp level leaderboard récompenses rôles progression">
<h2>Niveaux</h2><p>Le système de niveaux suit la progression communautaire lorsque le module est activé.</p><div class="doc-grid"><div class="doc-card"><b>XP</b><p>La progression dépend des règles actives sur le serveur.</p></div><div class="doc-card"><b>Classements</b><p>Les membres peuvent comparer leur progression via les surfaces prévues.</p></div><div class="doc-card"><b>Récompenses</b><p>Des rôles ou avantages peuvent être liés à certains niveaux.</p></div><div class="doc-card"><b>Désactivation</b><p>Désactiver un système ne doit pas supprimer arbitrairement les données persistantes prévues.</p></div></div></section>

<section class="doc-section" id="economy" data-doc="économie argent monnaie banque boutique daily weekly work deposit withdraw stock promo">
<h2>Économie</h2><p>Le module économie peut gérer monnaie, portefeuille, banque, récompenses, boutique de rôles et activités.</p>
<div class="doc-grid"><div class="doc-card"><b>Monnaie</b><p>Nom, pluriel et symbole sont configurables.</p></div><div class="doc-card"><b>Banque</b><p>Dépôt et retrait utilisent les règles du serveur.</p></div><div class="doc-card"><b>Boutique</b><p>Prix, stock, promotions et rôles peuvent être configurés.</p></div><div class="doc-card"><b>Anti-abus</b><p>Les systèmes automatiques doivent limiter les abus sans bloquer l’usage normal.</p></div></div></section>

<section class="doc-section" id="games" data-doc="jeux coinflip bomb lava rocket crown duel memory dungeon treasure boost">
<h2>Jeux</h2><p>SentriX inclut plusieurs activités communautaires reliées aux systèmes de progression ou d’économie lorsqu’ils sont configurés.</p><div class="callout">Les jeux disponibles peuvent évoluer. La page Commandes reste la source publique la plus précise pour les noms et paramètres exposés.</div></section>

<section class="doc-section" id="music" data-doc="musique vocal playlist play pause queue playlist join leave youtube">
<h2>Musique</h2><p>Le module musique peut rejoindre un salon vocal, gérer une file et travailler avec des playlists selon les fournisseurs actifs.</p>
<div class="steps"><div class="step"><i>01</i><div><b>Rejoindre le vocal</b><span>Le bot doit avoir Connect et Speak dans le salon.</span></div></div><div class="step"><i>02</i><div><b>Lancer une recherche ou une source</b><span>Certaines recherches réseau prennent plusieurs secondes.</span></div></div><div class="step"><i>03</i><div><b>Gérer la file</b><span>Utilisez les commandes exposées ou le module dashboard lorsqu’il est disponible.</span></div></div></div></section>

<section class="doc-section" id="notifications" data-doc="notifications youtube tiktok twitch ping rôle source">
<h2>Notifications</h2><p>Les intégrations de notification publient les nouvelles activités des sources configurées, dans les salons et avec les mentions autorisées.</p></section>

<section class="doc-section" id="automation" data-doc="automatisation auto reaction starboard sticky message programmé vocal temporaire voicehub">
<h2>Automatisations</h2><p>Les automatisations réduisent les tâches répétitives du staff.</p>
<div class="doc-grid"><div class="doc-card"><b>Réactions automatiques</b><p>Ajout d’emojis selon des mots-clés ou règles.</p></div><div class="doc-card"><b>Starboard</b><p>Mise en avant des messages selon les réactions.</p></div><div class="doc-card"><b>Messages programmés / sticky</b><p>Publication planifiée ou maintien d’un message important.</p></div><div class="doc-card"><b>Vocaux temporaires</b><p>Création et gestion de salons vocaux liés à un hub.</p></div></div></section>

<section class="doc-section" id="ai" data-doc="ia assistant langage naturel sentrix ban ouvre setup configure logs image">
<h2>IA & langage naturel</h2><p>L’assistant SentriX peut comprendre certaines demandes naturelles et les relier à des actions ou à la documentation. Les permissions restent obligatoires.</p>
<div class="doc-grid"><div class="doc-card"><b>Action staff</b><p>Une demande comme une sanction doit vérifier les permissions avant exécution.</p></div><div class="doc-card"><b>Navigation</b><p>L’assistant peut orienter vers setup, help, dashboard ou une section de configuration.</p></div><div class="doc-card"><b>Configuration</b><p>Les actions sensibles doivent rester explicites et vérifiables.</p></div><div class="doc-card"><b>Limites</b><p>L’IA ne doit pas inventer une commande ou contourner les règles Discord.</p></div></div></section>

<section class="doc-section" id="troubleshooting" data-doc="dépannage erreur permission commande introuvable dashboard oauth 403 logs bot offline">
<h2>Dépannage</h2><p>Commencez toujours par identifier si le problème vient de Discord, du dashboard, d’une permission ou du bot.</p>
<div class="steps"><div class="step"><i>A</i><div><b>Commande refusée</b><span>Vérifiez votre permission Discord et la hiérarchie des rôles.</span></div></div><div class="step"><i>B</i><div><b>Log absent</b><span>Vérifiez que SentriX voit le salon et peut y écrire.</span></div></div><div class="step"><i>C</i><div><b>Dashboard inaccessible</b><span>Reconnectez-vous avec Discord et vérifiez que vous administrez le serveur.</span></div></div><div class="step"><i>D</i><div><b>Commande introuvable</b><span>Consultez /commands : une ancienne commande peut avoir été renommée ou retirée.</span></div></div></div>
<div class="anchor-actions"><a class="btn" href="/support">Centre de support</a><a class="btn" href="/commands">Commandes actuelles</a></div></section>

<div class="empty" id="docEmpty">Aucune section ne correspond à cette recherche.</div>
</div></div>
</main>
<footer><div class="wrap foot"><span>Documentation publique SentriX</span><span><a href="/">Accueil</a> · <a href="/commands">Commandes</a> · <a href="/support">Support</a> · <a href="/privacy">Confidentialité</a></span></div></footer>
<script>
(()=>{
"use strict";
const input=document.getElementById("docSearch"),sections=Array.from(document.querySelectorAll(".doc-section")),links=Array.from(document.querySelectorAll(".side-link")),empty=document.getElementById("docEmpty");
const reduced=matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
if(!reduced&&"IntersectionObserver" in window){const reveal=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add("enter");reveal.unobserve(entry.target)}}),{threshold:.12,rootMargin:"0px 0px -8% 0px"});sections.forEach(section=>reveal.observe(section))}
if(!reduced){sections.forEach(section=>{section.addEventListener("pointermove",e=>{if(e.pointerType==="touch")return;const r=section.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;section.style.transform="perspective(1200px) rotateX("+(-y*1.5)+"deg) rotateY("+(x*1.5)+"deg)"});section.addEventListener("pointerleave",()=>{section.style.transform=""})})}

function norm(v){return(v||"").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"")}
function filter(){const q=norm(input.value).trim();let shown=0;sections.forEach(section=>{const text=norm(section.dataset.doc+" "+section.textContent),on=!q||text.includes(q);section.hidden=!on;if(on)shown++});empty.style.display=shown?"none":"block"}
input.addEventListener("input",filter);
links.forEach(link=>link.addEventListener("click",()=>{links.forEach(x=>x.classList.remove("active"));link.classList.add("active")}));
if("IntersectionObserver" in window){const io=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){const id=entry.target.id;links.forEach(x=>x.classList.toggle("active",x.getAttribute("href")==="#"+id))}}),{rootMargin:"-20% 0px -70% 0px"});sections.forEach(s=>io.observe(s))}
})();
</script>
</body>
</html>'''


def render(request, dashboard) -> str:
    base = str(dashboard._public_url(request)).rstrip("/")
    return PAGE.replace("__CANONICAL__", html.escape(base + "/docs", quote=True))
