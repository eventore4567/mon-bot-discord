"""Créateur d'embeds isolé et sécurisé pour le dashboard SentriX."""

from __future__ import annotations

import logging

from aiohttp import web

from .embed_dashboard import EMBED_CSS, EMBED_JS, handle_send_embed

logger = logging.getLogger("bot.dashboard.embed-center")
_INSTALLED = False


BASE_CSS = r"""
:root{--bg:#090b12;--panel:#111522;--panel2:#171c2c;--line:#29304a;--text:#f2f4ff;--muted:#99a2b9;--brand:#7c6cff;--brand2:#a897ff;--ok:#44d39a;--bad:#ff667d}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 14% -12%,#392e7355,transparent 35%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select,textarea{font:inherit}a{color:inherit;text-decoration:none}.hidden{display:none!important}
.top{position:sticky;top:0;z-index:30;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 4vw;border-bottom:1px solid var(--line);background:#090b12ed;backdrop-filter:blur(14px)}.brand{font-size:19px;font-weight:950}.actions,.toolbar{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.btn{border:1px solid var(--line);border-radius:11px;padding:10px 14px;background:var(--panel2);color:var(--text);cursor:pointer;font-weight:850;display:inline-flex;align-items:center;justify-content:center;gap:8px}.btn:hover{border-color:#566182}.btn.primary{background:linear-gradient(135deg,var(--brand),#5d4de1);border-color:transparent}.btn.danger{background:#351720;border-color:#713044;color:#ff9aaa}.btn:disabled{opacity:.5;cursor:not-allowed}
main{max-width:1450px;margin:0 auto;padding:28px 24px 90px}.head{display:grid;grid-template-columns:1fr minmax(280px,430px);gap:20px;align-items:end;margin-bottom:20px}.head h1{margin:0 0 8px;font-size:34px;letter-spacing:-.03em}.head p{margin:0;color:var(--muted);line-height:1.55}.panel{background:var(--panel);border:1px solid var(--line);border-radius:19px;padding:20px}.select,input,textarea{width:100%;background:#0c101a;border:1px solid var(--line);color:var(--text);border-radius:11px;padding:11px 12px;outline:none}.select:focus,input:focus,textarea:focus{border-color:var(--brand)}textarea{resize:vertical;min-height:100px}.field label{display:block;font-weight:850;margin-bottom:7px}.hint{color:var(--muted);font-size:12px;line-height:1.45;margin-top:6px}.switch{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px;background:#101625;border:1px solid #29334e;border-radius:12px}.switch input{width:auto}.template-bar{display:grid;grid-template-columns:1fr auto auto;gap:8px;margin-bottom:16px;padding:14px;background:#0d111c;border:1px solid #242c43;border-radius:14px}.savebar{position:sticky;bottom:12px;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:16px;padding:12px 14px;background:#111522ec;border:1px solid var(--line);border-radius:14px;backdrop-filter:blur(15px);box-shadow:0 18px 48px #0008}.save-status{color:var(--muted);font-size:12px}.toast{position:fixed;right:18px;top:18px;z-index:10010;max-width:min(90vw,470px);padding:12px 14px;border-radius:12px;background:#173d32;border:1px solid #2f6f5c;color:#9af0ce;font-weight:800;box-shadow:0 18px 45px #0009}.toast.bad{background:#351720;border-color:#713044;color:#ffb8c4}.channel-search{position:relative;margin:8px 0}.channel-search input{padding-left:38px}.channel-search::before{content:"⌕";position:absolute;left:13px;top:50%;transform:translateY(-50%);font-size:19px;color:var(--muted)}.search-status{min-height:17px;color:var(--muted);font-size:12px;margin-bottom:7px}.search-status.exact{color:#8be4c3;font-weight:850}.loading{opacity:.65;pointer-events:none}
@media(max-width:900px){.head{grid-template-columns:1fr}.template-bar{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
@media(max-width:620px){main{padding:20px 12px 90px}.panel{padding:14px}.savebar{bottom:70px;align-items:stretch;flex-direction:column}.savebar .toolbar{width:100%}.savebar .btn{flex:1}}
"""


