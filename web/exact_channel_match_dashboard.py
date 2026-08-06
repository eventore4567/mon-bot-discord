"""Correction du dashboard : un nom de salon exact doit toujours gagner."""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.channel-search-exact")
_INSTALLED = False


EXACT_MATCH_JS = r"""
    document.addEventListener("input",event=>{
      const target=event.target;
      if(!(target instanceof Element))return;
      const input=target.closest(".channel-search-input");
      if(!input)return;
      const wrap=input.closest(".channel-search-wrap");
      const select=wrap?.querySelector("select");
      if(!select)return;

      const query=normaliseChannelSearch(input.value);
      if(!query)return;

      const exactOptions=[...select.options].filter(option=>
        option.dataset.channelOriginalIndex!=="0"&&channelOptionName(option)===query
      );
      if(exactOptions.length!==1)return;

      const exact=exactOptions[0];
      if(select.value!==exact.value){
        select.value=exact.value;
        exact.selected=true;
        select.dispatchEvent(new Event("input",{bubbles:true}));
      }

      queueMicrotask(()=>{
        const status=wrap.querySelector(".channel-search-empty");
        if(!status)return;
        const name=String(exact.textContent||"").split(" — ")[0].trim();
        status.classList.remove("hidden","suggestions");
        status.textContent=`Salon exact sélectionné : ${name}.`;
      });
    },true);
"""


def _patch_html(html: str) -> str:
    anchor = '    $("serverSelect").addEventListener("change",e=>selectGuild(e.target.value));'
    if anchor not in html:
        logger.warning("Dashboard : insertion de la priorité exacte impossible.")
        return html
    return html.replace(anchor, EXACT_MATCH_JS + "\n" + anchor, 1)


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    dashboard.INDEX_HTML = _patch_html(dashboard.INDEX_HTML)
    logger.info("Priorité aux noms exacts des salons chargée.")
