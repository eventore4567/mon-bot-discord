"""Extension du dashboard SentriX : recherche instantanée dans les listes de salons."""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.channel-search")
_INSTALLED = False


CHANNEL_SEARCH_CSS = r"""
    .channel-search-wrap{display:grid;gap:8px;width:100%}
    .channel-search-box{position:relative;display:flex;align-items:center}
    .channel-search-box:before{content:"⌕";position:absolute;left:13px;color:var(--muted);font-size:20px;pointer-events:none;z-index:1}
    .channel-search-input{width:100%;padding-left:40px!important;background:#0d111c!important;border-color:#303852!important}
    .channel-search-input:focus{border-color:var(--brand)!important;box-shadow:0 0 0 3px rgba(88,101,242,.16)}
    .channel-search-input::-webkit-search-cancel-button{cursor:pointer}
    .channel-search-select{width:100%}
    .channel-search-empty{padding:8px 11px;border:1px dashed #38415c;border-radius:9px;color:var(--muted);font-size:12px;background:#111725}
"""


CHANNEL_SEARCH_JS = r"""
    const channelSearchKeys=new Set([
      "log_channel","welcome_channel","goodbye_channel","rules_channel",
      "verification_channel","ticket_log_channel","level_channel",
      "suggest_channel","announce_channel","giveaway_channel",
      "bot_commands_channel","report_channel","partner_channel","stats_channel",
      "afk_channel","error_channel","log_messages","log_members","log_voice",
      "log_roles","log_server","log_automod","log_moderation",
      "discord_channel_id"
    ]);
    function normaliseChannelSearch(value){return String(value||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLocaleLowerCase("fr").trim();}
    function isChannelSelect(select){
      if(!select||select.tagName!=="SELECT")return false;
      if(select.id==="embedChannel"||channelSearchKeys.has(select.dataset.key||""))return true;
      return [...select.options].slice(1).some(option=>/\s—\s[^—]+$/.test(option.textContent||""));
    }
    function filterChannelOptions(select,input,empty){
      const query=normaliseChannelSearch(input.value),options=[...select.options];let matches=0;
      options.forEach((option,index)=>{
        if(index===0){option.hidden=false;return;}
        const match=!query||normaliseChannelSearch(option.textContent).includes(query);
        option.hidden=!match&&!option.selected;
        if(match)matches++;
      });
      empty.classList.toggle("hidden",!query||matches>0);
      empty.textContent=query?"Aucun salon ne correspond à cette recherche.":"";
    }
    function enhanceChannelSelect(select){
      if(!isChannelSelect(select)||select.dataset.channelSearchReady==="1")return;
      select.dataset.channelSearchReady="1";
      const wrap=document.createElement("div");wrap.className="channel-search-wrap";
      const box=document.createElement("div");box.className="channel-search-box";
      const input=document.createElement("input");input.type="search";input.className="channel-search-input";input.placeholder="Rechercher un salon…";input.autocomplete="off";input.spellcheck=false;input.setAttribute("aria-label","Rechercher un salon par son nom");
      const empty=document.createElement("div");empty.className="channel-search-empty hidden";
      const parent=select.parentNode;if(!parent)return;
      parent.insertBefore(wrap,select);box.appendChild(input);wrap.appendChild(box);wrap.appendChild(select);wrap.appendChild(empty);select.classList.add("channel-search-select");
      input.addEventListener("input",()=>filterChannelOptions(select,input,empty));
      input.addEventListener("keydown",event=>{if(event.key==="Escape"&&input.value){input.value="";filterChannelOptions(select,input,empty);input.blur();}});
      select.addEventListener("change",()=>{if(input.value){input.value="";filterChannelOptions(select,input,empty);}});
    }
    function installChannelSearches(){const root=$("fields");if(!root)return;root.querySelectorAll("select").forEach(enhanceChannelSelect);}
"""


def _replace_once(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        logger.warning("Dashboard recherche salons : point d'insertion introuvable (%s).", label)
        return html
    return html.replace(old, new, 1)


def _patch_html(html: str) -> str:
    html = _replace_once(
        html,
        "  </style>",
        CHANNEL_SEARCH_CSS + "\n  </style>",
        "css",
    )
    listener_anchor = '    $("serverSelect").addEventListener("change",e=>selectGuild(e.target.value));'
    observer_js = CHANNEL_SEARCH_JS + r'''
    const channelSearchRoot=$("fields");
    if(channelSearchRoot){
      const channelSearchObserver=new MutationObserver(()=>installChannelSearches());
      channelSearchObserver.observe(channelSearchRoot,{childList:true,subtree:true});
      installChannelSearches();
    }
'''
    html = _replace_once(
        html,
        listener_anchor,
        observer_js + "\n" + listener_anchor,
        "javascript",
    )
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    dashboard.INDEX_HTML = _patch_html(dashboard.INDEX_HTML)
    logger.info("Recherche de salons du dashboard chargée.")
