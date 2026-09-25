"""Page support publique SentriX V2 — centre d’assistance intelligent et multi-plateforme."""
from __future__ import annotations

import html


PAGE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#06070b">
<title>Support SentriX — Diagnostic intelligent et centre d’aide</title>
<meta name="description" content="Centre d’aide SentriX avec diagnostic guidé, rapport de support, vérification des permissions, dashboard, commandes et accès au support officiel.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="__CANONICAL__">
<style>
:root{--bg:#06070b;--panel:#0e131b;--panel2:#141b26;--line:#243044;--text:#f7f8fb;--muted:#929eaf;--soft:#cbd3df;--violet:#7c6cff;--violet2:#aa9eff;--blue:#4ca9ff;--cyan:#65d8f0;--green:#59dda0;--amber:#efbd62;--mx:50vw;--my:30vh}
*{box-sizing:border-box}html{scroll-behavior:smooth;background:var(--bg)}body{margin:0;min-height:100vh;overflow-x:hidden;color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;background:radial-gradient(900px 650px at 10% -10%,rgba(124,108,255,.20),transparent 62%),radial-gradient(800px 600px at 90% 0%,rgba(76,169,255,.11),transparent 60%),linear-gradient(180deg,#06070b,#080b11 55%,#06070b);-webkit-font-smoothing:antialiased}
body:before{content:"";position:fixed;inset:0;z-index:-3;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.023) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.023) 1px,transparent 1px);background-size:54px 54px;mask-image:linear-gradient(to bottom,black,transparent 90%)}
body:after{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;background:radial-gradient(520px circle at var(--mx) var(--my),rgba(124,108,255,.13),transparent 64%)}
a{color:inherit;text-decoration:none}button{font:inherit}::selection{background:rgba(124,108,255,.4)}:focus-visible{outline:2px solid var(--violet2);outline-offset:3px}
.fx-dot{position:fixed;z-index:120;width:11px;height:11px;border-radius:50%;pointer-events:none;background:rgba(170,158,255,.26);box-shadow:0 0 35px rgba(124,108,255,.42);transform:translate(-50%,-50%);opacity:0;transition:opacity .18s ease}
.wrap{width:min(1180px,calc(100% - 40px));margin:0 auto}
header{position:sticky;top:0;z-index:100;border-bottom:1px solid rgba(255,255,255,.055);background:rgba(6,7,11,.70);backdrop-filter:blur(20px)}
.nav{height:72px;display:flex;align-items:center;justify-content:space-between;gap:22px}.brand{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:950;letter-spacing:-.03em}.brand img{width:39px;height:39px;border-radius:12px;border:1px solid rgba(255,255,255,.12)}.links{display:flex;gap:6px;align-items:center}.links a{padding:9px 10px;border-radius:9px;color:var(--muted);font-size:12px;font-weight:800}.links a:hover{background:rgba(255,255,255,.05);color:#fff}
.btn{position:relative;display:inline-flex;align-items:center;justify-content:center;min-height:43px;padding:10px 15px;border:1px solid var(--line);border-radius:11px;background:#121924;color:#fff;font-weight:850;font-size:12px;overflow:hidden;transition:.18s ease}.btn:before{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 25%,rgba(255,255,255,.10),transparent 75%);transform:translateX(-130%);transition:.5s ease}.btn:hover{transform:translateY(-2px);border-color:#41516c;box-shadow:0 14px 38px rgba(0,0,0,.25)}.btn:hover:before{transform:translateX(130%)}.btn.primary{border-color:transparent;background:linear-gradient(135deg,#7c6cff,#5d62eb 60%,#4c93f3);box-shadow:0 14px 38px rgba(111,97,247,.28)}
.hero{position:relative;min-height:560px;display:grid;grid-template-columns:.9fr 1.1fr;gap:54px;align-items:center;padding:72px 0 56px}.hero:before{content:"";position:absolute;left:50%;top:-230px;width:900px;height:650px;transform:translateX(-50%);border-radius:50%;background:radial-gradient(circle,rgba(124,108,255,.20),transparent 66%);filter:blur(22px);animation:breath 7s ease-in-out infinite alternate}.hero-copy{position:relative;z-index:3}.badge{display:inline-flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid rgba(170,158,255,.25);border-radius:999px;background:rgba(124,108,255,.08);color:#c9c2ff;font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase}.badge i{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 16px rgba(89,221,160,.8);animation:pulse 1.8s ease-in-out infinite}.hero h1{margin:18px 0;font-size:clamp(45px,6vw,74px);line-height:.97;letter-spacing:-.06em}.hero h1 span{background:linear-gradient(110deg,#fff,#c7c0ff 50%,#77bfff);-webkit-background-clip:text;background-clip:text;color:transparent}.hero p{max-width:650px;margin:0;color:var(--muted);font-size:17px;line-height:1.72}.actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:26px}
.support-visual{position:relative;min-height:420px;perspective:1200px}.orb{position:absolute;inset:50px;border:1px solid rgba(124,108,255,.12);border-radius:50%;animation:spin 20s linear infinite}.orb:before,.orb:after{content:"";position:absolute;width:9px;height:9px;border-radius:50%;background:var(--violet2);box-shadow:0 0 20px rgba(170,158,255,.85)}.orb:before{left:12%;top:18%}.orb:after{right:9%;bottom:20%;background:var(--blue)}
.support-console{position:absolute;inset:20px 20px 20px 26px;padding:20px;border:1px solid rgba(255,255,255,.12);border-radius:22px;background:linear-gradient(145deg,rgba(18,24,35,.97),rgba(8,12,18,.99));box-shadow:0 40px 110px rgba(0,0,0,.56);transform:rotateY(-5deg) rotateX(2deg);animation:float 6s ease-in-out infinite}.console-head{display:flex;align-items:center;justify-content:space-between;padding-bottom:15px;border-bottom:1px solid var(--line)}.console-head b{font-size:13px}.live{display:inline-flex;align-items:center;gap:7px;color:#8de2b7;font-size:8px;font-weight:900}.live i{width:6px;height:6px;border-radius:50%;background:var(--green)}.support-flow{display:grid;gap:10px;margin-top:18px}.flow{display:grid;grid-template-columns:39px 1fr auto;gap:10px;align-items:center;padding:11px;border:1px solid var(--line);border-radius:11px;background:#0a0f16}.flow i{width:36px;height:36px;border-radius:10px;background:rgba(124,108,255,.12);display:grid;place-items:center;color:#c4bdff;font-style:normal;font-size:8px;font-weight:950}.flow b{display:block;font-size:9px}.flow small{display:block;color:var(--muted);font-size:7px}.flow em{font-style:normal;color:#8de2b7;font-size:7px;font-weight:900}.typing{display:flex;gap:5px;margin-top:18px}.typing i{width:6px;height:6px;border-radius:50%;background:var(--violet);animation:typing 1.3s ease-in-out infinite}.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.30s}
.section{padding:92px 0}.section h2{margin:8px 0 0;font-size:clamp(31px,4vw,49px);line-height:1.05;letter-spacing:-.045em}.eyebrow{color:var(--violet2);font-size:10px;font-weight:950;letter-spacing:.11em;text-transform:uppercase}.lead2{max-width:700px;color:var(--muted);line-height:1.72}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:34px}.support-card{--cx:50%;--cy:50%;position:relative;overflow:hidden;min-height:190px;padding:22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#111823,#0b1017);transform-style:preserve-3d;will-change:transform;transition:border-color .18s ease,box-shadow .18s ease,transform .16s ease}.support-card:before{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(240px circle at var(--cx) var(--cy),rgba(124,108,255,.16),transparent 62%);opacity:0;transition:opacity .2s}.support-card:hover{border-color:#3c4a62;box-shadow:0 22px 60px rgba(0,0,0,.28)}.support-card:hover:before{opacity:1}.support-card>*{position:relative;transform:translateZ(20px)}.support-card .icon{width:42px;height:42px;border-radius:12px;border:1px solid var(--line);background:#172030;display:grid;place-items:center;color:#cbc5ff;font-size:9px;font-weight:950}.support-card h3{margin:16px 0 7px}.support-card p{margin:0;color:var(--muted);font-size:12px;line-height:1.65}
.smart-assistant{margin-top:40px;padding:26px;border:1px solid rgba(124,108,255,.23);border-radius:22px;background:radial-gradient(circle at 100% 0,rgba(124,108,255,.10),transparent 34%),linear-gradient(145deg,#101720,#090e14);box-shadow:0 28px 80px rgba(0,0,0,.28)}
.smart-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.smart-head h3{margin:7px 0 6px;font-size:25px;letter-spacing:-.03em}.smart-head p{margin:0;color:var(--muted);max-width:720px}.smart-chip{flex:none;display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid rgba(89,221,160,.20);border-radius:999px;background:rgba(89,221,160,.07);color:#90e3ba;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.08em}.smart-chip i{width:6px;height:6px;border-radius:50%;background:var(--green)}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin-top:22px}.field{display:grid;gap:7px}.field.full{grid-column:1/-1}.field label{font-size:9px;font-weight:900;color:var(--soft);text-transform:uppercase;letter-spacing:.07em}.field input,.field select,.field textarea{width:100%;border:1px solid var(--line);border-radius:10px;background:#070c12;color:#fff;padding:11px 12px;font:inherit;font-size:12px;outline:none;transition:border-color .16s ease,box-shadow .16s ease}.field textarea{min-height:92px;resize:vertical}.field input:focus,.field select:focus,.field textarea:focus{border-color:rgba(124,108,255,.65);box-shadow:0 0 0 3px rgba(124,108,255,.10)}.field small{color:var(--muted);font-size:8px}
.smart-actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:16px}
.smart-output{display:none;margin-top:20px;grid-template-columns:.8fr 1.2fr;gap:12px}.smart-output.show{display:grid;animation:rowIn .35s ease both}.score-card,.report-card{padding:17px;border:1px solid var(--line);border-radius:14px;background:#080d13}.score-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.score-top b{font-size:12px}.severity{padding:5px 8px;border-radius:999px;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.07em}.severity.low{background:rgba(89,221,160,.08);color:#8ce2b8}.severity.medium{background:rgba(239,189,98,.08);color:#f3cc83}.severity.high{background:rgba(255,111,125,.08);color:#ff9ca6}
.reason-list{display:grid;gap:7px;margin-top:13px}.reason{padding:9px;border-radius:9px;background:#0e141d;color:var(--soft);font-size:9px}.reason b{color:#fff}.report-card pre{white-space:pre-wrap;word-break:break-word;margin:11px 0 0;padding:12px;border:1px solid var(--line);border-radius:10px;background:#05090e;color:#cbd3df;font:10px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;max-height:260px;overflow:auto}.copy-note{margin-top:8px;color:var(--muted);font-size:8px}
.device-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:24px}.device{padding:11px;border:1px solid var(--line);border-radius:10px;background:#0a0f16;text-align:center}.device b{display:block;font-size:9px}.device span{display:block;margin-top:2px;color:var(--muted);font-size:7px}
.diagnose{display:grid;grid-template-columns:300px 1fr;gap:18px;margin-top:36px}.diag-menu{display:grid;gap:8px}.diag-btn{text-align:left;padding:14px;border:1px solid var(--line);border-radius:12px;background:#0c1118;color:var(--muted);cursor:pointer;transition:.18s ease}.diag-btn b{display:block;color:var(--soft);font-size:11px}.diag-btn span{display:block;margin-top:3px;font-size:9px}.diag-btn.active{border-color:rgba(124,108,255,.5);background:rgba(124,108,255,.12);box-shadow:inset 3px 0 0 var(--violet)}
.diag-panel{position:relative;overflow:hidden;min-height:330px;padding:25px;border:1px solid var(--line);border-radius:19px;background:linear-gradient(145deg,#101720,#090e14)}.diag-panel:before{content:"";position:absolute;inset:-30%;background:conic-gradient(from 180deg,transparent,rgba(124,108,255,.05),transparent 32%);animation:diagGlow 8s linear infinite}.diag-content{position:relative}.diag-content h3{margin:0 0 8px;font-size:22px}.diag-content p{color:var(--muted);line-height:1.68}.checklist{display:grid;gap:8px;margin-top:18px}.check{display:flex;gap:9px;align-items:flex-start;padding:10px;border:1px solid var(--line);border-radius:10px;background:#080d13;color:var(--soft);font-size:11px}.check i{width:19px;height:19px;flex:none;border-radius:6px;background:rgba(89,221,160,.10);display:grid;place-items:center;color:#8de2b7;font-style:normal;font-size:7px;font-weight:950}
.cta{position:relative;overflow:hidden;text-align:center;padding:58px 22px;border:1px solid rgba(124,108,255,.22);border-radius:24px;background:linear-gradient(145deg,rgba(124,108,255,.13),rgba(13,18,26,.94));box-shadow:0 35px 100px rgba(0,0,0,.4)}.cta:before{content:"";position:absolute;left:50%;top:-220px;width:620px;height:480px;transform:translateX(-50%);border-radius:50%;background:radial-gradient(circle,rgba(170,158,255,.22),transparent 66%);animation:breath 6s ease-in-out infinite alternate}.cta>*{position:relative}.cta h2{max-width:730px;margin:8px auto 12px}.cta p{max-width:620px;margin:0 auto;color:var(--muted)}.cta .actions{justify-content:center}
footer{padding:42px 0;color:var(--muted);font-size:11px}footer .wrap{display:flex;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding-top:23px}footer a:hover{color:#fff}
.reveal{opacity:0;transform:translateY(20px);transition:opacity .6s ease,transform .6s ease}.reveal.visible{opacity:1;transform:none}
@keyframes breath{to{transform:translateX(-50%) scale(1.08);opacity:.72}}@keyframes pulse{50%{transform:scale(1.18);box-shadow:0 0 26px rgba(89,221,160,1)}}@keyframes spin{to{transform:rotate(360deg)}}@keyframes float{50%{transform:rotateY(-3deg) rotateX(1deg) translateY(-9px)}}@keyframes typing{50%{transform:translateY(-4px);opacity:.45}}@keyframes diagGlow{to{transform:rotate(360deg)}}
@media(max-width:1024px){.links{display:none}.hero{grid-template-columns:1fr}.support-visual{width:min(720px,100%);margin:0 auto}.diagnose{grid-template-columns:1fr}.diag-menu{grid-template-columns:repeat(2,1fr)}}
@media(max-width:768px){.cards{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.field.full{grid-column:auto}.smart-output{grid-template-columns:1fr}.device-bar{grid-template-columns:1fr 1fr}.smart-head{display:block}.smart-chip{margin-top:12px}}
@media(max-width:650px){.wrap{width:min(calc(100% - 28px),1180px)}.nav{height:64px}.hero{padding-top:44px;min-height:auto}.hero h1{font-size:clamp(40px,13vw,58px)}.hero p{font-size:15px}.support-visual{min-height:340px}.support-console{inset:5px;transform:none;animation:none}.orb{display:none}.diag-menu{grid-template-columns:1fr}.actions .btn,.smart-actions .btn{width:100%}.smart-assistant{padding:20px}.device-bar{grid-template-columns:1fr 1fr}footer .wrap{display:block}footer span{display:block;margin-top:6px}}
@media(max-width:430px){.wrap{width:min(calc(100% - 22px),1180px)}.hero h1{font-size:39px}.section{padding:70px 0}.section h2{font-size:31px}.support-card{padding:18px}.support-console{padding:15px}.flow{grid-template-columns:34px 1fr}.flow em{display:none}.device-bar{grid-template-columns:1fr}.diag-panel{padding:19px}.smart-assistant{padding:17px}.smart-head h3{font-size:21px}}
@media(max-width:360px){.brand span{font-size:15px}.hero h1{font-size:36px}.badge{font-size:8px}.support-visual{min-height:320px}.section{padding:62px 0}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}body:after,.orb,.support-console,.badge i,.typing i,.diag-panel:before,.cta:before{animation:none!important}.reveal{opacity:1!important;transform:none!important;transition:none!important}.support-card{transform:none!important;transition:none!important}.fx-dot{display:none}}
</style>
</head>
<body>
<div class="fx-dot" id="cursorGlow" aria-hidden="true"></div>
<header><div class="wrap nav"><a class="brand" href="/home"><img src="/sentrix-avatar.png?v=55" alt="" width="39" height="39"><span>SentriX</span></a><nav class="links" aria-label="Navigation support"><a href="/home">Accueil</a><a href="/start">Démarrage</a><a href="/commands">Commandes</a><a href="/stats">Stats</a><a href="/app">Dashboard</a></nav></div></header>

<main>
<section class="wrap hero">
  <div class="hero-copy"><div class="badge"><i></i>Centre d’aide SentriX</div><h1>Un problème ? <span>On commence par le bon diagnostic.</span></h1><p>Permissions, dashboard, commandes, configuration ou comportement inattendu : cette page vous aide à préparer les bonnes informations avant de contacter le support.</p><div class="actions">__SUPPORT_BUTTON__<a class="btn" href="/start">Guide de démarrage</a><a class="btn" href="/app">Ouvrir le dashboard</a></div></div>
  <div class="support-visual" id="supportVisual"><div class="orb"></div><div class="support-console"><div class="console-head"><b>SentriX · Support Console</b><span class="live"><i></i>Prêt</span></div><div class="support-flow"><div class="flow"><i>01</i><div><b>Identifier</b><small>Quelle fonction pose problème ?</small></div><em>Contexte</em></div><div class="flow"><i>02</i><div><b>Vérifier</b><small>Permissions, hiérarchie et configuration.</small></div><em>Diagnostic</em></div><div class="flow"><i>03</i><div><b>Transmettre</b><small>Erreur exacte, sans aucun secret.</small></div><em>Support</em></div></div><div class="typing"><i></i><i></i><i></i></div></div></div>
</section>

<section class="wrap section">
  <span class="eyebrow">Avant d’ouvrir un ticket</span><h2>Les quatre vérifications qui font gagner du temps.</h2><p class="lead2">Une grande partie des problèmes Discord viennent d’une permission, d’une hiérarchie de rôle ou d’un réglage du serveur. Ces vérifications évitent les allers-retours inutiles.</p>
  <div class="cards">
    <article class="support-card reveal"><div class="icon">PR</div><h3>Permissions</h3><p>Vérifiez que SentriX possède les permissions requises dans le salon concerné et que son rôle est suffisamment haut dans la hiérarchie.</p></article>
    <article class="support-card reveal"><div class="icon">DB</div><h3>Dashboard</h3><p>Confirmez que vous avez sélectionné le bon serveur et que le module concerné est activé avec les bons salons et rôles.</p></article>
    <article class="support-card reveal"><div class="icon">ER</div><h3>Erreur exacte</h3><p>Copiez le message d’erreur ou décrivez précisément le résultat obtenu et le résultat attendu. Évitez les descriptions vagues.</p></article>
    <article class="support-card reveal"><div class="icon">SC</div><h3>Aucun secret</h3><p>Ne partagez jamais token Discord, secret OAuth, clé API, cookie de session ou mot de passe, même dans un ticket privé.</p></article>
  </div>
</section>

<section class="wrap section">
  <span class="eyebrow">Diagnostic interactif</span><h2>Choisissez ce qui ne fonctionne pas.</h2><p class="lead2">Le panneau change selon votre problème pour vous indiquer les vérifications les plus utiles.</p>
  <div class="diagnose reveal">
    <div class="diag-menu">
      <button class="diag-btn active" type="button" data-key="commands"><b>Commande Discord</b><span>Une commande ne répond pas ou refuse l’action.</span></button>
      <button class="diag-btn" type="button" data-key="dashboard"><b>Dashboard</b><span>Connexion, serveur ou sauvegarde.</span></button>
      <button class="diag-btn" type="button" data-key="permissions"><b>Permissions</b><span>SentriX ne peut pas agir.</span></button>
      <button class="diag-btn" type="button" data-key="security"><b>AutoMod / sécurité</b><span>Une protection ne se déclenche pas comme prévu.</span></button>
    </div>
    <div class="diag-panel"><div class="diag-content" id="diagContent"></div></div>
  </div>

  <div class="smart-assistant reveal" id="smartAssistant">
    <div class="smart-head"><div><span class="eyebrow">Assistant de diagnostic</span><h3>Préparez un rapport propre avant de contacter le staff.</h3><p>L’assistant analyse localement les informations saisies et propose les vérifications les plus pertinentes. Rien n’est envoyé automatiquement.</p></div><span class="smart-chip"><i></i>Analyse locale</span></div>
    <div class="form-grid">
      <div class="field"><label for="issueType">Type de problème</label><select id="issueType"><option value="commands">Commande Discord</option><option value="dashboard">Dashboard / OAuth</option><option value="permissions">Permissions / rôles</option><option value="security">AutoMod / sécurité</option><option value="tickets">Tickets</option><option value="economy">Économie / niveaux</option><option value="other">Autre</option></select></div>
      <div class="field"><label for="deviceType">Plateforme</label><select id="deviceType"><option>PC / navigateur desktop</option><option>Téléphone Android</option><option>iPhone / iPad</option><option>Discord desktop</option><option>Discord mobile</option></select></div>
      <div class="field"><label for="serverContext">Contexte</label><input id="serverContext" maxlength="120" placeholder="Ex. serveur test, salon modération…"><small>Pas besoin d’indiquer un ID sensible.</small></div>
      <div class="field"><label for="errorText">Erreur affichée</label><input id="errorText" maxlength="300" placeholder="Copiez le message exact s’il existe"></div>
      <div class="field full"><label for="expectedText">Que deviez-vous obtenir ?</label><textarea id="expectedText" maxlength="700" placeholder="Décrivez le comportement attendu…"></textarea></div>
      <div class="field full"><label for="actualText">Que se passe-t-il réellement ?</label><textarea id="actualText" maxlength="700" placeholder="Décrivez exactement le résultat obtenu…"></textarea></div>
    </div>
    <div class="device-bar"><div class="device"><b>320–430 px</b><span>Téléphones</span></div><div class="device"><b>768 px</b><span>Tablettes</span></div><div class="device"><b>1024–1440 px</b><span>PC / laptop</span></div><div class="device"><b>1920 px+</b><span>Grand écran</span></div></div>
    <div class="smart-actions"><button class="btn primary" id="analyzeBtn" type="button">Analyser le problème</button><button class="btn" id="resetBtn" type="button">Réinitialiser</button></div>
    <div class="smart-output" id="smartOutput"><div class="score-card"><div class="score-top"><b>Diagnostic suggéré</b><span class="severity low" id="severity">Faible</span></div><div class="reason-list" id="reasonList"></div></div><div class="report-card"><b>Rapport prêt à envoyer</b><pre id="reportText"></pre><div class="smart-actions"><button class="btn" id="copyReport" type="button">Copier le rapport</button></div><div class="copy-note" id="copyNote">Vérifiez le contenu avant de l’envoyer. Ne collez jamais de token, secret OAuth, clé API ou cookie.</div></div></div>
  </div>
</section>

<section class="wrap cta reveal"><span class="eyebrow">Support officiel</span><h2>Si le problème reste présent, envoyez un diagnostic propre.</h2><p>Indiquez le serveur concerné, la fonction utilisée, ce que vous attendiez, ce qui s’est produit et le message d’erreur exact. __NOTE__</p><div class="actions">__SUPPORT_BUTTON__<a class="btn" href="/commands">Voir les commandes</a></div></section>
</main>

<footer><div class="wrap"><span>SentriX · centre d’aide officiel</span><span><a href="/privacy">Confidentialité</a> · <a href="/terms">Conditions</a> · <a href="/home">Accueil</a></span></div></footer>

<script>
(()=>{
"use strict";
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>Array.from(r.querySelectorAll(s)),reduced=matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
if(!reduced){
  addEventListener("pointermove",e=>{document.documentElement.style.setProperty("--mx",e.clientX+"px");document.documentElement.style.setProperty("--my",e.clientY+"px");const g=$("#cursorGlow");if(g){g.style.left=e.clientX+"px";g.style.top=e.clientY+"px";g.style.opacity="1"}},{passive:true});
  addEventListener("pointerleave",()=>{const g=$("#cursorGlow");if(g)g.style.opacity="0"});

  const motion=new WeakMap();
  function state(el){let s=motion.get(el);if(!s){s={rx:0,ry:0,tx:0,ty:0,trx:0,try:0,ttx:0,tty:0,raf:0};motion.set(el,s)}return s}
  function animate(el){const s=state(el),k=.14;s.rx+=(s.trx-s.rx)*k;s.ry+=(s.try-s.ry)*k;s.tx+=(s.ttx-s.tx)*k;s.ty+=(s.tty-s.ty)*k;el.style.transform="perspective(1050px) rotateX("+s.rx.toFixed(2)+"deg) rotateY("+s.ry.toFixed(2)+"deg) translate3d("+s.tx.toFixed(1)+"px,"+s.ty.toFixed(1)+"px,0)";el.style.boxShadow=(-s.ry*3).toFixed(1)+"px "+(20+s.rx*1.4).toFixed(1)+"px 62px rgba(0,0,0,.31)";const d=Math.abs(s.trx-s.rx)+Math.abs(s.try-s.ry)+Math.abs(s.ttx-s.tx)+Math.abs(s.tty-s.ty);if(d>.05)s.raf=requestAnimationFrame(()=>animate(el));else{s.raf=0;if(!s.trx&&!s.try&&!s.ttx&&!s.tty){el.style.transform="";el.style.boxShadow=""}}}
  function aim(el,x,y,max,scale=1){const r=el.getBoundingClientRect(),nx=Math.max(0,Math.min(1,(x-r.left)/r.width))-.5,ny=Math.max(0,Math.min(1,(y-r.top)/r.height))-.5,s=state(el);s.trx=-ny*max*scale;s.try=nx*max*scale;s.ttx=nx*12*scale;s.tty=ny*8*scale;el.style.setProperty("--cx",((nx+.5)*100)+"%");el.style.setProperty("--cy",((ny+.5)*100)+"%");if(!s.raf)s.raf=requestAnimationFrame(()=>animate(el))}
  function release(el){const s=state(el);s.trx=s.try=s.ttx=s.tty=0;if(!s.raf)s.raf=requestAnimationFrame(()=>animate(el))}
  $(".support-card,.diag-panel,.smart-assistant,.score-card,.report-card").forEach(el=>{const max=el.classList.contains("support-card")?9:5;el.addEventListener("pointermove",e=>{if(e.pointerType!=="touch")aim(el,e.clientX,e.clientY,max)});el.addEventListener("pointerleave",()=>release(el));el.addEventListener("pointerdown",e=>{if(e.pointerType==="touch"){aim(el,e.clientX,e.clientY,max,.75);setTimeout(()=>release(el),220)}})});
  const visual=$("#supportVisual");visual?.addEventListener("pointermove",e=>{if(e.pointerType!=="touch")aim(visual,e.clientX,e.clientY,4)});visual?.addEventListener("pointerleave",()=>release(visual));visual?.addEventListener("pointerdown",e=>{if(e.pointerType==="touch"){aim(visual,e.clientX,e.clientY,4,.7);setTimeout(()=>release(visual),220)}});
}
const reveals=$$(".reveal");if(!reduced&&"IntersectionObserver" in window){const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("visible");io.unobserve(e.target)}}),{threshold:.12});reveals.forEach(x=>io.observe(x))}else reveals.forEach(x=>x.classList.add("visible"));

const data={
 commands:{title:"Commande Discord",text:"Commencez par vérifier le nom réel de la commande et les permissions requises.",items:["Testez la commande dans un salon où SentriX peut lire et répondre.","Vérifiez que votre rôle possède les permissions staff nécessaires si la commande est administrative.","Copiez le message de refus ou d’erreur exact au lieu de seulement dire “ça ne marche pas”."]},
 dashboard:{title:"Dashboard",text:"Le dashboard dépend de votre session Discord et de vos permissions sur le serveur.",items:["Reconnectez-vous à Discord si votre session a expiré.","Confirmez que vous administrez bien le serveur sélectionné.","Si une sauvegarde échoue, notez la section exacte et le message affiché."]},
 permissions:{title:"Permissions & hiérarchie",text:"Discord peut bloquer une action même si le bot est en ligne.",items:["Placez le rôle SentriX au-dessus du rôle qu’il doit gérer.","Vérifiez les permissions du salon en plus des permissions globales.","Pour les actions sensibles, contrôlez aussi les permissions du membre qui lance la commande."]},
 security:{title:"AutoMod & sécurité",text:"Une protection dépend toujours de ses règles et du contexte Discord.",items:["Vérifiez que le module est activé sur le bon serveur.","Testez avec un cas contrôlé plutôt que sur de vrais membres.","Fournissez l’événement attendu, l’événement observé et les logs disponibles."]}
};
function render(key){const d=data[key],box=$("#diagContent");if(!d||!box)return;box.innerHTML="<h3>"+d.title+"</h3><p>"+d.text+"</p><div class='checklist'>"+d.items.map((x,i)=>"<div class='check'><i>"+(i+1)+"</i><span>"+x+"</span></div>").join("")+"</div>";box.animate?.([{opacity:.25,transform:"translateY(6px)"},{opacity:1,transform:"none"}],{duration:220,easing:"ease-out"})}
$(".diag-btn").forEach(btn=>btn.addEventListener("click",()=>{$(".diag-btn").forEach(x=>x.classList.remove("active"));btn.classList.add("active");render(btn.dataset.key);const sel=$("#issueType");if(sel&&[...sel.options].some(o=>o.value===btn.dataset.key))sel.value=btn.dataset.key}));render("commands");

const rules={
 commands:{base:["Vérifiez que la commande existe dans la page Commandes.","Testez dans un salon où SentriX peut lire et répondre."],keywords:[["unknown","commande inconnue ou nom obsolète"],["missing","permission ou argument manquant"],["forbidden","permission Discord refusée"],["timeout","interaction trop lente ou service momentanément indisponible"]]},
 dashboard:{base:["Actualisez votre session Discord puis réessayez.","Confirmez que le bon serveur est sélectionné."],keywords:[["401","session OAuth expirée ou invalide"],["403","permission refusée"],["csrf","session de sécurité à renouveler"],["network","problème réseau entre le navigateur et le service"]]},
 permissions:{base:["Vérifiez la hiérarchie du rôle SentriX.","Contrôlez les permissions globales ET celles du salon."],keywords:[["403","Discord refuse probablement l’action"],["hierarchy","le rôle cible peut être au-dessus de SentriX"],["permission","une permission nécessaire manque"]]},
 security:{base:["Confirmez que le module est activé sur le bon serveur.","Testez avec un cas contrôlé et consultez les logs."],keywords:[["spam","vérifiez seuils, cooldowns et exclusions"],["raid","vérifiez les protections et permissions d’action"],["role","vérifiez la hiérarchie des rôles"],["channel","vérifiez les permissions du salon"]]},
 tickets:{base:["Vérifiez la configuration des salons et rôles staff.","Contrôlez les permissions de création et d’accès aux salons."],keywords:[["channel","salon de ticket ou catégorie inaccessible"],["permission","rôle staff ou bot sans accès suffisant"]]},
 economy:{base:["Vérifiez le solde, les cooldowns et les règles du serveur.","Reproduisez l’action une seule fois et notez le résultat exact."],keywords:[["balance","solde insuffisant ou réservation en cours"],["cooldown","action temporairement limitée"],["duplicate","évitez les doubles clics et signalez toute duplication"]]},
 other:{base:["Décrivez précisément les étapes de reproduction.","Ajoutez le résultat attendu et le résultat réellement obtenu."],keywords:[]}
};
function escReport(s){return String(s||"").replace(/\r/g,"").trim()}
function analyze(){
  const type=$("#issueType")?.value||"other",device=$("#deviceType")?.value||"Non précisé",ctx=escReport($("#serverContext")?.value),err=escReport($("#errorText")?.value),expected=escReport($("#expectedText")?.value),actual=escReport($("#actualText")?.value),rule=rules[type]||rules.other,hay=(err+" "+actual).toLowerCase();
  const reasons=[...rule.base];let matches=0;
  for(const [needle,msg] of rule.keywords){if(hay.includes(needle)){reasons.push("Indice détecté : "+msg+".");matches++}}
  if(!err)reasons.push("Ajoutez le message d’erreur exact s’il existe.");
  if(!expected||!actual)reasons.push("Complétez résultat attendu et résultat observé pour un diagnostic plus précis.");
  let sev="low",sevText="Faible";if(matches>=2||/token|secret|password|mot de passe|cookie/i.test(hay)){sev="high";sevText="Prioritaire"}else if(matches===1||err){sev="medium";sevText="À vérifier"}
  const severity=$("#severity");severity.className="severity "+sev;severity.textContent=sevText;
  $("#reasonList").innerHTML=reasons.map((x,i)=>"<div class='reason'><b>"+(i+1)+".</b> "+x+"</div>").join("");
  const labels={commands:"Commande Discord",dashboard:"Dashboard / OAuth",permissions:"Permissions / rôles",security:"AutoMod / sécurité",tickets:"Tickets",economy:"Économie / niveaux",other:"Autre"};
  const report=["Rapport support SentriX","Type : "+(labels[type]||type),"Plateforme : "+device,"Contexte : "+(ctx||"Non précisé"),"Erreur : "+(err||"Aucune erreur affichée"),"Résultat attendu : "+(expected||"Non précisé"),"Résultat observé : "+(actual||"Non précisé"),"","Vérifications suggérées :",...reasons.map((x,i)=>(i+1)+". "+x)].join("\n");
  $("#reportText").textContent=report;$("#smartOutput").classList.add("show");$("#smartOutput").scrollIntoView({behavior:reduced?"auto":"smooth",block:"nearest"});
}
$("#analyzeBtn")?.addEventListener("click",analyze);
$("#resetBtn")?.addEventListener("click",()=>{$("#smartAssistant input,#smartAssistant textarea").forEach(x=>x.value="");$("#issueType").value="commands";$("#deviceType").selectedIndex=0;$("#smartOutput").classList.remove("show");$("#copyNote").textContent="Vérifiez le contenu avant de l’envoyer. Ne collez jamais de token, secret OAuth, clé API ou cookie."});
$("#copyReport")?.addEventListener("click",async()=>{const text=$("#reportText")?.textContent||"";try{await navigator.clipboard.writeText(text);$("#copyNote").textContent="Rapport copié. Relisez-le avant de l’envoyer au support."}catch(_){$("#copyNote").textContent="Copie automatique indisponible : sélectionnez le rapport manuellement."}});

})();
</script>
</body>
</html>'''


def render(request, dashboard, support_url: str) -> str:
    base = str(dashboard._public_url(request)).rstrip("/")
    canonical = base + "/support"
    if support_url:
        button = (
            '<a class="btn primary" href="'
            + html.escape(support_url, quote=True)
            + '" target="_blank" rel="noopener">Rejoindre le serveur support</a>'
        )
        note = "Le serveur support officiel est accessible avec le bouton ci-dessus."
    else:
        button = '<a class="btn primary" href="/app">Ouvrir le dashboard</a>'
        note = "Le lien public du serveur support n’est pas encore configuré."
    return (
        PAGE.replace("__CANONICAL__", html.escape(canonical, quote=True))
        .replace("__SUPPORT_BUTTON__", button)
        .replace("__NOTE__", html.escape(note))
    )
