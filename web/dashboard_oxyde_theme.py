"""Thème visuel OXYDE/premium du dashboard SentriX.

Couche purement visuelle : aucune route API, permission, sauvegarde ou donnée Discord n'est
modifiée. Le thème s'applique au dashboard principal et au centre de contrôle existant.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.oxyde-theme")
_INSTALLED = False


OXYDE_CSS = r"""
<style id="sentrix-dashboard-oxyde-css">
  :root{
    --sx-bg:#06050a;
    --sx-bg-2:#0a0810;
    --sx-panel:rgba(15,12,24,.88);
    --sx-panel-2:rgba(20,16,31,.94);
    --sx-line:rgba(153,121,255,.17);
    --sx-line-strong:rgba(153,121,255,.36);
    --sx-purple:#8c6cff;
    --sx-purple-2:#6e4cff;
    --sx-purple-soft:#b7a6ff;
    --sx-text:#f7f5ff;
    --sx-muted:#9b96ab;
    --sx-good:#66e3a4;
    --sx-radius:18px;
    --sx-shadow:0 20px 65px rgba(0,0,0,.42);
  }

  html{background:var(--sx-bg)!important}
  body{
    color:var(--sx-text)!important;
    background:
      radial-gradient(900px 520px at 52% -140px,rgba(119,77,255,.22),transparent 66%),
      radial-gradient(650px 420px at 96% 14%,rgba(109,70,231,.08),transparent 72%),
      linear-gradient(180deg,#07060b 0%,#050409 100%)!important;
    min-height:100vh;
  }
  body::before{
    content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;
    background-image:linear-gradient(rgba(255,255,255,.012) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.012) 1px,transparent 1px);
    background-size:48px 48px;
    mask-image:linear-gradient(to bottom,rgba(0,0,0,.55),transparent 82%);
  }

  /* Conteneurs principaux */
  header,.topbar,.sidebar,.panel,.metric,.field,.card,.sentrix-control-card,
  .sentrix-control-stat,.ticket-ping-card{
    backdrop-filter:blur(18px);
    -webkit-backdrop-filter:blur(18px);
  }
  .panel,.metric,.field,.card,.ticket-ping-card,.sentrix-control-stat{
    background:linear-gradient(145deg,rgba(19,15,30,.94),rgba(10,8,16,.96))!important;
    border:1px solid var(--sx-line)!important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.025)!important;
  }
  .panel,.card{border-radius:var(--sx-radius)!important;box-shadow:var(--sx-shadow)!important}
  .metric,.field,.ticket-ping-card,.sentrix-control-stat{border-radius:14px!important}

  /* Sidebar / navigation */
  #navigation{
    gap:5px!important;
    padding:7px!important;
    border:1px solid rgba(255,255,255,.045)!important;
    border-radius:17px!important;
    background:rgba(7,6,11,.72)!important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.025)!important;
  }
  #navigation button{
    position:relative;
    min-height:39px!important;
    padding:9px 11px!important;
    border:1px solid transparent!important;
    border-radius:11px!important;
    color:#a9a4b5!important;
    background:transparent!important;
    font-weight:650!important;
    transition:background .16s ease,border-color .16s ease,color .16s ease,transform .16s ease!important;
  }
  #navigation button:hover{
    color:#eeeaff!important;
    background:rgba(140,108,255,.085)!important;
    border-color:rgba(140,108,255,.14)!important;
    transform:translateX(1px);
  }
  #navigation button.active{
    color:#fff!important;
    background:linear-gradient(135deg,rgba(139,104,255,.28),rgba(101,67,219,.18))!important;
    border-color:rgba(155,126,255,.33)!important;
    box-shadow:0 8px 24px rgba(84,50,180,.16),inset 3px 0 0 var(--sx-purple)!important;
  }
  .sentrix-nav-search{
    background:#09070e!important;
    border:1px solid rgba(255,255,255,.07)!important;
    border-radius:12px!important;
    color:var(--sx-text)!important;
  }
  .sentrix-nav-search:focus{
    border-color:rgba(140,108,255,.58)!important;
    box-shadow:0 0 0 3px rgba(140,108,255,.12)!important;
  }

  /* Inputs */
  input,select,textarea,.select{
    color:var(--sx-text)!important;
    background:#09070f!important;
    border:1px solid rgba(255,255,255,.08)!important;
    border-radius:11px!important;
    outline:none!important;
    transition:border-color .16s ease,box-shadow .16s ease,background .16s ease!important;
  }
  input:focus,select:focus,textarea:focus,.select:focus{
    background:#0c0914!important;
    border-color:rgba(140,108,255,.63)!important;
    box-shadow:0 0 0 3px rgba(140,108,255,.11)!important;
  }
  label{color:#ddd8eb!important;font-weight:650!important}
  .hint,small,.muted{color:var(--sx-muted)!important}

  /* Boutons */
  .btn,button.btn{
    border-radius:11px!important;
    border:1px solid rgba(255,255,255,.075)!important;
    background:linear-gradient(180deg,#17131f,#100d16)!important;
    color:#ded9e9!important;
    font-weight:700!important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.035)!important;
    transition:transform .14s ease,border-color .14s ease,box-shadow .14s ease,filter .14s ease!important;
  }
  .btn:hover,button.btn:hover{
    transform:translateY(-1px);
    border-color:rgba(140,108,255,.36)!important;
    box-shadow:0 10px 28px rgba(0,0,0,.3)!important;
  }
  .btn.primary,button.btn.primary{
    color:white!important;
    background:linear-gradient(135deg,#8b68ff 0%,#6648df 100%)!important;
    border-color:rgba(177,154,255,.48)!important;
    box-shadow:0 9px 28px rgba(108,73,232,.22),inset 0 1px 0 rgba(255,255,255,.17)!important;
  }
  .btn.primary:hover,button.btn.primary:hover{filter:brightness(1.08)}

  /* Titres et métriques */
  #tabTitle,h1,h2,h3{letter-spacing:-.025em;color:#faf8ff!important}
  #tabDescription{color:#9993a7!important;line-height:1.6!important}
  .overview{gap:11px!important}
  .metric{padding:15px 16px!important}
  .metric small,.sentrix-control-stat small{font-size:11px!important;text-transform:uppercase;letter-spacing:.075em;color:#817b8e!important}
  .metric strong,.sentrix-control-stat strong{font-weight:800!important;color:#faf8ff!important;letter-spacing:-.035em}

  /* Centre de contrôle */
  .sentrix-control-grid{gap:11px!important}
  .sentrix-control-card{
    position:relative;overflow:hidden;
    min-height:126px!important;
    padding:17px!important;
    border:1px solid var(--sx-line)!important;
    border-radius:16px!important;
    background:linear-gradient(145deg,rgba(20,16,31,.95),rgba(10,8,16,.98))!important;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.025)!important;
  }
  .sentrix-control-card::before{
    content:"";position:absolute;width:120px;height:120px;right:-52px;top:-58px;border-radius:50%;
    background:radial-gradient(circle,rgba(139,104,255,.15),transparent 68%);pointer-events:none;
  }
  .sentrix-control-card:hover{
    transform:translateY(-2px)!important;
    border-color:rgba(151,120,255,.38)!important;
    box-shadow:0 16px 38px rgba(0,0,0,.36),0 0 28px rgba(108,73,232,.07)!important;
  }
  .sentrix-control-card.primary{
    background:linear-gradient(145deg,rgba(53,37,92,.72),rgba(18,13,31,.97))!important;
    border-color:rgba(151,120,255,.31)!important;
  }
  .sentrix-control-card .icon{
    width:38px;height:38px;display:grid;place-items:center;border-radius:11px;
    background:rgba(140,108,255,.105);border:1px solid rgba(140,108,255,.13);
    font-size:19px!important;
  }
  .sentrix-control-card b{font-size:14px!important;color:#f7f4ff!important}
  .sentrix-control-card span:not(.icon){color:#938d9f!important;line-height:1.5!important}
  .sentrix-mini-badge{
    color:#c7b9ff!important;background:rgba(140,108,255,.1)!important;
    border-color:rgba(140,108,255,.24)!important;
  }

  /* Barre de sauvegarde */
  #saveBar{
    border:1px solid rgba(140,108,255,.18)!important;
    background:rgba(10,8,16,.91)!important;
    box-shadow:0 -8px 34px rgba(0,0,0,.28)!important;
    backdrop-filter:blur(18px);
  }

  /* Hero OXYDE */
  #sentrixOxydeHero{
    position:relative;overflow:hidden;
    margin:0 0 15px;padding:22px 24px 20px;
    border:1px solid rgba(147,115,255,.2);
    border-radius:20px;
    background:
      radial-gradient(500px 170px at 50% -75px,rgba(137,94,255,.24),transparent 73%),
      linear-gradient(145deg,rgba(17,13,27,.95),rgba(8,6,13,.98));
    box-shadow:0 22px 70px rgba(0,0,0,.34),inset 0 1px 0 rgba(255,255,255,.035);
  }
  #sentrixOxydeHero::after{
    content:"";position:absolute;inset:0;pointer-events:none;
    background:linear-gradient(115deg,transparent 20%,rgba(255,255,255,.025) 48%,transparent 72%);
  }
  .sx-hero-brand{display:flex;align-items:center;justify-content:center;gap:13px;margin-bottom:14px}
  .sx-hero-line{height:1px;width:min(150px,22vw);background:linear-gradient(90deg,transparent,var(--sx-purple))}
  .sx-hero-line.right{background:linear-gradient(90deg,var(--sx-purple),transparent)}
  .sx-hero-logo{
    width:48px;height:48px;border-radius:15px;display:grid;place-items:center;
    font-size:22px;font-weight:950;letter-spacing:-.06em;color:white;
    background:linear-gradient(145deg,#9879ff,#6444da);
    border:1px solid rgba(220,210,255,.32);
    box-shadow:0 0 34px rgba(124,82,255,.32),inset 0 1px 0 rgba(255,255,255,.22);
  }
  .sx-hero-copy{text-align:center;position:relative;z-index:1}
  .sx-hero-kicker{font-size:10px;font-weight:900;letter-spacing:.22em;color:#9b8ec3;margin-bottom:6px}
  .sx-hero-title{font-size:23px;font-weight:900;letter-spacing:-.045em;color:white}
  .sx-hero-title span{color:#ab94ff}
  .sx-hero-sub{margin-top:6px;color:#8e879a;font-size:12px}
  .sx-online{display:inline-flex;align-items:center;gap:5px;color:#a8a2b2}
  .sx-online::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--sx-good);box-shadow:0 0 10px rgba(102,227,164,.55)}

  /* Scrollbars */
  *{scrollbar-width:thin;scrollbar-color:#33264f #09070e}
  *::-webkit-scrollbar{width:8px;height:8px}
  *::-webkit-scrollbar-track{background:#09070e}
  *::-webkit-scrollbar-thumb{background:#33264f;border-radius:999px;border:2px solid #09070e}

  @media(max-width:760px){
    #sentrixOxydeHero{padding:18px 14px 17px;border-radius:16px}
    .sx-hero-logo{width:42px;height:42px;border-radius:13px}
    .sx-hero-title{font-size:20px}
    .sx-hero-line{width:17vw}
    .sentrix-control-card{min-height:108px!important}
    #navigation{overflow-x:auto;display:flex!important;flex-wrap:nowrap!important;padding:6px!important}
    #navigation button{white-space:nowrap;min-width:max-content}
  }

  @media(prefers-reduced-motion:reduce){
    *,*::before,*::after{scroll-behavior:auto!important;transition:none!important;animation:none!important}
  }
</style>
"""


OXYDE_JS = r"""
<script id="sentrix-dashboard-oxyde-js">
(() => {
  "use strict";
  if (window.__sentrixOxydeDashboardTheme) return;
  window.__sentrixOxydeDashboardTheme = true;

  function guildName(){
    try {
      return state?.guildData?.guild?.name || "Control Center";
    } catch (_) {
      return "Control Center";
    }
  }

  function ensureHero(){
    const content = document.getElementById("serverContent");
    if (!content) return;
    let hero = document.getElementById("sentrixOxydeHero");
    if (!hero) {
      hero = document.createElement("section");
      hero.id = "sentrixOxydeHero";
      hero.innerHTML = `
        <div class="sx-hero-brand">
          <span class="sx-hero-line"></span>
          <div class="sx-hero-logo">S</div>
          <span class="sx-hero-line right"></span>
        </div>
        <div class="sx-hero-copy">
          <div class="sx-hero-kicker">SENTRIX • DASHBOARD</div>
          <div class="sx-hero-title">Centre de contrôle <span>premium</span></div>
          <div class="sx-hero-sub"><span class="sx-online">En ligne</span> &nbsp;•&nbsp; <span data-sx-guild></span></div>
        </div>`;
      content.insertBefore(hero, content.firstChild);
    }
    const guild = hero.querySelector("[data-sx-guild]");
    if (guild) guild.textContent = guildName();
  }

  // Plusieurs couches du dashboard reconstruisent #serverContent lors d'un changement de
  // serveur/onglet. L'observer remet uniquement le hero s'il a réellement disparu.
  const observer = new MutationObserver(() => ensureHero());
  const start = () => {
    ensureHero();
    if (document.body) observer.observe(document.body,{childList:true,subtree:true});
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();

  window.addEventListener("pageshow",ensureHero);
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    html = dashboard.INDEX_HTML
    if 'id="sentrix-dashboard-oxyde-css"' not in html:
        html = html.replace("</head>", OXYDE_CSS + "\n</head>", 1)
    if 'id="sentrix-dashboard-oxyde-js"' not in html:
        html = html.replace("</body>", OXYDE_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html

    _INSTALLED = True
    logger.info("Thème OXYDE premium du dashboard SentriX chargé.")
