"""Compatibility entry point for the SentriX dashboard presentation layer."""

from .dashboard_oxyde_rebuild import apply_dashboard_pages as _apply_oxyde_dashboard
from .dashboard_oxyde_hotfix import apply_dashboard_hotfix, patch_dashboard_runtime


# dashboard.py imports this module after its handlers are defined. Patch the guild reader
# immediately so a secondary/optional table can never leave the whole dashboard blank.
patch_dashboard_runtime()


_EMBEDS_PAGE_FIX = r"""
    /* Embeds has its own secure builder route; keep it as a real dashboard page. */
    body[data-tab="embeds"] #sxV4Save,
    body[data-tab="embeds"] .savebar{display:none!important}
"""

_EMBEDS_PAGE_JS = r"""
    (() => {
      "use strict";
      tabs.embeds={
        title:"Embeds",
        description:"Créez et publiez vos messages enrichis depuis l'éditeur SentriX.",
        fields:[]
      };
      const sxRenderWithEmbeds=renderTab;
      renderTab=function(){
        if(state.tab!=="embeds")return sxRenderWithEmbeds();
        if(!state.guildData)return;
        document.body.dataset.tab="embeds";
        const title=document.getElementById("tabTitle");
        const description=document.getElementById("tabDescription");
        const crumb=document.getElementById("sxV4Crumb");
        const eyebrow=document.getElementById("sxV4Eyebrow");
        if(title)title.textContent="Embeds";
        if(description)description.textContent="Préparez vos annonces et messages Discord avec l'éditeur dédié de SentriX.";
        if(crumb)crumb.textContent="Embeds";
        if(eyebrow)eyebrow.textContent="OUTILS";
        document.getElementById("navigation")?.querySelectorAll("button[data-tab]").forEach(btn=>btn.classList.toggle("active",btn.dataset.tab==="embeds"));
        const fields=document.getElementById("fields");
        if(fields){
          const guild=encodeURIComponent(String(state.guildId||""));
          fields.innerHTML='<div class="sx-section-head"><small>OUTILS</small><h2>Créateur d embeds</h2><p>Utilisez l éditeur sécurisé déjà relié à votre serveur.</p></div><article class="sx-hub-card" style="grid-column:1/-1;min-height:240px"><div><div class="sx-kicker">MESSAGES DISCORD</div><h3>Créer un message enrichi</h3><p>Composez le contenu, choisissez le salon, prévisualisez le rendu et publiez depuis le créateur SentriX.</p></div><div class="sx-hub-actions"><button type="button" class="sx-hub-button primary" id="sxOpenEmbedBuilder">Ouvrir le créateur</button></div></article>';
          fields.querySelector("#sxOpenEmbedBuilder")?.addEventListener("click",()=>{location.href="/embed-builder"+(guild?"?guild="+guild:"");});
        }
        document.getElementById("saveBar")?.classList.add("hidden");
        document.getElementById("sxV4Save")?.classList.add("hidden");
        state.dirty=false;
      };
    })();
"""


def apply_dashboard_pages(html: str) -> str:
    """Install the clean dashboard, embeds bridge and final reliability layer."""
    html = _apply_oxyde_dashboard(html)
    if "body[data-tab=\"embeds\"] #sxV4Save" not in html:
        html = html.replace("  </style>", _EMBEDS_PAGE_FIX + "\n  </style>", 1)
    marker = "    Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true));"
    if marker in html and "sxRenderWithEmbeds" not in html:
        html = html.replace(marker, _EMBEDS_PAGE_JS + "\n" + marker, 1)
    return apply_dashboard_hotfix(html)


__all__ = ["apply_dashboard_pages"]
