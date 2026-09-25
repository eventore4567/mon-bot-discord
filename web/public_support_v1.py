"""Page support publique SentriX — expérience interactive premium."""
from __future__ import annotations

import html


PAGE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#06070b">
<title>Support SentriX — Centre d’aide Discord</title>
<meta name="description" content="Centre d’aide SentriX : diagnostic, permissions, dashboard, commandes et accès au support officiel.">
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
.diagnose{display:grid;grid-template-columns:300px 1fr;gap:18px;margin-top:36px}.diag-menu{display:grid;gap:8px}.diag-btn{text-align:left;padding:14px;border:1px solid var(--line);border-radius:12px;background:#0c1118;color:var(--muted);cursor:pointer;transition:.18s ease}.diag-btn b{display:block;color:var(--soft);font-size:11px}.diag-btn span{display:block;margin-top:3px;font-size:9px}.diag-btn.active{border-color:rgba(124,108,255,.5);background:rgba(124,108,255,.12);box-shadow:inset 3px 0 0 var(--violet)}
.diag-panel{position:relative;overflow:hidden;min-height:330px;padding:25px;border:1px solid var(--line);border-radius:19px;background:linear-gradient(145deg,#101720,#090e14)}.diag-panel:before{content:"";position:absolute;inset:-30%;background:conic-gradient(from 180deg,transparent,rgba(124,108,255,.05),transparent 32%);animation:diagGlow 8s linear infinite}.diag-content{position:relative}.diag-content h3{margin:0 0 8px;font-size:22px}.diag-content p{color:var(--muted);line-height:1.68}.checklist{display:grid;gap:8px;margin-top:18px}.check{display:flex;gap:9px;align-items:flex-start;padding:10px;border:1px solid var(--line);border-radius:10px;background:#080d13;color:var(--soft);font-size:11px}.check i{width:19px;height:19px;flex:none;border-radius:6px;background:rgba(89,221,160,.10);display:grid;place-items:center;color:#8de2b7;font-style:normal;font-size:7px;font-weight:950}
.cta{position:relative;overflow:hidden;text-align:center;padding:58px 22px;border:1px solid rgba(124,108,255,.22);border-radius:24px;background:linear-gradient(145deg,rgba(124,108,255,.13),rgba(13,18,26,.94));box-shadow:0 35px 100px rgba(0,0,0,.4)}.cta:before{content:"";position:absolute;left:50%;top:-220px;width:620px;height:480px;transform:translateX(-50%);border-radius:50%;background:radial-gradient(circle,rgba(170,158,255,.22),transparent 66%);animation:breath 6s ease-in-out infinite alternate}.cta>*{position:relative}.cta h2{max-width:730px;margin:8px auto 12px}.cta p{max-width:620px;margin:0 auto;color:var(--muted)}.cta .actions{justify-content:center}
footer{padding:42px 0;color:var(--muted);font-size:11px}footer .wrap{display:flex;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding-top:23px}footer a:hover{color:#fff}
.reveal{opacity:0;transform:translateY(20px);transition:opacity .6s ease,transform .6s ease}.reveal.visible{opacity:1;transform:none}
@keyframes breath{to{transform:translateX(-50%) scale(1.08);opacity:.72}}@keyframes pulse{50%{transform:scale(1.18);box-shadow:0 0 26px rgba(89,221,160,1)}}@keyframes spin{to{transform:rotate(360deg)}}@keyframes float{50%{transform:rotateY(-3deg) rotateX(1deg) translateY(-9px)}}@keyframes typing{50%{transform:translateY(-4px);opacity:.45}}@keyframes diagGlow{to{transform:rotate(360deg)}}
@media(max-width:900px){.links{display:none}.hero{grid-template-columns:1fr}.support-visual{width:min(680px,100%);margin:0 auto}.diagnose{grid-template-columns:1fr}.diag-menu{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){.wrap{width:min(calc(100% - 28px),1180px)}.hero{padding-top:48px}.hero h1{font-size:clamp(42px,13vw,58px)}.hero p{font-size:15px}.support-visual{min-height:340px}.support-console{inset:5px;transform:none;animation:none}.orb{display:none}.cards{grid-template-columns:1fr}.diag-menu{grid-template-columns:1fr}.actions .btn{width:100%}footer .wrap{display:block}footer span{display:block;margin-top:6px}}
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
  function tilt(el,e,max){const r=el.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;el.style.setProperty("--cx",((x+.5)*100)+"%");el.style.setProperty("--cy",((y+.5)*100)+"%");el.style.transform="perspective(900px) rotateX("+(-y*max)+"deg) rotateY("+(x*max)+"deg) translateY(-2px)"}
  $$(".support-card").forEach(el=>{el.addEventListener("pointermove",e=>tilt(el,e,7));el.addEventListener("pointerleave",()=>el.style.transform="")});
  const visual=$("#supportVisual");visual?.addEventListener("pointermove",e=>{const r=visual.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;visual.style.transform="perspective(1200px) rotateX("+(-y*3)+"deg) rotateY("+(x*3)+"deg)"});visual?.addEventListener("pointerleave",()=>visual.style.transform="");
}
const reveals=$$(".reveal");if(!reduced&&"IntersectionObserver" in window){const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("visible");io.unobserve(e.target)}}),{threshold:.12});reveals.forEach(x=>io.observe(x))}else reveals.forEach(x=>x.classList.add("visible"));

const data={
 commands:{title:"Commande Discord",text:"Commencez par vérifier le nom réel de la commande et les permissions requises.",items:["Testez la commande dans un salon où SentriX peut lire et répondre.","Vérifiez que votre rôle possède les permissions staff nécessaires si la commande est administrative.","Copiez le message de refus ou d’erreur exact au lieu de seulement dire “ça ne marche pas”."]},
 dashboard:{title:"Dashboard",text:"Le dashboard dépend de votre session Discord et de vos permissions sur le serveur.",items:["Reconnectez-vous à Discord si votre session a expiré.","Confirmez que vous administrez bien le serveur sélectionné.","Si une sauvegarde échoue, notez la section exacte et le message affiché."]},
 permissions:{title:"Permissions & hiérarchie",text:"Discord peut bloquer une action même si le bot est en ligne.",items:["Placez le rôle SentriX au-dessus du rôle qu’il doit gérer.","Vérifiez les permissions du salon en plus des permissions globales.","Pour les actions sensibles, contrôlez aussi les permissions du membre qui lance la commande."]},
 security:{title:"AutoMod & sécurité",text:"Une protection dépend toujours de ses règles et du contexte Discord.",items:["Vérifiez que le module est activé sur le bon serveur.","Testez avec un cas contrôlé plutôt que sur de vrais membres.","Fournissez l’événement attendu, l’événement observé et les logs disponibles."]}
};
function render(key){const d=data[key],box=$("#diagContent");if(!d||!box)return;box.innerHTML="<h3>"+d.title+"</h3><p>"+d.text+"</p><div class='checklist'>"+d.items.map((x,i)=>"<div class='check'><i>"+(i+1)+"</i><span>"+x+"</span></div>").join("")+"</div>";box.animate?.([{opacity:.25,transform:"translateY(6px)"},{opacity:1,transform:"none"}],{duration:220,easing:"ease-out"})}
$$(".diag-btn").forEach(btn=>btn.addEventListener("click",()=>{$$(".diag-btn").forEach(x=>x.classList.remove("active"));btn.classList.add("active");render(btn.dataset.key)}));render("commands");
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
