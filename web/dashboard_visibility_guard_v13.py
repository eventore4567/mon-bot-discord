"""Browser-visible guard for the unified SentriX dashboard.

The canonical V55/V2 frontend rebuilds ``#navigation`` from its private NAV array. Growth V12
is intentionally additive, so its injected buttons can be removed by a later native render.
This layer runs after V12 and makes the additive pages persistent in the actual browser DOM.
It also exposes V12's existing renderer through a tiny public bridge and makes the real V96
CAPTCHA control unmistakably visible on the Verification page.
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
const TABS={
  stats:["Général","Statistiques","ST"],
  invites:["Communauté","Invitations","IN"],
  autoreact:["Communauté","Réactions automatiques","RA"],
  automations:["Outils","Automatisations","AU"],
  staffactivity:["Administration","Activité staff","AS"],
  audit:["Administration","Historique & audit","HA"],
  backups:["Administration","Sauvegardes","SV"],
  maintenance:["Administration","Maintenance","MT"],
  integrations:["Administration","Webhooks & intégrations","WI"]
};
const state=()=>window.state||window.__sentrixUnifiedRuntimeV10?.state||null;
const api=()=>window.__sentrixGrowthV12Api||null;
let repairing=false;
function group(name){return [...document.querySelectorAll("#navigation .nav-group")].find(x=>x.textContent.trim().toLocaleLowerCase("fr")===name.toLocaleLowerCase("fr"))}
function ensureNav(){
  const nav=$("navigation");if(!nav||repairing)return;
  repairing=true;
  try{
    for(const [key,[groupName,label,icon]] of Object.entries(TABS)){
      if(nav.querySelector(`[data-tab="${key}"],[data-sx12-tab="${key}"],[data-sx13-tab="${key}"]`))continue;
      const g=group(groupName);if(!g)continue;
      const b=document.createElement("button");b.type="button";b.className="sx13-nav";b.dataset.sx13Tab=key;b.innerHTML=`<span class="nav-icon">${icon}</span><span>${label}</span>`;
      let last=g,c=g.nextElementSibling;while(c&&!c.classList.contains("nav-group")){last=c;c=c.nextElementSibling}last.after(b);
    }
    sync();
  } finally {repairing=false}
}
function sync(){const cur=state()?.tab||new URL(location.href).searchParams.get("tab")||"";document.querySelectorAll("[data-sx13-tab],[data-sx12-tab]").forEach(b=>b.classList.toggle("active",(b.dataset.sx13Tab||b.dataset.sx12Tab)===cur))}
function openGrowth(tab){const a=api();if(a?.setTab){a.setTab(tab);sync();return}const u=new URL(location.href);u.searchParams.set("tab",tab);history.replaceState({},"",u);const c=$("content");if(c)c.innerHTML='<div class="error-state"><h2>Module dashboard en cours de chargement</h2><p>Le moteur Growth Control n’est pas encore disponible dans cette session.</p></div>';window.toast?.("Growth Control V12 n’est pas chargé dans le navigateur.",true)}
function ensureCurrent(){const s=state(),a=api();if(!s||!TABS[s.tab]||!a?.render)return;if(!$("content")?.querySelector(".sx12-page"))a.render(s.tab);sync()}
function ensureCaptcha(){
  const s=state();if(s?.tab!=="verification"){$("sxCaptchaV13")?.remove();return}
  if($("sxVerifyV9")){ $("sxCaptchaV13")?.remove(); return }
  const control=$("verifyCaptcha"),content=$("content"),grid=content?.querySelector(":scope > .grid");if(!control||!grid||$("sxCaptchaV13"))return;
  const box=document.createElement("section");box.id="sxCaptchaV13";box.innerHTML='<div class="sx13-cap-head"><div><h2>Vérification Discord réelle</h2><p>Le CAPTCHA V96 est actif ici : le membre doit résoudre le code avant que SentriX lui attribue le rôle. Les boutons ci-dessous utilisent les vrais contrôles de cette page.</p></div><span class="sx13-cap-badge">CAPTCHA V96 RÉEL</span></div><div class="sx13-cap-actions"><button type="button" class="btn" id="sx13CaptchaFocus">Régler le CAPTCHA</button><button type="button" class="btn primary" id="sx13CaptchaPublish">Enregistrer et publier sur Discord</button></div>';
  grid.prepend(box);
  $("sx13CaptchaFocus")?.addEventListener("click",()=>{control.scrollIntoView({behavior:"smooth",block:"center"});control.focus()});
  $("sx13CaptchaPublish")?.addEventListener("click",()=>$("verifyPublish")?.click());
}
function repair(){ensureNav();ensureCurrent();ensureCaptcha()}
document.addEventListener("click",e=>{const b=e.target.closest?.("[data-sx13-tab]");if(!b)return;e.preventDefault();e.stopPropagation();openGrowth(b.dataset.sx13Tab)},true);
const nav=$("navigation");if(nav)new MutationObserver(()=>queueMicrotask(repair)).observe(nav,{childList:true});
const content=$("content");if(content)new MutationObserver(()=>queueMicrotask(repair)).observe(content,{childList:true,subtree:true});
repair();setInterval(repair,650);
})();
</script>
'''

_RENDER_NEEDLE = 'function render(tab=st()?.tab){if(!R[tab])return;syncActive();R[tab]()}'
_RENDER_BRIDGE = _RENDER_NEEDLE + '\nwindow.__sentrixGrowthV12Api={render,setTab,ensureNav,TABS};'


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False
    if 'id="sentrix-growth-v12-js"' not in html:
        logger.error("Visibility V13 requires Growth Control V12 in the final HTML.")
        return False
    if API_MARKER not in html:
        if _RENDER_NEEDLE not in html:
            logger.error("Visibility V13 could not expose the V12 renderer.")
            return False
        html = html.replace(_RENDER_NEEDLE, _RENDER_BRIDGE, 1)
    if f'id="{CSS_MARKER}"' not in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if f'id="{JS_MARKER}"' not in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    ok = all(x in html for x in (API_MARKER, CSS_MARKER, JS_MARKER, "CAPTCHA V96 RÉEL", "data-sx13-tab"))
    logger.warning("Dashboard Visibility V13 installed=%s: persistent Growth navigation + visible CAPTCHA guard.", ok)
    return ok


__all__ = ["install", "CSS_MARKER", "JS_MARKER", "API_MARKER"]