BASE_JS = r"""
const state={csrf:"",guilds:[],guildId:"",guildData:null,dirty:false,draftTimer:null};
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
async function json(url,options={}){const response=await fetch(url,options);let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.error||"Une erreur est survenue.");return data;}
function toast(message,bad=false){const box=$("toast");box.textContent=message;box.className=`toast${bad?" bad":""}`;box.classList.remove("hidden");clearTimeout(toast.timer);toast.timer=setTimeout(()=>box.classList.add("hidden"),4200);}
function draftKey(){return `sentrix:embed:draft:${state.guildId||"none"}`;}
function normalise(value){return String(value||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g," ").trim();}
function fuzzyScore(name,query){if(name===query)return-1000;if(name.startsWith(query))return-500+(name.length-query.length);if(name.includes(query))return-250+name.indexOf(query);const words=name.split(" ");let total=0;for(const token of query.split(" ")){let best=99;for(const word of words){let difference=Math.abs(word.length-token.length);for(let i=0;i<Math.min(word.length,token.length);i++)if(word[i]!==token[i])difference++;best=Math.min(best,difference);}total+=best;}return total*20;}
function installChannelSearch(){const select=$("embedChannel");if(!select||document.getElementById("embedChannelSearch"))return;const wrap=document.createElement("div");wrap.className="channel-search";wrap.innerHTML='<input id="embedChannelSearch" data-no-dirty="1" type="search" placeholder="Rechercher un salon…" autocomplete="off">';const status=document.createElement("div");status.id="embedChannelStatus";status.className="search-status";select.parentNode.insertBefore(wrap,select);select.parentNode.insertBefore(status,select);const input=$("embedChannelSearch");const filter=()=>{const query=normalise(input.value),options=[...select.options].filter(option=>option.value);if(!query){options.forEach(option=>{option.hidden=false;option.style.display="";});status.textContent=`${options.length} salons textuels disponibles`;status.classList.remove("exact");return;}const ranked=options.map(option=>({option,name:normalise(option.textContent),score:fuzzyScore(normalise(option.textContent),query)})).sort((a,b)=>a.score-b.score);const matches=ranked.filter(item=>item.score<0||item.score<=Math.max(35,query.length*18)).slice(0,8);const shown=matches.length?matches:ranked.slice(0,6),visible=new Set(shown.map(item=>item.option));ranked.forEach(item=>{item.option.hidden=!visible.has(item.option);item.option.style.display=visible.has(item.option)?"":"none";select.appendChild(item.option);});const exact=ranked.find(item=>item.name===query);status.textContent=exact?"✓ Salon exact trouvé":`${shown.length} salon${shown.length>1?"s":""} proche${shown.length>1?"s":""}`;status.classList.toggle("exact",Boolean(exact));};input.addEventListener("input",filter);input.addEventListener("keydown",event=>{if(event.key!=="Enter")return;event.preventDefault();const first=[...select.options].find(option=>option.value&&!option.hidden);if(first){select.value=first.value;select.dispatchEvent(new Event("change",{bubbles:true}));input.value="";filter();}});filter();}
function saveDraft(){if(!state.guildId||!$("embedChannel"))return;localStorage.setItem(draftKey(),JSON.stringify(collectEmbedPayload()));$("draftState").textContent=`Brouillon sauvegardé à ${new Date().toLocaleTimeString("fr-FR",{hour:"2-digit",minute:"2-digit"})}`;}
function scheduleDraft(){clearTimeout(state.draftTimer);state.draftTimer=setTimeout(saveDraft,450);}
function restoreDraft(){const raw=localStorage.getItem(draftKey());if(!raw)return;try{const data=JSON.parse(raw);const mapping={embedChannel:"channel_id",embedContent:"content",embedTitle:"title",embedDescription:"description",embedColor:"color",embedUrl:"url",embedAuthorName:"author_name",embedAuthorUrl:"author_url",embedAuthorIcon:"author_icon_url",embedFooter:"footer_text",embedFooterIcon:"footer_icon_url",embedImage:"image_url",embedThumbnail:"thumbnail_url"};for(const [id,key] of Object.entries(mapping)){if($(id))$(id).value=data[key]||"";}if($("embedColorPicker")&&/^#[0-9a-f]{6}$/i.test(data.color||""))$("embedColorPicker").value=data.color;if($("embedTimestamp"))$("embedTimestamp").checked=Boolean(data.timestamp);const list=$("embedFieldsList");if(list){list.innerHTML="";for(const field of data.fields||[])addEmbedField(false,field);if(!list.children.length)addEmbedField(false);}$("draftState").textContent="Brouillon restauré";updateEmbedPreview();}catch{localStorage.removeItem(draftKey());}}
function addEmbedFieldWithValue(focus=true,value={}){addEmbedField(focus);const rows=document.querySelectorAll(".embed-field-row"),row=rows[rows.length-1];if(!row)return;row.querySelector(".embedFieldName").value=value.name||"";row.querySelector(".embedFieldValue").value=value.value||"";row.querySelector(".embedFieldInline").checked=Boolean(value.inline);updateEmbedPreview();}
function applyTemplate(){const templates={announcement:{title:"📢 Nouvelle annonce",description:"Écrivez ici les informations importantes de votre annonce.",color:"#5865F2",footer_text:"L'équipe du serveur"},rules:{title:"📜 Règlement du serveur",description:"Merci de lire et de respecter les règles ci-dessous.",color:"#7C6CFF",fields:[{name:"1. Respect",value:"Respectez tous les membres du serveur.",inline:false},{name:"2. Spam",value:"Le spam et la publicité non autorisée sont interdits.",inline:false}]},giveaway:{title:"🎉 Nouveau giveaway",description:"Participez et tentez de gagner la récompense !",color:"#FEE75C",fields:[{name:"Récompense",value:"À compléter",inline:true},{name:"Fin",value:"À compléter",inline:true}]},event:{title:"🎮 Nouvel événement",description:"Rejoignez-nous pour un événement communautaire !",color:"#57F287",fields:[{name:"Date",value:"À compléter",inline:true},{name:"Heure",value:"À compléter",inline:true},{name:"Salon",value:"À compléter",inline:true}]}};const template=templates[$("template").value];if(!template)return;for(const id of ["embedContent","embedTitle","embedDescription","embedUrl","embedAuthorName","embedAuthorUrl","embedAuthorIcon","embedFooter","embedFooterIcon","embedImage","embedThumbnail"]){if($(id))$(id).value="";}$("embedTitle").value=template.title||"";$("embedDescription").value=template.description||"";$("embedColor").value=template.color||"#5865F2";$("embedColorPicker").value=template.color||"#5865F2";$("embedFooter").value=template.footer_text||"";$("embedFieldsList").innerHTML="";for(const field of template.fields||[])addEmbedFieldWithValue(false,field);if(!$("embedFieldsList").children.length)addEmbedField(false);updateEmbedPreview();}
function clearDraft(){if(!confirm("Effacer complètement le brouillon de cet embed ?"))return;localStorage.removeItem(draftKey());renderEmbeds();installChannelSearch();$("draftState").textContent="Brouillon effacé";bindEditor();}
function bindEditor(){installChannelSearch();const fields=$("fields");if(fields.dataset.draftBound!=="1"){fields.dataset.draftBound="1";fields.addEventListener("input",scheduleDraft);fields.addEventListener("change",scheduleDraft);}restoreDraft();}
async function loadGuild(id){if(!id)return;state.guildId=id;$("settingsForm").classList.add("loading");try{state.guildData=await json(`/api/guilds/${id}`);localStorage.setItem("sentrix:embed:guild",id);renderEmbeds();bindEditor();}catch(error){toast(error.message,true);}finally{$("settingsForm").classList.remove("loading");}}
async function boot(){try{const [me,guildData]=await Promise.all([json("/api/me"),json("/api/guilds")]);state.csrf=me.csrf;state.guilds=guildData.guilds.filter(guild=>guild.installed);$("guild").innerHTML='<option value="">Choisissez un serveur</option>'+state.guilds.map(guild=>`<option value="${esc(guild.id)}">${esc(guild.name)}</option>`).join("");const saved=localStorage.getItem("sentrix:embed:guild"),first=state.guilds.find(guild=>guild.id===saved)||state.guilds[0];if(first){$("guild").value=first.id;await loadGuild(first.id);}else toast("Aucun serveur administrable avec SentriX n'est disponible.",true);}catch(error){toast(error.message,true);setTimeout(()=>location.href="/app",1400);}}
"""

