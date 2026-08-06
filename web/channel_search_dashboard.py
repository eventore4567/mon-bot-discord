"""Extension du dashboard SentriX : recherche instantanée et approximative des salons."""

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
    .channel-search-empty.suggestions{border-color:#35507a;color:#a9c8ff;background:#111d32}
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

    function normaliseChannelSearch(value){
      return String(value||"")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g,"")
        .toLocaleLowerCase("fr")
        .replace(/[^a-z0-9]+/g," ")
        .trim();
    }

    function channelOptionName(option){
      const raw=String(option?.textContent||"").split(" — ")[0];
      return normaliseChannelSearch(raw);
    }

    function levenshteinDistance(a,b){
      if(a===b)return 0;
      if(!a.length)return b.length;
      if(!b.length)return a.length;
      let previous=Array.from({length:b.length+1},(_,index)=>index);
      for(let i=1;i<=a.length;i++){
        const current=[i];
        for(let j=1;j<=b.length;j++){
          const cost=a[i-1]===b[j-1]?0:1;
          current[j]=Math.min(
            current[j-1]+1,
            previous[j]+1,
            previous[j-1]+cost
          );
        }
        previous=current;
      }
      return previous[b.length];
    }

    function subsequenceScore(query,name){
      if(!query||!name)return 0;
      let queryIndex=0;
      for(const character of name){
        if(character===query[queryIndex])queryIndex++;
        if(queryIndex===query.length)break;
      }
      if(queryIndex!==query.length)return 0;
      return .48+.22*(query.length/name.length);
    }

    function channelMatchScore(query,name){
      if(!query||!name)return 0;
      if(name===query)return 2;
      if(name.startsWith(query))return 1.85-(name.length-query.length)*.002;
      const position=name.indexOf(query);
      if(position>=0)return 1.65-position*.01;

      const queryWords=query.split(/\s+/).filter(Boolean);
      const nameWords=name.split(/\s+/).filter(Boolean);
      let wordScore=0;
      if(queryWords.length){
        const wordMatches=queryWords.map(queryWord=>{
          let best=0;
          for(const nameWord of nameWords){
            if(nameWord===queryWord)best=Math.max(best,1);
            else if(nameWord.startsWith(queryWord)||queryWord.startsWith(nameWord))best=Math.max(best,.9);
            else{
              const maximum=Math.max(queryWord.length,nameWord.length);
              const similarity=maximum?1-levenshteinDistance(queryWord,nameWord)/maximum:0;
              best=Math.max(best,similarity);
            }
          }
          return best;
        });
        wordScore=wordMatches.reduce((sum,value)=>sum+value,0)/wordMatches.length;
      }

      const maximum=Math.max(query.length,name.length);
      const fullScore=maximum?1-levenshteinDistance(query,name)/maximum:0;
      return Math.max(fullScore,wordScore,subsequenceScore(query,name));
    }

    function isChannelSelect(select){
      if(!select||select.tagName!=="SELECT")return false;
      if(select.id==="embedChannel"||channelSearchKeys.has(select.dataset.key||""))return true;
      return [...select.options].slice(1).some(option=>/\s—\s[^—]+$/.test(option.textContent||""));
    }

    function restoreChannelOptionOrder(select){
      const options=[...select.options].sort((a,b)=>Number(a.dataset.channelOriginalIndex||0)-Number(b.dataset.channelOriginalIndex||0));
      options.forEach(option=>{option.hidden=false;select.appendChild(option);});
    }

    function filterChannelOptions(select,input,status){
      const query=normaliseChannelSearch(input.value);
      const placeholder=[...select.options].find(option=>option.dataset.channelOriginalIndex==="0")||select.options[0];
      if(!query){
        restoreChannelOptionOrder(select);
        status.classList.add("hidden");
        status.classList.remove("suggestions");
        status.textContent="";
        return;
      }

      const candidates=[...select.options]
        .filter(option=>option!==placeholder)
        .map(option=>{
          const name=channelOptionName(option);
          const exact=name.includes(query);
          const score=channelMatchScore(query,name);
          return {option,name,exact,score,original:Number(option.dataset.channelOriginalIndex||0)};
        });

      const minimum=query.length<=2?.88:query.length<=4?.55:.48;
      let visible=candidates
        .filter(item=>item.exact||item.score>=minimum||item.option.selected)
        .sort((a,b)=>{
          if(a.option.selected!==b.option.selected)return a.option.selected?-1:1;
          if(a.exact!==b.exact)return a.exact?-1:1;
          return b.score-a.score||a.original-b.original;
        });

      const exactCount=visible.filter(item=>item.exact).length;
      if(exactCount===0)visible=visible.slice(0,6);
      else visible=visible.slice(0,12);
      const visibleOptions=new Set(visible.map(item=>item.option));

      placeholder.hidden=false;
      select.appendChild(placeholder);
      visible.forEach(item=>{item.option.hidden=false;select.appendChild(item.option);});
      candidates.forEach(item=>{
        if(!visibleOptions.has(item.option))item.option.hidden=true;
      });

      status.classList.remove("hidden");
      if(!visible.length){
        status.classList.remove("suggestions");
        status.textContent="Aucun salon proche trouvé. Essayez avec un autre mot.";
      }else if(exactCount===0){
        status.classList.add("suggestions");
        status.textContent=`Aucun nom exact : ${visible.length} salon${visible.length>1?"s":""} proche${visible.length>1?"s":""} proposé${visible.length>1?"s":""}.`;
      }else{
        const approximateCount=visible.length-exactCount;
        status.classList.toggle("suggestions",approximateCount>0);
        status.textContent=approximateCount>0
          ?`${exactCount} résultat${exactCount>1?"s":""} direct${exactCount>1?"s":""} et ${approximateCount} salon${approximateCount>1?"s":""} proche${approximateCount>1?"s":""}.`
          :`${exactCount} salon${exactCount>1?"s":""} trouvé${exactCount>1?"s":""}.`;
      }
    }

    function enhanceChannelSelect(select){
      if(!isChannelSelect(select)||select.dataset.channelSearchReady==="1")return;
      select.dataset.channelSearchReady="1";
      [...select.options].forEach((option,index)=>option.dataset.channelOriginalIndex=String(index));
      const wrap=document.createElement("div");wrap.className="channel-search-wrap";
      const box=document.createElement("div");box.className="channel-search-box";
      const input=document.createElement("input");input.type="search";input.className="channel-search-input";input.placeholder="Rechercher un salon…";input.autocomplete="off";input.spellcheck=false;input.setAttribute("aria-label","Rechercher un salon par son nom");
      const status=document.createElement("div");status.className="channel-search-empty hidden";
      const parent=select.parentNode;if(!parent)return;
      parent.insertBefore(wrap,select);box.appendChild(input);wrap.appendChild(box);wrap.appendChild(select);wrap.appendChild(status);select.classList.add("channel-search-select");
      input.addEventListener("input",()=>filterChannelOptions(select,input,status));
      input.addEventListener("keydown",event=>{if(event.key==="Escape"&&input.value){input.value="";filterChannelOptions(select,input,status);input.blur();}});
      select.addEventListener("change",()=>{if(input.value){input.value="";filterChannelOptions(select,input,status);}});
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
    logger.info("Recherche approximative de salons du dashboard chargée.")
