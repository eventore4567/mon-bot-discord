"""Browser-visible CAPTCHA guard for the unified SentriX dashboard.

Historique : V13 rendait persistants les boutons de navigation injectés par Growth V12 et
relançait le renderer de V12 (``ensureCurrent``) dès que ``#content`` ne contenait pas de
``.sx12-page`` — sur chaque mutation du DOM et toutes les 650 ms. Depuis V15
(``dashboard_live_response_v15``), ces 9 pages sont rendues nativement par le routeur V2 :
le rendu V15 ne contient jamais ``.sx12-page``, donc V13 l'écrasait par un skeleton V12,
relançait deux fetch par cycle et, si une requête V12 était lente, laissait le skeleton
affiché indéfiniment. Mesuré en navigateur réel : un seul clic sur « Statistiques »
produisait 6 écritures dans ``#content`` et 5 fetch. Ce mécanisme est retiré ; il ne reste
que la mise en évidence du vrai contrôle CAPTCHA V96 sur la page Vérification, sans rapport.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-visibility-v13")

CSS_MARKER = "sentrix-dashboard-visibility-v13-css"
JS_MARKER = "sentrix-dashboard-visibility-v13-js"
API_MARKER = "__sentrixGrowthV12Api"

CSS = r'''
<style id="sentrix-dashboard-visibility-v13-css">
  .sx13-nav .nav-icon{border-color:#365a7b!important;color:#a8d5ff!important;background:#102034!important}
  .sx13-nav.active{background:#172f46!important;border-left-color:#58afff!important;color:#f5f9ff!important}
  #sxCaptchaV13{grid-column:1/-1;border:1px solid #2b6f89;border-radius:14px;background:linear-gradient(135deg,#0e2632,#0a1720);padding:16px 17px;box-shadow:inset 3px 0 0 #50d5ff,0 12px 28px #0002;margin-bottom:2px}
  #sxCaptchaV13 .sx13-cap-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
  #sxCaptchaV13 h2{margin:0;font-size:19px;letter-spacing:-.025em}#sxCaptchaV13 p{margin:5px 0 0;color:#91a8b8;font-size:11px;max-width:820px}
  #sxCaptchaV13 .sx13-cap-badge{flex:0 0 auto;border:1px solid #2b6b52;background:#10281f;color:#7ce3b0;border-radius:999px;padding:6px 9px;font-size:9px;font-weight:950}
  #sxCaptchaV13 .sx13-cap-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
  @media(max-width:620px){#sxCaptchaV13 .sx13-cap-head{display:block}#sxCaptchaV13 .sx13-cap-badge{display:inline-flex;margin-top:9px}}
</style>
'''

JS = r'''
<script id="sentrix-dashboard-visibility-v13-js">
(()=>{
"use strict";
if(window.__sentrixDashboardVisibilityV13)return;
window.__sentrixDashboardVisibilityV13=true;
const $=id=>document.getElementById(id);
const state=()=>window.state||window.__sentrixUnifiedRuntimeV10?.state||null;
function ensureCaptcha(){
  const s=state();if(s?.tab!=="verification"){$("sxCaptchaV13")?.remove();return}
  if($("sxVerifyV9")){ $("sxCaptchaV13")?.remove(); return }
  const control=$("verifyCaptcha"),content=$("content"),grid=content?.querySelector(":scope > .grid");if(!control||!grid||$("sxCaptchaV13"))return;
  const box=document.createElement("section");box.id="sxCaptchaV13";box.innerHTML='<div class="sx13-cap-head"><div><h2>Vérification Discord réelle</h2><p>Le CAPTCHA V96 est actif ici : le membre doit résoudre le code avant que SentriX lui attribue le rôle. Les boutons ci-dessous utilisent les vrais contrôles de cette page.</p></div><span class="sx13-cap-badge">CAPTCHA V96 RÉEL</span></div><div class="sx13-cap-actions"><button type="button" class="btn" id="sx13CaptchaFocus">Régler le CAPTCHA</button><button type="button" class="btn primary" id="sx13CaptchaPublish">Enregistrer et publier sur Discord</button></div>';
  grid.prepend(box);
  $("sx13CaptchaFocus")?.addEventListener("click",()=>{control.scrollIntoView({behavior:"smooth",block:"center"});control.focus()});
  $("sx13CaptchaPublish")?.addEventListener("click",()=>$("verifyPublish")?.click());
}
// Seul déclencheur : le contenu change (changement d'onglet). ensureCaptcha est idempotent,
// ne déclenche aucun fetch et n'écrit rien en dehors de son propre encart.
const content=$("content");if(content)new MutationObserver(()=>queueMicrotask(ensureCaptcha)).observe(content,{childList:true,subtree:true});
ensureCaptcha();
})();
</script>
'''



def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False
    if 'id="sentrix-growth-v12-js"' not in html:
        logger.error("Visibility V13 requires Growth Control V12 in the final HTML.")
        return False
    if API_MARKER not in html:
        logger.error("Visibility V13 requires the Growth Control V12 API marker in the final HTML.")
        return False
    if f'id="{CSS_MARKER}"' not in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if f'id="{JS_MARKER}"' not in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    ok = all(x in html for x in (API_MARKER, CSS_MARKER, JS_MARKER, "CAPTCHA V96 RÉEL", "sxCaptchaV13"))
    logger.info("Dashboard Visibility V13 installed=%s: visible CAPTCHA guard (Growth navigation/re-render bridge retired, V15 renders natively).", ok)
    return ok


__all__ = ["install", "CSS_MARKER", "JS_MARKER", "API_MARKER"]