# EMBED_JS appelle addEmbedField avec un seul argument. Ce petit adaptateur permet aussi
# de restaurer des champs depuis le brouillon sans modifier le module historique.
ADAPTER_JS = r"""
const _baseAddEmbedField=addEmbedField;
addEmbedField=function(focus=true,value=null){_baseAddEmbedField(focus);if(value){const rows=document.querySelectorAll(".embed-field-row"),row=rows[rows.length-1];if(row){row.querySelector(".embedFieldName").value=value.name||"";row.querySelector(".embedFieldValue").value=value.value||"";row.querySelector(".embedFieldInline").checked=Boolean(value.inline);}}};
$("guild").addEventListener("change",event=>loadGuild(event.target.value));
$("settingsForm").addEventListener("submit",event=>{event.preventDefault();sendEmbed();});
$("saveButton").addEventListener("click",event=>{event.preventDefault();sendEmbed();});
$("applyTemplate").addEventListener("click",applyTemplate);
$("clearDraft").addEventListener("click",clearDraft);
boot();
"""

EMBED_CENTER_HTML = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#090b12"><title>SentriX — Créateur d'embeds</title><style>""" + BASE_CSS + EMBED_CSS + """</style></head>
<body><header class="top"><div class="brand">📨 SentriX — Créateur d'embeds</div><div class="actions"><a class="btn" href="/app">← Dashboard</a><a class="btn" href="/setup-center">⚙️ Centre Setup</a></div></header>
<main><div class="head"><div><h1>Créer un message professionnel</h1><p>Aperçu Discord en direct, brouillon automatique, modèles rapides et recherche intelligente du salon. Les mentions sont neutralisées pour éviter les pings accidentels.</p></div><div class="field"><label>Serveur</label><select id="guild" class="select"><option>Chargement…</option></select></div></div>
<form id="settingsForm" class="panel embed-form"><div class="template-bar"><select id="template" class="select"><option value="">Partir de zéro</option><option value="announcement">📢 Annonce</option><option value="rules">📜 Règlement</option><option value="giveaway">🎉 Giveaway</option><option value="event">🎮 Événement</option></select><button id="applyTemplate" class="btn" type="button">Appliquer le modèle</button><button id="clearDraft" class="btn danger" type="button">Effacer le brouillon</button></div><div id="fields"></div><div class="savebar" id="saveBar"><div><div id="saveStatus" class="save-status">Aucune modification</div><div id="draftState" class="hint">Brouillon automatique</div></div><div class="toolbar"><button id="saveButton" class="btn primary" type="submit">Envoyer l'embed</button></div></div></form></main><div id="toast" class="toast hidden" role="status" aria-live="polite"></div>
<script>""" + BASE_JS + EMBED_JS + ADAPTER_JS + """</script></body></html>"""


async def handle_embed_center(request: web.Request) -> web.Response:
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login")
    return web.Response(
        text=EMBED_CENTER_HTML,
        content_type="text/html",
        headers={
            "Cache-Control": "private, no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def install(dashboard) -> None:
    """Ajoute une page séparée et l'API d'envoi sans toucher au script principal."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_security_headers = dashboard.security_headers

    @web.middleware
    async def security_headers(request: web.Request, handler):
        response = await original_security_headers(request, handler)
        csp = response.headers.get("Content-Security-Policy", "")
        response.headers["Content-Security-Policy"] = csp.replace(
            "img-src 'self' https://cdn.discordapp.com data:",
            "img-src 'self' https: data:",
        )
        return response

    dashboard.security_headers = security_headers
    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/embed-builder", handle_embed_center)
        app.router.add_post("/api/guilds/{guild_id}/embeds", handle_send_embed)
        return app

    dashboard.build_app = build_app
    logger.info("Créateur d'embeds isolé chargé.")
