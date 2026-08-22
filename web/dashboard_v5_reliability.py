"""Final navigation guard for the SentriX V5 dashboard."""

from __future__ import annotations


V5_RELIABILITY_CSS = r"""
<style id="sentrix-dashboard-v5-reliability-css">
  /* Hard guarantee: the overview renderer only exists on the overview page. */
  body:not([data-tab="overview"]) #fields>.sx-overview{display:none!important}
  body[data-tab="overview"] #fields>.sx-overview{display:grid!important;grid-column:1/-1!important}

  /* Never let legacy dashboard homes stack above the current V5 page. */
  #sxSimpleHome,#sxSimpleControls,#sxModeEscape,#sentrixOxydeHero,
  .sentrix-control-center,.sentrix-advanced-guide{display:none!important}

  /* A page render always owns the full content width. */
  #dashboard #fields{min-width:0!important;width:100%!important}
  #dashboard #fields>*{min-width:0}
</style>
"""


V5_RELIABILITY_JS = r"""
<script id="sentrix-dashboard-v5-reliability-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardV5Reliability) return;
  window.__sentrixDashboardV5Reliability = true;

  const getState=()=>{try{return typeof state!=="undefined"?state:null}catch(_){return null}};

  /* The native dashboard nav listener predates the V5 router and does not ask before
     discarding a dirty form. Capture the click first so no later listener can lose data. */
  document.addEventListener("click",event=>{
    const button=event.target?.closest?.("#navigation button[data-tab]");
    if(!button)return;
    const s=getState();
    if(!s)return;
    const next=String(button.dataset.tab||"");
    if(s.dirty&&next&&next!==String(s.tab||"")&&!confirm("Vous avez des modifications non enregistrées. Changer de page ?")){
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    if(next)document.body.dataset.tab=next;
  },true);

  document.addEventListener("change",event=>{
    if(event.target?.id!=="serverSelect")return;
    const s=getState();
    if(!s?.dirty)return;
    if(confirm("Vous avez des modifications non enregistrées. Changer de serveur ?"))return;
    event.preventDefault();
    event.stopImmediatePropagation();
    event.target.value=s.guildId||"";
  },true);

  function repairPageState(){
    const s=getState();
    if(!s?.guildData)return;
    const valid=new Set([...document.querySelectorAll("#navigation button[data-tab]")].map(button=>button.dataset.tab));
    if(!valid.has(String(s.tab||""))){s.tab="overview";try{renderTab()}catch(_){} }
    document.body.dataset.tab=String(s.tab||"overview");
    document.querySelectorAll("#navigation button[data-tab]").forEach(button=>button.classList.toggle("active",button.dataset.tab===s.tab));

    /* Defensive cleanup if a browser restored duplicated DOM from an interrupted render. */
    const overviews=[...document.querySelectorAll("#fields>.sx-overview")];
    overviews.slice(1).forEach(node=>node.remove());
  }

  const observer=new MutationObserver(()=>setTimeout(repairPageState,0));
  const start=()=>{
    repairPageState();
    const fields=document.getElementById("fields");
    if(fields)observer.observe(fields,{childList:true});
    [120,500,1400].forEach(delay=>setTimeout(repairPageState,delay));
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
</script>
"""


def apply_v5_reliability(html: str) -> str:
    if not isinstance(html, str):
        return html
    if 'id="sentrix-dashboard-v5-reliability-css"' not in html:
        html = html.replace("</head>", V5_RELIABILITY_CSS + "\n</head>", 1)
    if 'id="sentrix-dashboard-v5-reliability-js"' not in html:
        html = html.replace("</body>", V5_RELIABILITY_JS + "\n</body>", 1)
    return html


__all__ = ["apply_v5_reliability"]
