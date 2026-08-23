"""Dashboard V36 — centre compact des fonctionnalités SentriX.

Expose dans /app les systèmes déjà présents dans le bot sans dupliquer leur logique.
Les interrupteurs réutilisent les API existantes Argent/Niveaux/Mini-jeux ; les autres
cartes ouvrent les onglets ou centres spécialisés déjà sécurisés par OAuth/admin/CSRF.
"""
from __future__ import annotations

import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.feature-control-v36")
_INSTALLED = False


CSS = r"""
<style id="sentrix-feature-control-v36-css">
  #sentrixFeatureControlV36{grid-column:1/-1;display:grid;gap:10px;margin:0 0 4px}
  .sx-fc-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;padding:12px 13px;border:1px solid #283047;border-radius:11px;background:#0f141e}
  .sx-fc-head h3{margin:0;color:#f0eef5;font-size:15px}.sx-fc-head p{margin:3px 0 0;color:#7f889b;font-size:10px;line-height:1.45}
  .sx-fc-head button{min-height:31px;padding:0 10px;border:1px solid #343d52;border-radius:8px;background:#171d29;color:#dcd9e4;font-size:9px;font-weight:800;cursor:pointer}
  .sx-fc-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
  .sx-fc-card{min-width:0;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;align-items:center;min-height:72px;padding:10px 11px;border:1px solid #252d40;border-radius:10px;background:#0f141e}
  .sx-fc-main{min-width:0}.sx-fc-main b{display:block;color:#eceaf2;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sx-fc-main span{display:block;margin-top:3px;color:#7d8698;font-size:9px;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sx-fc-actions{display:flex;align-items:center;justify-content:flex-end;gap:5px;flex-wrap:wrap}
  .sx-fc-btn,.sx-fc-link{display:inline-flex;align-items:center;justify-content:center;min-height:29px;padding:0 8px;border:1px solid #343d52;border-radius:7px;background:#171d29;color:#dcd9e4;font-size:8px;font-weight:850;text-decoration:none;cursor:pointer;white-space:nowrap}
  .sx-fc-btn.primary,.sx-fc-link.primary{border-color:#6954c5;background:#261f43;color:#cbbdff}
  .sx-fc-pill{display:inline-flex;align-items:center;justify-content:center;min-width:48px;min-height:24px;padding:0 7px;border:1px solid #343d52;border-radius:999px;background:#171d29;color:#aeb7c8;font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.04em}
  .sx-fc-pill.on{border-color:#396351;background:#14251e;color:#87d5ad}.sx-fc-pill.warn{border-color:#67542f;background:#271f11;color:#dfbc69}
  .sx-fc-switch{position:relative;width:39px;height:23px;border:1px solid #394158;border-radius:999px;background:#242b3b;cursor:pointer;padding:0}.sx-fc-switch::after{content:"";position:absolute;width:15px;height:15px;left:3px;top:3px;border-radius:50%;background:#eef0f7;transition:.14s}.sx-fc-switch.on{background:#6958d5;border-color:#7d6be7}.sx-fc-switch.on::after{left:19px}.sx-fc-switch:disabled{opacity:.45;cursor:not-allowed}
  .sx-fc-error{padding:10px 12px;border:1px solid #67333a;border-radius:9px;background:#281519;color:#e99aa3;font-size:10px}
  @media(max-width:1050px){.sx-fc-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:650px){.sx-fc-grid{grid-template-columns:1fr}.sx-fc-head{align-items:flex-start}.sx-fc-card{min-height:64px}}
</style>
"""


