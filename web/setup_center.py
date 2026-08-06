"""Centre Setup isolé du dashboard SentriX.

Cette page possède son propre JavaScript et ne modifie jamais le script principal du
dashboard. Une erreur dans ce centre ne peut donc plus bloquer les autres onglets.
"""

from __future__ import annotations

import logging

from aiohttp import web

from database.db import MANAGER_CATEGORIES as DB_MANAGER_CATEGORIES

logger = logging.getLogger("bot.dashboard.setup-center")
_INSTALLED = False


async def handle_setup_center(request: web.Request) -> web.Response:
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login")
    return web.Response(
        text=SETUP_CENTER_HTML,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


SETUP_CENTER_HTML = r"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#090b12">
  <title>SentriX — Centre Setup</title>
  <style>
    :root{--bg:#090b12;--panel:#111522;--panel2:#171c2c;--line:#262d43;--text:#f2f4ff;--muted:#949db5;--brand:#7c6cff;--ok:#44d39a;--bad:#ff667d;--warn:#f2bd5a}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% -10%,#33266b55,transparent 35%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}button,input,select,textarea{font:inherit}a{color:inherit;text-decoration:none}.hidden{display:none!important}
    .top{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 4vw;border-bottom:1px solid var(--line);background:#090b12ed;backdrop-filter:blur(12px)}.brand{font-size:19px;font-weight:900}.actions{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.btn{border:1px solid var(--line);border-radius:11px;padding:10px 14px;background:var(--panel2);color:var(--text);cursor:pointer;font-weight:800}.btn:hover{border-color:#596485}.btn.primary{background:linear-gradient(135deg,var(--brand),#5e4ee5);border-color:transparent}.btn.danger{background:#3a1520;border-color:#713044;color:#ff9aaa}.btn.small{padding:7px 10px;font-size:12px}.btn:disabled{opacity:.45;cursor:not-allowed}
    main{max-width:1280px;margin:0 auto;padding:30px 24px 70px}.head{display:grid;grid-template-columns:1fr minmax(260px,420px);gap:18px;align-items:end;margin-bottom:22px}.head h1{margin:0 0 7px;font-size:32px}.head p{margin:0;color:var(--muted)}.field label{display:block;font-weight:800;margin-bottom:7px}.field small{display:block;color:var(--muted);margin-top:6px;line-height:1.45}.select,input,textarea{width:100%;background:#0c101a;border:1px solid var(--line);color:var(--text);border-radius:11px;padding:11px 12px;outline:none}.select:focus,input:focus,textarea:focus{border-color:var(--brand)}textarea{min-height:95px;resize:vertical}select[multiple]{min-height:150px}
    .tabs{display:flex;gap:8px;overflow:auto;margin:20px 0}.tab{white-space:nowrap}.tab.active{background:var(--brand);border-color:transparent}.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden}.panel-head{padding:20px 22px;border-bottom:1px solid var(--line)}.panel-head h2{margin:0 0 5px}.panel-head p{margin:0;color:var(--muted)}.content{padding:22px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.full{grid-column:1/-1}.card{padding:16px;background:#0d111c;border:1px solid #222940;border-radius:14px;display:grid;gap:12px;align-content:start}.card h3{margin:0}.card p{margin:0;color:var(--muted);font-size:12px;line-height:1.5}.row{display:flex;gap:9px;align-items:end;flex-wrap:wrap}.row>.field{flex:1 1 190px}.checks{display:flex;gap:8px;flex-wrap:wrap}.check{display:flex;gap:7px;align-items:center;padding:9px 10px;background:#111725;border:1px solid #2b3450;border-radius:10px}.check input{width:auto}.list{display:grid;gap:8px;max-height:260px;overflow:auto}.item{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px;background:#111725;border:1px solid #252e45;border-radius:10px}.item span{min-width:0;overflow:hidden;text-overflow:ellipsis}.muted{color:var(--muted)}.status{padding:12px 14px;border:1px solid #315b4e;background:#12332b;color:#8be4c3;border-radius:11px;margin-bottom:16px}.status.bad{border-color:#713044;background:#2c141c;color:#ff9aaa}.savebar{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin-top:18px}.danger-card{border-color:#713044;background:#24131a}.preview{border-left:5px solid var(--preview,#5865f2)}.progress{font-size:18px;overflow-wrap:anywhere}.loading{opacity:.55;pointer-events:none}
    @media(max-width:850px){.head,.grid{grid-template-columns:1fr}.full{grid-column:auto}}
  </style>
</head>
<body>
  <header class="top"><div class="brand">🛡️ SentriX — Centre Setup</div><div class="actions"><a class="btn" href="/app">← Dashboard principal</a><button class="btn" id="reload">Actualiser</button></div></header>
  <main>
    <div class="head"><div><h1>Configuration avancée</h1><p>Mini-jeux, design et outils Setup, isolés du dashboard principal.</p></div><div class="field"><label>Serveur</label><select id="guild" class="select"><option>Chargement…</option></select></div></div>
    <div class="tabs"><button class="btn tab active" data-tab="games">🎮 Mini-jeux</button><button class="btn tab" data-tab="design">🎨 Design</button><button class="btn tab" data-tab="advanced">⚙️ Setup avancé</button></div>
    <div id="status" class="status hidden"></div>
    <section class="panel"><div class="panel-head"><h2 id="title">Mini-jeux</h2><p id="description">Réglages complets de +gamesetup.</p></div><div id="content" class="content"><div class="muted">Choisissez un serveur.</div></div></section>
  </main>
  <script>
    const state={csrf:"",guilds:[],guildId:"",guildData:null,setup:null,design:null,tab:"games"};
    const $=id=>document.getElementById(id);
    const esc=value=>String(value??"").replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
    async function api(url,options={}){const response=await fetch(url,options);let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.error||"Une erreur est survenue.");return data;}
    function message(text,bad=false){const box=$("status");box.textContent=text;box.className=`status${bad?" bad":""}`;box.classList.remove("hidden");clearTimeout(message.timer);message.timer=setTimeout(()=>box.classList.add("hidden"),5000);}
    function selected(id){return [...$(id).selectedOptions].map(option=>option.value);}
    function channelOptions(current="",types=null){const channels=(state.guildData?.channels||[]).filter(channel=>!types||types.includes(channel.type));return '<option value="">Non configuré</option>'+channels.map(channel=>`<option value="${esc(channel.id)}" ${String(current)===String(channel.id)?"selected":""}>${esc(channel.name)} — ${esc(channel.type)}</option>`).join("");}
    function roleOptions(current=""){return '<option value="">Non configuré</option>'+(state.guildData?.roles||[]).map(role=>`<option value="${esc(role.id)}" ${String(current)===String(role.id)?"selected":""}>${esc(role.name)}</option>`).join("");}
    function multiOptions(items,values=[]){const set=new Set((values||[]).map(String));return items.map(item=>`<option value="${esc(item.id)}" ${set.has(String(item.id))?"selected":""}>${esc(item.name)}</option>`).join("");}
    function boolCard(id,label,checked,hint=""){return `<label class="check"><input id="${id}" type="checkbox" ${checked?"checked":""}><span><b>${esc(label)}</b>${hint?`<small class="muted">${esc(hint)}</small>`:""}</span></label>`;}
    async function boot(){try{const me=await api('/api/me');state.csrf=me.csrf;const data=await api('/api/guilds');state.guilds=data.guilds.filter(guild=>guild.installed);$("guild").innerHTML='<option value="">Choisissez un serveur</option>'+state.guilds.map(guild=>`<option value="${esc(guild.id)}">${esc(guild.name)}</option>`).join("");if(state.guilds[0]){$("guild").value=state.guilds[0].id;await loadGuild(state.guilds[0].id);}}catch(error){message(error.message,true);setTimeout(()=>location.href='/app',1200);}}
    async function loadGuild(id){if(!id)return;state.guildId=id;$("content").classList.add("loading");try{const [guildData,setupData,designData]=await Promise.all([api(`/api/guilds/${id}`),api(`/api/guilds/${id}/setup-tools`),api(`/api/guilds/${id}/design`)]);state.guildData=guildData;state.setup=setupData;state.design=designData.design;render();}catch(error){message(error.message,true);}finally{$("content").classList.remove("loading");}}
    function render(){if(!state.guildId)return;if(state.tab==="games")renderGames();else if(state.tab==="design")renderDesign();else renderAdvanced();}
    function renderGames(){const g=state.setup.games||{};$("title").textContent="Mini-jeux";$("description").textContent="Toutes les options de +gamesetup.";const gameItems=(state.setup.game_names||[]).map(name=>({id:name,name:name}));const channels=state.guildData.channels||[],roles=state.guildData.roles||[];$("content").innerHTML=`<div class="grid">
      <div class="card full"><h3>Activation et affichage</h3><div class="checks">${boolCard("game_enabled","Activer les mini-jeux",g.enabled)}${boolCard("game_logs","Activer les logs",g.logs_enabled)}${boolCard("game_board","Activer le classement",g.leaderboard_enabled)}${boolCard("game_dm","Résultats en MP",g.dm_results)}${boolCard("game_compact","Mode compact",g.compact_mode)}</div></div>
      <div class="field"><label>Limite quotidienne</label><input id="game_daily" type="number" min="0" max="10000" value="${esc(g.daily_limit??50)}"></div>
      <div class="field"><label>Difficulté par défaut</label><select id="game_difficulty" class="select"><option value="facile" ${g.default_difficulty==="facile"?"selected":""}>Facile</option><option value="normal" ${g.default_difficulty==="normal"?"selected":""}>Normale</option><option value="difficile" ${g.default_difficulty==="difficile"?"selected":""}>Difficile</option></select></div>
      <div class="field"><label>Multiplicateur événement</label><input id="game_event" type="number" min="0" max="100" step="0.1" value="${esc(g.event_multiplier??1)}"></div>
      <div class="field"><label>Multiplicateur minimum</label><input id="game_min" type="number" min="0" max="100" step="0.1" value="${esc(g.min_reward_multiplier??1)}"></div>
      <div class="field"><label>Multiplicateur maximum</label><input id="game_max" type="number" min="0" max="100" step="0.1" value="${esc(g.max_reward_multiplier??1)}"></div>
      <div class="field"><label>Jeux désactivés</label><select id="game_disabled" class="select" multiple>${multiOptions(gameItems,g.disabled_games)}</select></div>
      <div class="field"><label>Salons autorisés</label><select id="game_allowed_channels" class="select" multiple>${multiOptions(channels,g.allowed_channel_ids)}</select></div>
      <div class="field"><label>Salons bloqués</label><select id="game_blocked_channels" class="select" multiple>${multiOptions(channels,g.blocked_channel_ids)}</select></div>
      <div class="field"><label>Rôles autorisés</label><select id="game_allowed_roles" class="select" multiple>${multiOptions(roles,g.allowed_role_ids)}</select></div>
      <div class="field"><label>Rôles bloqués</label><select id="game_blocked_roles" class="select" multiple>${multiOptions(roles,g.blocked_role_ids)}</select></div>
      <div class="savebar full"><button class="btn primary" id="saveGames">Enregistrer les mini-jeux</button></div></div>`;$("saveGames").onclick=saveGames;}
    async function saveGames(){const payload={enabled:$("game_enabled").checked,logs_enabled:$("game_logs").checked,leaderboard_enabled:$("game_board").checked,dm_results:$("game_dm").checked,compact_mode:$("game_compact").checked,daily_limit:$("game_daily").value,event_multiplier:$("game_event").value,min_reward_multiplier:$("game_min").value,max_reward_multiplier:$("game_max").value,default_difficulty:$("game_difficulty").value,disabled_games:selected("game_disabled"),allowed_channel_ids:selected("game_allowed_channels"),blocked_channel_ids:selected("game_blocked_channels"),allowed_role_ids:selected("game_allowed_roles"),blocked_role_ids:selected("game_blocked_roles")};try{const result=await api(`/api/guilds/${state.guildId}/games`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(payload)});state.setup.games=result.games;message(result.message);}catch(error){message(error.message,true);}}
    function hex(value){return `#${Number(value||0).toString(16).padStart(6,"0").slice(-6)}`;}
    function renderDesign(){const d=state.design||{};$("title").textContent="Design";$("description").textContent="Couleurs, footer et apparence de +designsetup.";$("content").innerHTML=`<div class="grid">
      ${[["primary_color","Couleur principale"],["secondary_color","Couleur secondaire"],["success_color","Couleur succès"],["warning_color","Couleur avertissement"],["danger_color","Couleur erreur"]].map(([key,label])=>`<div class="field"><label>${label}</label><input id="design_${key}" type="color" value="${hex(d[key])}"></div>`).join("")}
      <div class="field full"><label>Footer</label><input id="design_footer" maxlength="100" value="${esc(d.footer||"SentriX")}"></div>
      <div class="field"><label>Longueur de la progression</label><input id="design_length" type="number" min="3" max="30" value="${esc(d.progress_length??10)}"></div>
      <div class="field"><label>Symbole rempli</label><input id="design_filled" maxlength="16" value="${esc(d.progress_filled||"🟪")}"></div>
      <div class="field"><label>Symbole vide</label><input id="design_empty" maxlength="16" value="${esc(d.progress_empty||"⬛")}"></div>
      <div class="card full"><div class="checks">${boolCard("design_avatars","Afficher les avatars",d.show_avatars)}${boolCard("design_compact","Mode compact",d.compact_mode)}${boolCard("design_charts","Activer les graphiques",d.charts_enabled)}</div></div>
      <div class="card preview full" id="designPreview"><h3>Aperçu</h3><p id="designPreviewFooter"></p><div class="progress" id="designProgress"></div></div>
      <div class="savebar full"><button class="btn primary" id="saveDesign">Enregistrer le design</button></div></div>`;document.querySelectorAll('[id^="design_"]').forEach(element=>element.addEventListener("input",updatePreview));$("saveDesign").onclick=saveDesign;updatePreview();}
    function updatePreview(){const box=$("designPreview");if(!box)return;box.style.setProperty("--preview",$("design_primary_color").value);$("designPreviewFooter").textContent=$("design_footer").value;const length=Math.max(3,Math.min(30,Number($("design_length").value||10))),active=Math.max(1,Math.round(length*.7));$("designProgress").textContent=$("design_filled").value.repeat(active)+$("design_empty").value.repeat(length-active);}
    async function saveDesign(){const payload={primary_color:$("design_primary_color").value,secondary_color:$("design_secondary_color").value,success_color:$("design_success_color").value,warning_color:$("design_warning_color").value,danger_color:$("design_danger_color").value,footer:$("design_footer").value,progress_length:$("design_length").value,progress_filled:$("design_filled").value,progress_empty:$("design_empty").value,show_avatars:$("design_avatars").checked,compact_mode:$("design_compact").checked,charts_enabled:$("design_charts").checked};try{const result=await api(`/api/guilds/${state.guildId}/design`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(payload)});state.design=result.design;message(result.message);}catch(error){message(error.message,true);}}
    function list(items,renderer,empty="Aucun élément configuré."){return items?.length?`<div class="list">${items.map(renderer).join("")}</div>`:`<div class="muted">${esc(empty)}</div>`;}
    function renderAdvanced(){const s=state.setup;$("title").textContent="Setup avancé";$("description").textContent="Commandes, exemptions, vérification, gestionnaires, logs et réinitialisation.";const disabled=new Set(s.disabled_commands||[]),ignored=new Set((s.ignored_channels||[]).map(String)),exempt=new Set((s.automod_exempt_roles||[]).map(String));$("content").innerHTML=`<div class="grid">
      <div class="card"><h3>Commandes</h3><p>Désactivez ou réactivez une commande sur ce serveur.</p><div class="row"><div class="field"><select id="commandSelect" class="select">${s.commands.map(command=>`<option value="${esc(command.name)}" ${command.protected?"disabled":""}>+${esc(command.name)}${disabled.has(command.name)?" — désactivée":""}${command.protected?" — protégée":""}</option>`).join("")}</select></div><button class="btn" id="toggleCommand">Changer l'état</button></div></div>
      <div class="card"><h3>Salons ignorés</h3><p>Les commandes configurables ne fonctionneront pas dans ces salons.</p><div class="row"><div class="field"><select id="ignoredChannel" class="select">${channelOptions("",null)}</select></div><button class="btn" id="toggleIgnored">Ajouter / retirer</button></div>${list([...ignored],id=>`<div class="item"><span>${esc(state.guildData.channels.find(c=>String(c.id)===id)?.name||id)}</span></div>`)}</div>
      <div class="card"><h3>Exemptions AutoMod</h3><div class="row"><div class="field"><select id="exemptRole" class="select">${roleOptions()}</select></div><button class="btn" id="toggleExempt">Ajouter / retirer</button></div>${list([...exempt],id=>`<div class="item"><span>${esc(state.guildData.roles.find(r=>String(r.id)===id)?.name||id)}</span></div>`)}</div>
      <div class="card"><h3>Liste blanche anti-nuke</h3><div class="row"><div class="field"><input id="whiteUser" placeholder="ID Discord du membre"></div><button class="btn" id="addWhite">Ajouter</button></div>${list(s.antinuke_whitelist,user=>`<div class="item"><span>${esc(user.name)}<small class="muted">${esc(user.id)}</small></span><button class="btn danger small" data-remove-white="${esc(user.id)}">Retirer</button></div>`)}</div>
      <div class="card full"><h3>Gestionnaires du bot</h3><p>Ils peuvent utiliser les catégories choisies, sans accéder aux autres serveurs.</p><div class="row"><div class="field"><input id="managerUser" placeholder="ID Discord du membre"></div><button class="btn" id="addManager">Ajouter / mettre à jour</button></div><div class="checks">${Object.entries(s.manager_categories).map(([key,label])=>`<label class="check"><input type="checkbox" data-manager-category="${esc(key)}" ${key==="complete"?"checked":""}>${esc(label)}</label>`).join("")}</div>${list(s.managers,user=>`<div class="item"><span>${esc(user.name)}<small class="muted">${esc(user.id)} · ${esc((user.categories||[]).join(", "))}</small></span><button class="btn danger small" data-remove-manager="${esc(user.id)}">Retirer</button></div>`)}</div>
      <div class="card"><h3>Créer les logs</h3><p>Crée automatiquement les salons de logs manquants.</p><button class="btn primary" id="createLogs">Créer et configurer les logs</button></div>
      <div class="card"><h3>Panneau de vérification</h3><div class="field"><label>Salon</label><select id="verifyChannel" class="select">${channelOptions(s.verification.channel_id,["text","news"])}</select></div><div class="field"><label>Rôle</label><select id="verifyRole" class="select">${roleOptions(s.verification.role_id)}</select></div><button class="btn primary" id="verifyPanel">Publier le panneau</button></div>
      <div class="card"><h3>Rôles de notification</h3><div class="field"><label>Salon</label><select id="selfRoleChannel" class="select">${channelOptions("",["text","news"])}</select></div><div class="field"><label>Titre</label><input id="selfRoleTitle" value="Choisissez vos notifications"></div><button class="btn primary" id="selfRolePanel">Publier le panneau</button></div>
      <div class="card"><h3>Historique Setup</h3>${list(s.history,item=>`<div class="item"><span><b>${esc(item.action||item.category||"Configuration")}</b><small class="muted">${esc(item.details||item.new_value||"")} · ${esc(item.user?.name||"")}</small></span></div>`)}</div>
      <div class="card danger-card full"><h3>Réinitialisation</h3><p>Écrivez exactement le nom du serveur pour confirmer.</p><div class="row"><div class="field"><select id="resetScope" class="select"><option value="commands">Commandes désactivées</option><option value="ignored">Salons ignorés</option><option value="games">Mini-jeux</option><option value="security">Sécurité</option><option value="all">Toute la configuration</option></select></div><div class="field"><input id="resetConfirm" placeholder="Nom exact du serveur"></div><button class="btn danger" id="resetSetup">Réinitialiser</button></div></div>
      </div>`;bindAdvanced(ignored,exempt);}
    async function action(payload){try{const result=await api(`/api/guilds/${state.guildId}/setup-tools`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(payload)});message(result.message);state.setup=await api(`/api/guilds/${state.guildId}/setup-tools`);renderAdvanced();}catch(error){message(error.message,true);}}
    function bindAdvanced(ignored,exempt){$("toggleCommand").onclick=()=>{const name=$("commandSelect").value;action({action:"command",command:name,enabled:(state.setup.disabled_commands||[]).includes(name)});};$("toggleIgnored").onclick=()=>{const id=$("ignoredChannel").value;if(id)action({action:"ignored_channel",channel_id:id,ignored:!ignored.has(String(id))});};$("toggleExempt").onclick=()=>{const id=$("exemptRole").value;if(id)action({action:"automod_exempt_role",role_id:id,exempt:!exempt.has(String(id))});};$("addWhite").onclick=()=>{const id=$("whiteUser").value.trim();if(id)action({action:"antinuke_whitelist",user_id:id,allowed:true});};document.querySelectorAll("[data-remove-white]").forEach(button=>button.onclick=()=>action({action:"antinuke_whitelist",user_id:button.dataset.removeWhite,allowed:false}));$("addManager").onclick=()=>{const categories=[...document.querySelectorAll("[data-manager-category]:checked")].map(input=>input.dataset.managerCategory),id=$("managerUser").value.trim();if(id)action({action:"manager",user_id:id,enabled:true,categories});};document.querySelectorAll("[data-remove-manager]").forEach(button=>button.onclick=()=>action({action:"manager",user_id:button.dataset.removeManager,enabled:false}));$("createLogs").onclick=()=>action({action:"create_logs"});$("verifyPanel").onclick=()=>action({action:"verify_panel",channel_id:$("verifyChannel").value,role_id:$("verifyRole").value});$("selfRolePanel").onclick=()=>action({action:"self_role_panel",channel_id:$("selfRoleChannel").value,title:$("selfRoleTitle").value});$("resetSetup").onclick=()=>action({action:"reset",scope:$("resetScope").value,confirmation:$("resetConfirm").value});}
    document.querySelectorAll("[data-tab]").forEach(button=>button.onclick=()=>{state.tab=button.dataset.tab;document.querySelectorAll("[data-tab]").forEach(item=>item.classList.toggle("active",item===button));render();});
    $("guild").onchange=event=>loadGuild(event.target.value);$("reload").onclick=()=>state.guildId&&loadGuild(state.guildId);boot();
  </script>
</body>
</html>"""


def _patch_dashboard_link(html: str) -> str:
    anchor = '      <div class="side-bottom">\n        <a class="btn primary" id="appInvite"'
    if anchor not in html:
        logger.warning("Centre Setup : impossible d'ajouter le lien au dashboard principal.")
        return html
    replacement = '      <div class="side-bottom">\n        <a class="btn" href="/setup-center">⚙️ Centre Setup</a>\n        <a class="btn primary" id="appInvite"'
    return html.replace(anchor, replacement, 1)


def install(dashboard, setup_dashboard, design_dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    setup_dashboard.MANAGER_CATEGORIES.clear()
    setup_dashboard.MANAGER_CATEGORIES.update(DB_MANAGER_CATEGORIES)
    dashboard.INDEX_HTML = _patch_dashboard_link(dashboard.INDEX_HTML)
    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/setup-center", handle_setup_center)
        app.router.add_get("/api/guilds/{guild_id}/setup-tools", setup_dashboard.handle_setup_data)
        app.router.add_post("/api/guilds/{guild_id}/setup-tools", setup_dashboard.handle_setup_action)
        app.router.add_put("/api/guilds/{guild_id}/games", setup_dashboard.handle_save_games)
        app.router.add_get("/api/guilds/{guild_id}/design", design_dashboard.handle_get_design)
        app.router.add_put("/api/guilds/{guild_id}/design", design_dashboard.handle_save_design)
        return app

    dashboard.build_app = build_app
    logger.info("Centre Setup isolé chargé.")
