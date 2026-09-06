"""Intègre la Feature Suite V37 dans le dashboard SentriX V60.

Le centre V37 reste le moteur/backend des dix systèmes avancés, mais il ne doit plus
remplacer visuellement le dashboard principal. Les navigations vers ``/feature-suite``
sont redirigées vers l'onglet V60 ``features``. Le document historique n'est servi que
dans une iframe same-origin explicitement marquée ``embed=1`` ; son chrome est masqué et
son thème est harmonisé avec V60 afin que l'utilisateur reste dans la même interface.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from aiohttp import web

logger = logging.getLogger("bot.dashboard-v60-features-inline")
_INSTALLED = False

INLINE_CSS = r'''
/* SentriX V60 — fonctions avancées intégrées */
.sx-features-shell{border:1px solid #484d53;border-radius:8px;background:#2b2f34;overflow:hidden;min-height:720px}
.sx-features-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 15px;border-bottom:1px solid #454a50;background:#303439}
.sx-features-head strong{font-size:13px}.sx-features-head span{display:block;color:#aeb0b3;font-size:10px;margin-top:3px}
.sx-features-frame{display:block;width:100%;min-height:760px;border:0;background:#292d32}
.sx-features-loading{padding:32px;text-align:center;color:#aaa;font-size:12px}
@media(max-width:760px){.sx-features-shell{border-radius:0;margin-left:-14px;margin-right:-14px}.sx-features-head{align-items:flex-start;flex-direction:column}.sx-features-frame{min-height:900px}}
'''

INLINE_JS = r'''
<script id="sentrix-v60-features-inline">
(() => {
  "use strict";
  if(window.__sentrixV60FeaturesInline)return;window.__sentrixV60FeaturesInline=true;

  const EMBED_STYLE=`
    :root{--bg:#292d32!important;--panel:#303439!important;--panel2:#2b2f34!important;--line:#484d53!important;--text:#f3f3f3!important;--muted:#aeb0b3!important;--accent:#d66f55!important;--ok:#72c69a!important;--bad:#ef7183!important}
    html,body{background:#292d32!important;min-height:0!important}
    body{overflow:hidden!important}
    .top{display:none!important}
    .shell{max-width:none!important;margin:0!important;padding:14px!important;background:#292d32!important}
    .head{display:none!important}
    .tabs{margin:0 0 14px!important;gap:7px!important}
    .tab{background:#2d3136!important;border-color:#484d53!important;color:#d7d8da!important;border-radius:6px!important;min-height:44px!important}
    .tab:hover{border-color:#686e75!important;background:#34383d!important}
    .tab.active{border-color:#d66f55!important;background:#463029!important;color:#fff!important}
    .panel,.card,.item,.metric{border-color:#484d53!important;background:#303439!important;border-radius:7px!important}
    .panel-head{border-color:#484d53!important;background:#303439!important}
    .content{background:#292d32!important}
    input,select,textarea{background:#24282d!important;border-color:#4b5056!important;color:#f2f2f2!important;border-radius:6px!important}
    input:focus,select:focus,textarea:focus{border-color:#d66f55!important;outline:none!important}
    .btn{background:#34383d!important;border-color:#555b62!important;color:#eee!important;border-radius:6px!important}
    .btn.primary{background:#5a352c!important;border-color:#d66f55!important;color:#fff!important}
    .btn.danger{background:#422328!important;border-color:#7b4149!important}
    .state.on{border-color:#3f7057!important;background:#1d3a2c!important;color:#8ce0b2!important}
    .toast{right:14px!important;bottom:14px!important}
    @media(max-width:900px){.shell{padding:9px!important}}
  `;

  function ensureFeatureNav(){
    const nav=$('navigation');if(!nav)return;
    if(!nav.querySelector('[data-tab="features"]')){
      const b=document.createElement('button');b.type='button';b.dataset.tab='features';
      b.innerHTML='<span class="nav-icon">⚙</span>Fonctions avancées';
      const anchor=nav.querySelector('[data-tab="access"]')||nav.querySelector('[data-tab="general"]');
      if(anchor&&anchor.nextSibling)nav.insertBefore(b,anchor.nextSibling);else nav.appendChild(b);
    }
    tabMeta.features=['Fonctions avancées','Automatisations, recrutements, vocaux temporaires, surveillance, planning, événements, FAQ, santé serveur, Sticky Roles et panneaux.'];
  }

  function styleEmbeddedFeatureSuite(frame){
    try{
      const doc=frame.contentDocument;if(!doc)return;
      if(!doc.getElementById('sentrix-v60-embedded-style')){
        const style=doc.createElement('style');style.id='sentrix-v60-embedded-style';style.textContent=EMBED_STYLE;doc.head.appendChild(style);
      }
      const resize=()=>{
        try{
          const height=Math.max(760,doc.documentElement.scrollHeight,doc.body?.scrollHeight||0);
          frame.style.height=Math.min(3600,height+8)+'px';
        }catch(_){}
      };
      resize();
      if(typeof ResizeObserver==='function'){
        const observer=new ResizeObserver(resize);observer.observe(doc.documentElement);
        frame.__sentrixResizeObserver=observer;
      }
      setTimeout(resize,250);setTimeout(resize,800);
    }catch(error){console.warn('SentriX V60: impossible de styliser le centre intégré',error)}
  }

  function renderFeaturesInline(){
    $('tabTitle').textContent='Fonctions avancées';
    $('tabDescription').textContent='Configurez les systèmes avancés sans quitter le dashboard SentriX.';
    document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='features'));
    $('saveBar').classList.add('hidden');state.dirty=false;
    const guildId=String(state.guildId||'');
    if(!guildId){$('fields').innerHTML='<div class="panel-section"><div class="empty">Choisissez d’abord un serveur.</div></div>';return;}
    const src='/feature-suite?embed=1&guild='+encodeURIComponent(guildId);
    $('fields').innerHTML=`<div class="panel-section"><div class="sx-features-shell"><div class="sx-features-head"><div><strong>Configuration avancée SentriX</strong><span>Les dix systèmes restent dans le serveur actuellement sélectionné.</span></div><span>Interface V60</span></div><div id="sxFeaturesLoading" class="sx-features-loading">Chargement des fonctions avancées…</div><iframe id="sxFeaturesFrame" class="sx-features-frame hidden" title="Fonctions avancées SentriX" src="${src}"></iframe></div></div>`;
    const frame=$('sxFeaturesFrame');
    frame.addEventListener('load',()=>{
      $('sxFeaturesLoading')?.classList.add('hidden');frame.classList.remove('hidden');styleEmbeddedFeatureSuite(frame);
    },{once:true});
  }

  const baseRenderTab=renderTab;
  renderTab=function(){
    ensureFeatureNav();
    if(state.tab==='features'){renderFeaturesInline();return;}
    return baseRenderTab();
  };

  // Tout ancien lien encore présent vers le centre V37 reste dans le shell V60.
  document.addEventListener('click',event=>{
    const link=event.target.closest?.('a[href^="/feature-suite"]');
    if(!link)return;
    event.preventDefault();
    state.tab='features';
    renderTab();
    try{history.replaceState({},'',`/app?tab=features&guild=${encodeURIComponent(state.guildId||'')}`)}catch(_){}
  });

  ensureFeatureNav();

  // Les anciennes pages secondaires redirigent ici avec ?tab=features&guild=... .
  const params=new URLSearchParams(location.search);
  if(params.get('tab')==='features'){
    state.tab='features';
    const wanted=String(params.get('guild')||'');
    const open=()=>{
      if(wanted&&String(state.guildId||'')!==wanted){
        const option=[...($('serverSelect')?.options||[])].find(o=>String(o.value)===wanted);
        if(option){$('serverSelect').value=wanted;selectGuild(wanted);return;}
      }
      if(state.guildId)renderTab();
    };
    setTimeout(open,250);setTimeout(open,850);
  }
})();
</script>
'''


def _install_route_redirect() -> bool:
    """Transforme la page V37 autonome en deep-link V60, sauf pour l'iframe interne."""
    try:
        from . import feature_suite_dashboard_v37 as feature_suite
    except Exception:
        logger.exception("Dashboard V60 : Feature Suite V37 indisponible.")
        return False

    current = feature_suite.handle_page
    if getattr(current, "_sentrix_v60_inline_redirect", False):
        return True

    async def inline_or_redirect(request: web.Request):
        if request.query.get("embed") == "1":
            response = await current(request)
            if isinstance(response, web.Response):
                response.headers["X-SentriX-Feature-Suite"] = "v60-embedded"
                response.headers["X-Frame-Options"] = "SAMEORIGIN"
            return response

        params = {"tab": "features"}
        guild_id = str(request.query.get("guild") or "").strip()
        if guild_id.isdigit():
            params["guild"] = guild_id
        raise web.HTTPFound("/app?" + urlencode(params))

    inline_or_redirect._sentrix_v60_inline_redirect = True
    inline_or_redirect._sentrix_original = current
    feature_suite.handle_page = inline_or_redirect
    return True


def install(dashboard) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    if not str(getattr(dashboard, "_sentrix_dashboard_version", "")).startswith("v60"):
        logger.error("Dashboard V60 fonctions avancées refusé : V60 absent.")
        return False

    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v60-features-inline"' not in html:
        if "</style>" not in html or "</body>" not in html:
            return False
        html = html.replace("</style>", INLINE_CSS + "\n</style>", 1)
        html = html.replace("</body>", INLINE_JS + "\n</body>", 1)
        dashboard.INDEX_HTML = html

    redirect_ok = _install_route_redirect()
    if not redirect_ok:
        return False

    _INSTALLED = True
    dashboard._sentrix_dashboard_version = "v60-max-suite-inline-features"
    logger.info("Dashboard V60 : Feature Suite intégrée au shell principal ; ancien centre redirigé.")
    return True


__all__ = ["install", "INLINE_CSS", "INLINE_JS"]