JS = r"""
<script id="sentrix-feature-control-v36-js">
(() => {
  "use strict";
  if (window.__sentrixFeatureControlV36) return;
  window.__sentrixFeatureControlV36 = true;

  let guild="", loading=false, summary=null, systems=null, setup=null;

  const gid=()=>{try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return"";}};
  const csrf=()=>{try{return typeof state!=="undefined"?state.csrf||"":"";}catch(_){return"";}};
  const simpleHome=()=>document.body.classList.contains("sx-simple-home-active")&&Boolean(document.getElementById("sxSimpleHome"));
  const active=()=>{try{return simpleHome()||(typeof state!=="undefined"&&state.tab==="general");}catch(_){return false;}};
  const notify=(m,b=false)=>{try{if(typeof toast==="function")return toast(m,b);}catch(_){}(b?console.error:console.info)(m);};
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  function root(){
    if(!active()){document.getElementById("sentrixFeatureControlV36")?.remove();return null;}
    let target=null, before=null;
    if(simpleHome()){
      target=document.getElementById("sxSimpleHome");
      before=target?.querySelector(".sx-simple-steps")||null;
    }else{
      target=document.getElementById("fields");
    }
    if(!target)return null;
    let el=document.getElementById("sentrixFeatureControlV36");
    if(!el){
      el=document.createElement("section");el.id="sentrixFeatureControlV36";
      if(before)target.insertBefore(el,before);else target.prepend(el);
    }else if(el.parentNode!==target){
      if(before)target.insertBefore(el,before);else target.prepend(el);
    }
    return el;
  }
  function openTab(name){
    const button=document.querySelector(`#navigation button[data-tab="${name}"]`);
    if(button){
      document.body.classList.remove("sx-simple-home-active");
      document.body.classList.add("sx-simple-detail");
      document.getElementById("sxSimpleHome")?.classList.add("hidden");
      button.click();
      window.scrollTo({top:0,behavior:"smooth"});
      return;
    }
    notify("Cette section n'est pas disponible dans ce mode du dashboard.",true);
  }
  function navButton(tab,label){return `<button class="sx-fc-btn primary" type="button" data-fc-tab="${esc(tab)}">${esc(label)}</button>`;}
  function pageButton(url,label){const sep=url.includes("?")?"&":"?";const href=gid()?`${url}${sep}guild=${encodeURIComponent(gid())}`:url;return `<a class="sx-fc-link primary" href="${esc(href)}">${esc(label)}</a>`;}
  function stat(on,onText="Actif",offText="Inactif"){return `<span class="sx-fc-pill ${on?"on":""}">${on?esc(onText):esc(offText)}</span>`;}
  function toggle(feature,on){return `<button class="sx-fc-switch ${on?"on":""}" type="button" role="switch" aria-checked="${on?"true":"false"}" data-fc-toggle="${feature}" title="${on?"Désactiver":"Activer"}"></button>`;}
  function card(title,detail,actions){return `<article class="sx-fc-card"><div class="sx-fc-main"><b>${esc(title)}</b><span>${esc(detail)}</span></div><div class="sx-fc-actions">${actions}</div></article>`;}

  function render(){
    const el=root(); if(!el||!summary||!systems||!setup)return;
    const m=summary.metrics||{}, game=setup.games||{}, verification=setup.verification||{};
    const automod=Number(summary.automod_active||0), verify=Boolean(verification.role_id&&verification.channel_id);
    el.innerHTML=`
      <div class="sx-fc-head"><div><h3>Centre des fonctionnalités</h3><p>Les fonctions importantes du bot sont réunies ici. Les réglages détaillés restent accessibles en un clic.</p></div><button id="sxFcRefresh" type="button">Actualiser</button></div>
      <div class="sx-fc-grid">
        ${card("Argent & boutiques",`${Number(m.economy_accounts||0)} compte(s) · ${Number(m.shop_items||0)} article(s)`,toggle("economy",Boolean(systems.economy_enabled))+pageButton("/setup-center","Gérer"))}
        ${card("Niveaux & XP",`${Number(m.level_profiles||0)} profil(s) · ${Number(m.level_roles||0)} rôle(s) de palier`,toggle("levels",Boolean(systems.levels_enabled))+navButton("levels","Gérer"))}
        ${card("Mini-jeux",`${Number(m.game_players||0)} joueur(s) enregistré(s)`,toggle("games",Boolean(game.enabled))+pageButton("/setup-center","Gérer"))}
        ${card("Sécurité & AutoMod",`${automod}/11 protections actives`,stat(automod>0,`${automod}/11`,"OFF")+navButton("security","Gérer"))}
        ${card("Tickets",`${Number(m.open_tickets||0)} ouvert(s) · ${Number(m.unclaimed_tickets||0)} non pris`,stat(Number(m.open_tickets||0)>0,"Actif","0 ouvert")+navButton("tickets","Gérer"))}
        ${card("Logs & sanctions",`${Number(m.sanctions_24h||0)} sanction(s) sur 24 h`,navButton("logs","Logs")+navButton("sanctions","Sanctions"))}
        ${card("IA SentriX","Modèles, mémoire, limites et journalisation",navButton("ai","Configurer"))}
        ${card("Accueil & vérification",verify?"Panel de vérification configuré":"Vérification à configurer",stat(verify,"Prêt","À régler")+navButton("roles","Gérer"))}
        ${card("Notifications sociales",`${Number(m.social_notifications||0)} surveillance(s) active(s)`,navButton("notifications","Gérer"))}
        ${card("Engagement",`${Number(m.active_events||0)} événement(s) · ${Number(m.active_giveaways||0)} giveaway(s)`,pageButton("/engagement","Ouvrir"))}
        ${card("Opérations & commandes",`${Number(m.custom_commands||0)} commande(s) custom · ${Number(setup.disabled_commands?.length||0)} désactivée(s)`,pageButton("/operations","Opérations")+pageButton("/setup-center","Commandes"))}
        ${card("Communauté & embeds",`${Number(m.role_panels||0)} panel(s) de rôles · création de messages`,pageButton("/community","Communauté")+pageButton("/embed-builder","Embeds"))}
      </div>`;
    document.getElementById("sxFcRefresh")?.addEventListener("click",()=>load(gid(),true));
    el.querySelectorAll("[data-fc-tab]").forEach(b=>b.addEventListener("click",()=>openTab(b.dataset.fcTab)));
    el.querySelectorAll("[data-fc-toggle]").forEach(b=>b.addEventListener("click",()=>changeToggle(b.dataset.fcToggle,b)));
  }

  async function apiJson(url,options={}){
    const response=await fetch(url,{credentials:"same-origin",cache:"no-store",...options});
    const body=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(body.error||"Action impossible.");
    return body;
  }

  async function load(id,force=false){
    if(!id||loading)return;
    if(!force&&guild===id&&summary&&systems&&setup){render();return;}
    loading=true; const el=root(); if(el)el.innerHTML='<div class="sx-fc-error">Chargement du centre des fonctionnalités…</div>';
    try{
      const [a,b,c]=await Promise.all([
        apiJson(`/api/guilds/${id}/feature-control-v36`),
        apiJson(`/api/guilds/${id}/systems`),
        apiJson(`/api/guilds/${id}/setup-tools`)
      ]);
      if(gid()!==id||!active())return;
      guild=id; summary=a; systems=b.systems||b; setup=c; render();
    }catch(error){
      if(el)el.innerHTML=`<div class="sx-fc-error">${esc(error.message||"Impossible de charger les fonctionnalités.")}</div>`;
      notify(error.message||"Impossible de charger les fonctionnalités.",true);
    }finally{loading=false;}
  }

  async function changeToggle(feature,button){
    const id=gid(); if(!id||button.disabled)return;
    document.querySelectorAll("#sentrixFeatureControlV36 [data-fc-toggle]").forEach(x=>x.disabled=true);
    try{
      if(feature==="economy"||feature==="levels"){
        const key=feature==="economy"?"economy_enabled":"levels_enabled";
        const next=!Boolean(systems[key]);
        const data=await apiJson(`/api/guilds/${id}/systems`,{
          method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},
          body:JSON.stringify({[key]:next})
        });
        systems=data.systems||data;
        notify(data.message||"Système mis à jour.");
      }else if(feature==="games"){
        const current=setup.games||{};
        const payload={...current,enabled:!Boolean(current.enabled)};
        const data=await apiJson(`/api/guilds/${id}/games`,{
          method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},
          body:JSON.stringify(payload)
        });
        setup.games=data.games||payload;
        notify(data.message||"Mini-jeux mis à jour.");
      }
      render();
    }catch(error){notify(error.message||"Modification impossible.",true);}
    finally{document.querySelectorAll("#sentrixFeatureControlV36 [data-fc-toggle]").forEach(x=>x.disabled=false);}
  }

  let last="";
  const tick=()=>{
    const id=gid(), key=`${id}:${active()?"general":"other"}`;
    if(!id||!active()){document.getElementById("sentrixFeatureControlV36")?.remove();last=key;return;}
    if(key!==last||guild!==id||!summary){last=key;summary=null;systems=null;setup=null;load(id,true);return;}
    if(!document.getElementById("sentrixFeatureControlV36"))render();
  };
  setInterval(tick,650);window.addEventListener("pageshow",tick);setTimeout(tick,160);
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-feature-control-v36-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    return html


async def _count(db, sql: str, params: tuple) -> int:
    try:
        row = await db.fetchone(sql, params)
        return int(row["n"] if row else 0)
    except Exception:
        return 0


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    async def feature_control(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error

        bot = request.app["bot"]
        db = bot.db
        current = int(time.time())
        try:
            automod = await db.get_automod(guild_id)
        except Exception:
            automod = None
        automod_keys = (
            "antispam", "antilink", "antiinvite", "antimention", "anticaps",
            "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
        )
        automod_active = sum(1 for key in automod_keys if automod and bool(automod[key]))

        metrics = {
            "economy_accounts": await _count(db, "SELECT COUNT(*) AS n FROM economy WHERE guild_id = ?", (guild_id,)),
            "shop_items": await _count(db, "SELECT COUNT(*) AS n FROM shop_items WHERE guild_id = ?", (guild_id,)),
            "level_profiles": await _count(db, "SELECT COUNT(*) AS n FROM levels WHERE guild_id = ?", (guild_id,)),
            "level_roles": await _count(db, "SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (guild_id,)),
            "game_players": await _count(db, "SELECT COUNT(DISTINCT user_id) AS n FROM game_stats WHERE guild_id = ?", (guild_id,)),
            "open_tickets": await _count(db, "SELECT COUNT(*) AS n FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (guild_id,)),
            "unclaimed_tickets": await _count(db, "SELECT COUNT(*) AS n FROM tickets WHERE guild_id = ? AND status = 'ouvert' AND claimed_by IS NULL", (guild_id,)),
            "sanctions_24h": await _count(db, "SELECT COUNT(*) AS n FROM sanctions WHERE guild_id = ? AND created_at >= ?", (guild_id, current - 86400)),
            "social_notifications": await _count(db, "SELECT COUNT(*) AS n FROM social_notifications WHERE guild_id = ? AND enabled = 1", (guild_id,)),
            "active_events": await _count(db, "SELECT COUNT(*) AS n FROM events WHERE guild_id = ? AND status IN ('planifie','actif')", (guild_id,)),
            "active_giveaways": await _count(db, "SELECT COUNT(*) AS n FROM giveaways WHERE guild_id = ? AND status = 'actif'", (guild_id,)),
            "custom_commands": await _count(db, "SELECT COUNT(*) AS n FROM custom_commands_v2 WHERE guild_id = ? AND enabled = 1", (guild_id,)),
            "role_panels": (
                await _count(db, "SELECT COUNT(*) AS n FROM reaction_role_panels WHERE guild_id = ?", (guild_id,))
                + await _count(db, "SELECT COUNT(*) AS n FROM self_role_panels WHERE guild_id = ?", (guild_id,))
            ),
        }
        return web.json_response({
            "ok": True,
            "guild_id": str(guild.id),
            "automod_active": automod_active,
            "metrics": metrics,
        })

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/feature-control-v36", feature_control)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Centre compact des fonctionnalités V36 ajouté au dashboard principal.")
