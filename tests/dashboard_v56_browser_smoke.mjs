import fs from "node:fs";
import process from "node:process";
import { JSDOM, VirtualConsole } from "jsdom";

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error("usage: node dashboard_v56_browser_smoke.mjs <dashboard.html>");
const html = fs.readFileSync(htmlPath, "utf8");
const requests = [];
const runtimeErrors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", error => runtimeErrors.push(String(error?.stack || error)));
virtualConsole.on("error", (...args) => runtimeErrors.push(args.map(String).join(" ")));

const response = (payload, status = 200) => ({ ok: status >= 200 && status < 300, status, async json(){ return payload; } });
const diagnosticsPayload = {
  ok:true, score:86, summary:{active:8,inactive:1,missing:1,errors:0},
  modules:{
    welcome:{code:"active",detail:"Bienvenue configurée."}, levels:{code:"active",detail:"Niveaux configurés."},
    logs:{code:"active",detail:"Logs configurés."}, roles:{code:"active",detail:"Rôles configurés."},
    tickets:{code:"active",detail:"Tickets configurés."}, automod:{code:"active",detail:"AutoMod actif."},
    ai:{code:"inactive",detail:"IA désactivée."}, notifications:{code:"missing",detail:"Aucune source."},
    moderation:{code:"active",detail:"Permissions disponibles."},
  },
  permissions:[{key:"administrator",name:"Administrateur",granted:true},{key:"manage_roles",name:"Gérer les rôles",granted:true}],
  invalid_resources:[], bot:{id:"999",top_role_position:10},
};
const setupPayload = {
  ok:true,
  commands:[{name:"help",description:"Aide",protected:true},{name:"ban",description:"Bannir",protected:false},{name:"ticket",description:"Tickets",protected:false}],
  disabled_commands:["ticket"], managers:[], history:[],
};
const v62Payload = {
  ok:true,
  verification:{role_id:"15",channel_id:"22",captcha_enabled:true,captcha_max_attempts:3,rules_text:"1. Respectez les membres.\n2. Pas de spam.",image_url:"",message_id:null},
  tickets:{
    panels:[{id:1,guild_id:1,name:"Support",title:"Support",description:"Choisissez une option.",color:5088255,channel_id:23,message_id:null,style:"button",max_per_member:1,enabled:1}],
    types:[{id:2,panel_id:1,guild_id:1,name:"Support",description:"Besoin d'aide",use_form:1}],
    questions:[], buttons:{},
  },
};

const dom = new JSDOM(html, {
  url:"https://sentrix.test/app", runScripts:"dangerously", pretendToBeVisual:true, virtualConsole,
  beforeParse(window){
    window.fetch = async (input, options={}) => {
      const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
      const method = String(options.method || "GET").toUpperCase();
      requests.push({path:url.pathname,method});
      if(url.pathname==="/api/public") return response({ok:true,online:true,guilds:20,members:1000,latency_ms:42,uptime_seconds:3600,oauth_ready:true});
      if(url.pathname==="/api/me") return response({ok:true,user:{id:"42",username:"SentriX Test",avatar_url:null},csrf:"test-csrf"});
      if(url.pathname==="/api/guilds") return response({ok:true,guilds:[{id:"1",name:"Serveur Test",icon_url:null,installed:true}]});
      if(url.pathname==="/api/guilds/1") return response({
        ok:true,guild:{id:"1",name:"Serveur Test",members:12,channels_count:7,roles_count:7},
        metrics:{commands_24h:3,open_tickets:1,warnings:0,economy_accounts:2,profiles:4},
        settings:{prefix:"+",security_level:"moyen",warn_ban_threshold:3},automod:{antispam:1},ai:{enabled:1,default_model:"sol",reasoning_effort:"medium"},
        roles:[{id:"10",name:"Staff"},{id:"11",name:"Membre"},{id:"12",name:"Booster"},{id:"13",name:"Modérateur"},{id:"14",name:"Admin"},{id:"15",name:"Vérifié"}],
        channels:[{id:"20",name:"general",type:"text"},{id:"21",name:"logs",type:"text"},{id:"22",name:"reglement",type:"text"},{id:"23",name:"tickets",type:"text"},{id:"24",name:"reports",type:"text"},{id:"25",name:"staff",type:"text"},{id:"26",name:"Tickets",type:"category"}],
        social_notifications:[],
      });
      if(url.pathname==="/api/guilds/1/sanctions") return response({ok:true,sanctions:[],next_offset:null,total:0});
      if(url.pathname==="/api/guilds/1/diagnostics") return response(diagnosticsPayload);
      if(url.pathname==="/api/guilds/1/setup-tools") return method==="POST" ? response({ok:true,message:"Configuration appliquée."}) : response(setupPayload);
      if(url.pathname==="/api/guilds/1/v62") return method==="POST" ? response({ok:true,message:"Configuration V62 enregistrée.",panel_id:"1"}) : response(v62Payload);
      if(url.pathname==="/api/guilds/1/settings") return response({ok:true,message:"Configuration enregistrée."});
      if(url.pathname==="/api/guilds/1/notifications") return response({ok:true,message:"Notification ajoutée."});
      if(url.pathname==="/api/guilds/1/embeds") return response({ok:true,message:"Embed envoyé."});
      if(url.pathname==="/api/guilds/1/dm/apercu") return response({guild:{id:"1",name:"Serveur Test"},longueur_max:3500});
      if(url.pathname==="/api/guilds/1/dm/user") return response({resultat:"envoye",message:"Message envoyé.",bilan:{envoyes:1}});
      if(url.pathname==="/api/guilds/1/welcome") return method==="PUT" ? response({ok:true,message:"Présentation enregistrée."}) : response({ok:true,title:"Bienvenue sur {server}",show_avatar:true,show_member_count:true,mode:"embed",goodbye_mode:"embed",default_title:"Bienvenue sur {server}",default_text:"Bienvenue {member} !",variables:["{member}","{username}","{display_name}","{server}","{member_count}"]});
      if(url.pathname==="/api/guilds/1/welcome/test") return response({ok:true,message:"Test envoyé."});
      if(url.pathname==="/api/guilds/1/levels") return method==="PUT" ? response({ok:true,message:"Réglages des niveaux enregistrés."}) : response({ok:true,xp_min:10,xp_max:25,xp_cooldown:60,level_announce_enabled:true,level_keep_old_roles:false,xp_disabled_on_commands:false,xp_excluded_role_ids:[],xp_channel_disabled:[],roles:[{level:5,role_id:"15"}]});
      if(url.pathname==="/api/guilds/1/economy") return method==="PUT" ? response({ok:true,message:"Monnaie enregistrée."}) : response({ok:true,currency_singular:"Pièce",currency_plural:"Pièces",currency_symbol:"🪙",shop:[{id:1,name:"VIP",price:500,description:"",role_id:"15"}],panels:[],gains:{daily:200,weekly:1000,work_cooldown:3600,daily_cooldown:86400}});
      if(url.pathname==="/api/guilds/1/economy/games") return method==="PUT" ? response({ok:true,message:"Réglages des jeux enregistrés."}) : response({ok:true,settings:{enabled:true,disabled_games:[],allowed_channel_ids:[],blocked_channel_ids:[],allowed_role_ids:[],blocked_role_ids:[],daily_limit:50,logs_enabled:true,leaderboard_enabled:true,dm_results:false,compact_mode:false},catalog:[{key:"slots",label:"🎰 Machine à sous",kind:"rapide"}]});
      if(url.pathname==="/api/guilds/1/roles/messages") return response({ok:true,items:[{id:"555",author:"SentriX",mine:true,text:"Choisissez vos rôles",created_at:1700000000,reactions:2}]});
      if(url.pathname==="/api/guilds/1/roles") return response({ok:true,notification_roles:[{id:"15",name:"Ping annonces"}],notification_panels:[],reaction_panels:[],reaction_roles:[]});
      if(url.pathname==="/api/guilds/1/verification-v6") return response({ok:true,configured:true,published:false,captcha_enabled:true,channel_id:"22",role_id:"15",title:"Vérification",rules_text:"1. Respectez les membres.",image_url:null,jump_url:null});
      if(url.pathname==="/api/guilds/1/logs/config") return response({ok:true,routes:[
        {key:"moderation",label:"Modération",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"messages",label:"Messages",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"members",label:"Membres",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"channels",label:"Salons",channel_id:null,enabled:false,valid:false,problem:"aucun salon configuré"},
        {key:"roles",label:"Rôles",channel_id:null,enabled:false,valid:false,problem:"aucun salon configuré"},
        {key:"voice",label:"Vocal",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"server",label:"Serveur",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"tickets",label:"Tickets",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"automod",label:"AutoMod",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"spam",label:"Anti-Spam",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"raid",label:"Anti-Raid",channel_id:"21",enabled:true,valid:true,problem:null},
        {key:"resources",label:"Ressources",channel_id:null,enabled:false,valid:false,problem:"aucun salon configuré"},
        {key:"files",label:"Fichiers",channel_id:null,enabled:false,valid:false,problem:"aucun salon configuré"}
      ],events:[]});
      if(url.pathname==="/api/guilds/1/automation/reactions") return response({ok:true,items:[{id:1,channel_id:"22",channel_name:"général",mode:"all",keyword:"",emojis:["👍"],enabled:1}]});
      if(url.pathname==="/api/guilds/1/ops/overview") return response({ok:true,status:{discord_ready:true,latency_ms:42},diagnostics:[],history:[{id:1,changed_keys:["prefix"],created_at:1700000000,username:"Owner"}],staff:[],maintenance:{enabled:false,reason:""},policies:[]});
      if(url.pathname==="/api/guilds/1/ops/access") return response({ok:true,roles:[],tier:"admin"});
      if(url.pathname==="/api/guilds/1/ops/health") return response({ok:true,discord_ready:true,latency_ms:42,db_latency_ms:1});
      if(url.pathname==="/api/guilds/1/growth/invitations") return response({ok:true,items:[],total_uses:0});
      if(url.pathname==="/api/guilds/1/growth/webhooks") return response({ok:true,items:[]});
      if(url.pathname==="/api/guilds/1/product/analytics") return response({ok:true,analytics:{members:1000,commands_24h:3,open_tickets:0,automation_runs_24h:0,top_commands:[]}});
      if(url.pathname==="/api/guilds/1/live/metrics") return response({ok:true,online:true,latency_ms:42,members:1000,warnings:0,open_tickets:0,commands_24h:3});
      return response({error:`Route mock inconnue: ${url.pathname}`},404);
    };
    window.confirm=()=>true;window.prompt=()=>"Test dashboard";window.scrollTo=()=>{};
  },
});

const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
await sleep(2800);
const bootstrapPaths=requests.map(x=>x.path);
for(const required of ["/api/me","/api/guilds"]){
  if(!bootstrapPaths.includes(required)) throw new Error(`Bootstrap manquant: ${required}`);
}
if(bootstrapPaths.includes("/api/guilds/1")) throw new Error("Le dashboard ne doit plus auto-charger un serveur à l'ouverture.");

const dashboard=dom.window.document.getElementById("dashboard");
if(!dashboard||dashboard.classList.contains("hidden")) throw new Error("Dashboard masqué après session.");
if(!dom.window.document.body.classList.contains("dashboard-locked")) throw new Error("Le dashboard prêt doit verrouiller le scroll global.");
if(!dom.window.document.body.classList.contains("startup-done")) throw new Error("L’écran de démarrage doit se terminer après le bootstrap.");
const startupProgress=dom.window.document.getElementById("startupProgress");
if(startupProgress && Number(startupProgress.getAttribute("aria-valuenow") || 0) < 92) throw new Error("La barre de démarrage doit progresser par étapes jusqu'à la fin du bootstrap.");
if(!sourceByName.get('90_boot.js')?.includes('startupTarget = 4')) throw new Error('La barre de démarrage doit interpoler vers une cible au lieu de sauter.');
if(!sourceByName.get('90_boot.js')?.includes('elapsed >= 2200')) throw new Error('Le chargement SentriX est trop rapide : durée minimale fluide absente.');



if(!dom.window.document.getElementById("sentrix-dashboard-unified-v2")) throw new Error("Frontend unifié absent.");
if(!dom.window.document.getElementById("sentrix-unified-runtime-v2")) throw new Error("Runtime unifié absent.");
if(dom.window.document.querySelector("#sxFeaturesFrame,.sx-features-shell,#sentrix-v64-final")) throw new Error("Une ancienne couche frontend est encore embarquée.");

// Programme unique : un seul <script> exécutable, un seul <style>, aucune ancienne couche.
const executableScripts=[...dom.window.document.querySelectorAll("script")].filter(s=>s.type!=="application/json");
if(executableScripts.length!==1) throw new Error(`${executableScripts.length} scripts exécutables au lieu de 1.`);
if(dom.window.document.querySelectorAll("style").length!==1) throw new Error("Plusieurs feuilles de style embarquées.");
const responsiveCss=dom.window.document.querySelector("style").textContent;
for(const token of ["responsive universel v3","max-width:1024px","max-width:600px","pointer:coarse","safe-area-inset-bottom","100dvh","body.save-pending .workspace","sxPageIn 240ms","startup-screen","startup-progress","body.dashboard-locked",".workspace{"]){
  if(!responsiveCss.includes(token)) throw new Error(`Responsive universel incomplet: ${token}`);
}
dom.window.document.getElementById("mobileMenu").click();
if(!dom.window.document.body.classList.contains("nav-open")) throw new Error("Le menu mobile ne verrouille pas le scroll de la page.");
if(dom.window.document.getElementById("mobileOverlay").classList.contains("hidden")) throw new Error("Overlay mobile absent à l'ouverture.");
dom.window.document.getElementById("mobileOverlay").click();
if(dom.window.document.body.classList.contains("nav-open")) throw new Error("Le verrouillage mobile reste actif après fermeture.");


// Mode global : profil / serveurs / préférences uniquement. La configuration serveur
// n'apparaît qu'après un clic explicite sur une pastille de la colonne gauche.
const globalTabs=[...dom.window.document.querySelectorAll("#navigation button[data-tab]")].map(b=>b.dataset.tab);
for(const tab of ["profile","servers","preferences"]) if(!globalTabs.includes(tab)) throw new Error(`Page globale absente: ${tab}`);
for(const tab of ["overview","levels","economy","security","tickets"]) if(globalTabs.includes(tab)) throw new Error(`Page serveur visible avant sélection: ${tab}`);
if(!/Mon espace SentriX|Continuer sur un serveur/.test(dom.window.document.getElementById("content").textContent)) throw new Error("La page d'ouverture n'est pas le profil global.");

// Préférences globales : thèmes prêts + persistance locale.
dom.window.document.querySelector('#navigation button[data-tab="preferences"]').click();
await sleep(120);
for(const selector of ['#prefTheme','#prefAccentColor','#prefAccentHex','#themeSaveName','#themeSaveButton']){
  if(!dom.window.document.querySelector(selector)) throw new Error(`Préférences de thème incomplètes: ${selector}`);
}
const curatedButtons=[...dom.window.document.querySelectorAll('[data-curated-theme]')];
if(curatedButtons.length<12) throw new Error("Pas assez de thèmes prêts.");
if(dom.window.document.querySelector('.theme-advanced-editor')) throw new Error("L'éditeur de couleurs avancé doit être retiré.");
curatedButtons.find(b=>b.dataset.curatedTheme==="crimson")?.click();
await sleep(30);
if(dom.window.localStorage.getItem("sentrix:accent")!=="#ff4d67") throw new Error("Le thème Crimson Night ne s'applique pas.");
const appliedColors=JSON.parse(dom.window.localStorage.getItem("sentrix:theme-colors")||"{}");
if(appliedColors.bg!=="#030304") throw new Error("La palette prête n'est pas persistée.");
dom.window.document.getElementById("themeSaveName").value="Smoke Theme";
dom.window.document.getElementById("themeSaveButton").click();
await sleep(30);
const savedThemes=JSON.parse(dom.window.localStorage.getItem("sentrix:saved-themes")||"[]");
if(!savedThemes.some(x=>x.name==="Smoke Theme")) throw new Error("La sauvegarde d'un thème ne fonctionne pas.");
if(!dom.window.document.querySelector('[data-load-theme]')) throw new Error("Un thème enregistré doit être rechargeable.");
dom.window.localStorage.removeItem("sentrix:theme-colors");
dom.window.localStorage.removeItem("sentrix:saved-themes");

const railServer=dom.window.document.querySelector('#serverRail [data-guild="1"]');
if(!railServer) throw new Error("Serveur absent de la colonne de sélection.");
railServer.click();
await sleep(300);
if(!requests.map(x=>x.path).includes("/api/guilds/1")) throw new Error("Le clic serveur ne charge pas sa configuration.");

const expectedTabs=["overview","welcome","levels","economy","roles","moderation","security","logs","tickets","games","notifications","automation","embeds","ai","settings","access","invites","backups"];
const actualTabs=[...dom.window.document.querySelectorAll("#navigation button[data-tab]")].map(b=>b.dataset.tab);
for(const tab of expectedTabs) if(!actualTabs.includes(tab)) throw new Error(`Page unifiée absente après sélection serveur: ${tab}`);
if(actualTabs.includes("profile")||actualTabs.includes("servers")||actualTabs.includes("preferences")) throw new Error("Les pages globales ne doivent pas encombrer la navigation serveur.");
if(actualTabs.length>20) throw new Error(`Sidebar trop longue : ${actualTabs.length} entrées.`);

// [page, sous-section, sélecteur attendu]
const checks=[
  ["overview","",".module-card"], ["welcome","bienvenue",'[data-setting="welcome_message"]'], ["welcome","departs",'[data-setting="goodbye_message"]'],
  ["levels","general","#lvSave"], ["levels","levelup",'[data-setting="level_channel"]'], ["levels","roles","#lvRoleAdd"], ["levels","avance","#lvExRoles"],
  ["economy","general","#ecSave"], ["economy","boutique","#shopAdd"], ["economy","jeux","#gmEnabled"], ["economy","gains",".kpi"], ["roles","autoroles",'[data-setting="autorole"]'], ["roles","interactifs","#reactionPanelCreate"], ["roles","avance",'[data-setting="mod_role"]'],
  ["moderation","","#sanctionList"], ["security","protections","[data-automod]"], ["security","verification","#verifyRules"],
  ["logs","",'[data-log-channel]'], ["tickets","","#ticketSave"], ["notifications","","#notifAdd"], ["automation","","#reactCreate"],
  ["settings","",'[data-setting="prefix"]'], ["access","","#commandList"], ["embeds","","#embedSend"], ["ai","","[data-ai]"],
  ["invites","invites",".card"], ["backups","backups","#opsExport"], ["backups","history","[data-rollback]"],
];
for(const [tab,sub,selector] of checks){
  const button=dom.window.document.querySelector(`#navigation button[data-tab="${tab}"]`);
  if(!button) throw new Error(`Bouton de navigation absent: ${tab}`);
  button.click();
  await sleep(120);
  if(sub){ const sb=dom.window.document.querySelector(`#subnav [data-sub="${sub}"]`); if(!sb) throw new Error(`Sous-section absente: ${tab}/${sub}`); sb.click(); await sleep(120); }
  const currentButton=dom.window.document.querySelector(`#navigation button[data-tab="${tab}"]`);
  if(!currentButton?.classList.contains("active")) throw new Error(`L'onglet ${tab} ne devient pas actif.`);
  if(!dom.window.document.getElementById("pageTitle")?.textContent?.trim()) throw new Error(`Titre vide: ${tab}`);
  if(!dom.window.document.querySelector(selector)) throw new Error(`Contenu fonctionnel absent: ${tab}/${sub||"-"} (${selector})`);
}

const interactivePathsNow=()=>requests.map(x=>x.path);
const interactivePaths=requests.map(x=>x.path);
for(const required of ["/api/guilds/1/welcome","/api/guilds/1/levels","/api/guilds/1/economy","/api/guilds/1/economy/games","/api/guilds/1/roles","/api/guilds/1/diagnostics","/api/guilds/1/sanctions","/api/guilds/1/v62","/api/guilds/1/setup-tools","/api/guilds/1/verification-v6","/api/guilds/1/logs/config","/api/guilds/1/automation/reactions","/api/guilds/1/ops/overview"]){
  if(!interactivePaths.includes(required)) throw new Error(`Route réelle jamais chargée: ${required}`);
}
// Le cache par serveur évite les rechargements : le diagnostic n'est demandé qu'une poignée de fois malgré 22 navigations.
const diagCalls=interactivePaths.filter(p=>p==="/api/guilds/1/diagnostics").length;
if(diagCalls>4) throw new Error(`Diagnostics rechargé ${diagCalls} fois : le cache front ne fonctionne pas.`);


// Message privé : plus dans la sidebar, mais accessible depuis le Centre de modération.
dom.window.document.querySelector('#navigation button[data-tab="moderation"]').click(); await sleep(150);
dom.window.document.querySelector('[data-go="dm"]').click(); await sleep(150);
if(!dom.window.document.getElementById("dmOneMessage")) throw new Error("La page Message privé doit rester accessible depuis Sanctions.");
if(!interactivePathsNow().includes("/api/guilds/1/dm/apercu")) throw new Error("Route DM jamais chargée.");

// Tickets : « Publier » ne regarde que le panneau sélectionné (1 type sur le panneau 1 du mock → activé).
dom.window.document.querySelector('#navigation button[data-tab="tickets"]').click(); await sleep(150);
if(dom.window.document.getElementById("ticketPublish").disabled) throw new Error("Panneau avec un type : Publier devrait être actif.");
if(!/1 type/.test(dom.window.document.getElementById("ticketPanelPick").selectedOptions[0].textContent)) throw new Error("Le nombre de types du panneau doit être visible.");
// Liens de migration : jamais visibles pour un non-développeur.
if(dom.window.document.querySelector('#navigation a[href="/setup-center"]')) throw new Error("Les anciens liens ne doivent pas apparaître pour un utilisateur normal.");

const paletteInput=dom.window.document.getElementById("paletteInput");
dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown",{key:"k",metaKey:true,bubbles:true}));
await sleep(20);
if(dom.window.document.getElementById("paletteBackdrop").classList.contains("hidden")) throw new Error("Palette ⌘K inaccessible.");
paletteInput.value="sauvegardes";paletteInput.dispatchEvent(new dom.window.Event("input",{bubbles:true}));
if(!dom.window.document.querySelector('[data-palette-page="backups"]')) throw new Error("Recherche globale absente.");

// Le bouton de compte doit quitter réellement le contexte serveur, sans déconnexion.
dom.window.document.getElementById("paletteBackdrop").classList.add("hidden");
dom.window.document.getElementById("profileButton").click();
await sleep(180);
const afterProfileTabs=[...dom.window.document.querySelectorAll("#navigation button[data-tab]")].map(b=>b.dataset.tab);
if(!afterProfileTabs.includes("profile")||!afterProfileTabs.includes("servers")||!afterProfileTabs.includes("preferences")) throw new Error("Retour vers l'espace global impossible.");
if(afterProfileTabs.includes("levels")||afterProfileTabs.includes("tickets")) throw new Error("La configuration serveur reste visible après retour au profil.");
if(new URL(dom.window.location.href).searchParams.get("guild")) throw new Error("L'URL conserve une guild après retour au profil.");

if(runtimeErrors.some(message=>/SyntaxError|ReferenceError|TypeError/.test(message))){
  console.error(runtimeErrors.join("\n"));throw new Error("Erreur JavaScript dans le dashboard unifié.");
}
// Adresse ?tab=moderation → Centre de modération.
const legacy = new JSDOM(html, { url:"https://sentrix.test/app?tab=moderation&guild=1", runScripts:"dangerously", pretendToBeVisual:true, virtualConsole, beforeParse(window){ window.fetch = dom.window.fetch; window.scrollTo=()=>{}; } });
await sleep(900);
if(!legacy.window.document.querySelector("#sanctionList")) throw new Error("Le Centre de modération ne fonctionne pas via ?tab=moderation.");
legacy.window.close();

// États de démarrage : jamais une page réduite au bandeau.
async function bootWith(mock, url="https://sentrix.test/app"){
  const vc=new VirtualConsole(); const errs=[]; vc.on("jsdomError",e=>errs.push(String(e?.stack||e)));
  const d=new JSDOM(html,{url,runScripts:"dangerously",pretendToBeVisual:true,virtualConsole:vc,beforeParse(w){ w.fetch=async(input,options={})=>{ const u=new URL(typeof input==="string"?input:input.url,w.location.href); return mock(u.pathname,(options.method||"GET").toUpperCase()) ?? dom.window.fetch(input,options); }; w.scrollTo=()=>{}; }});
  await sleep(700);
  const doc=d.window.document; const visible=id=>!doc.getElementById(id).classList.contains("hidden");
  const out={landing:visible("landing"),boot:visible("bootState"),dashboard:visible("dashboard"),title:doc.getElementById("bootTitle").textContent,retry:!doc.getElementById("bootRetry").classList.contains("hidden"),login:!doc.getElementById("bootLogin").classList.contains("hidden"),content:doc.getElementById("content").textContent.trim().slice(0,80),errs};
  d.window.close(); return out;
}
const s401=await bootWith(p=>p==="/api/me"?response({error:"Connectez-vous"},401):null);
if(!s401.landing||s401.boot||s401.dashboard) throw new Error("401 sur /api/me doit afficher la page de connexion, pas une page vide: "+JSON.stringify(s401));
const s503=await bootWith(p=>p==="/api/me"?response({error:"Reconnexion Discord en cours"},503):null);
if(!s503.boot||!s503.retry||!/reconnecte/.test(s503.title)) throw new Error("503 sur /api/me doit afficher un état explicite avec Réessayer: "+JSON.stringify(s503));
const g500=await bootWith(p=>p==="/api/guilds"?response({error:"Base indisponible"},500):null);
if(!g500.boot||!g500.retry||!g500.login||!/serveurs/.test(g500.title)) throw new Error("Échec /api/guilds doit afficher un état explicite: "+JSON.stringify(g500));
const gEmpty=await bootWith(p=>p==="/api/guilds"?response({ok:true,guilds:[]}):null);
if(!gEmpty.dashboard||!/Mon espace SentriX|Mes serveurs/.test(gEmpty.content)) throw new Error("Aucune guild doit afficher l'espace profil global: "+JSON.stringify(gEmpty));
const stale=await bootWith(p=>null,"https://sentrix.test/app?guild=999999");
// Développeur : le groupe Migration (anciennes interfaces) n'existe que pour lui.
const devDom=new JSDOM(html,{url:"https://sentrix.test/app",runScripts:"dangerously",pretendToBeVisual:true,virtualConsole,beforeParse(w){ w.fetch=async(input,options={})=>{ const u=new URL(typeof input==="string"?input:input.url,w.location.href); if(u.pathname==="/api/me") return response({ok:true,user:{id:"42",username:"Dev",avatar_url:null},csrf:"t",developer:true}); return dom.window.fetch(input,options); }; w.scrollTo=()=>{}; }});
await sleep(700);
if(devDom.window.document.querySelector('#navigation a[href="/setup-center"]')) throw new Error("Migration ne doit pas apparaître dans l'espace global.");
devDom.window.document.querySelector('#serverRail [data-guild="1"]').click();
await sleep(250);
if(!devDom.window.document.querySelector('#navigation a[href="/setup-center"]')) throw new Error("Le développeur doit voir le groupe Migration dans un serveur.");
if(!devDom.window.document.querySelector('#navigation button[data-tab="advanced"]')) throw new Error("Le développeur doit voir le Centre avancé dans un serveur.");
devDom.window.close();
if(!stale.dashboard||stale.boot) throw new Error("Une guild mémorisée invalide ne doit pas casser le démarrage: "+JSON.stringify(stale));

console.log("Dashboard unified-v2 browser smoke OK:",interactivePaths.join(" -> "));
console.log("Pages unified-v2 OK:",expectedTabs.join(", "));
dom.window.close();


// Navigation simplifiée : aucun tiroir « Plus d’outils », aucun point d’état,
// et la page de règles personnalisées de commandes n’est plus proposée.
const navSource = sourceByName.get('10_nav.js') || '';
if(navSource.includes('id="navMore"') || navSource.includes('Plus d’outils')) throw new Error('La navigation doit rester ouverte sans « Plus d’outils ».');
if(navSource.includes("['access', 'Commandes & accès']")) throw new Error('Commandes & accès ne doit plus être proposé dans la navigation.');
if(navSource.includes('moduleDot(NAV_MODULE[page])')) throw new Error('Les points de statut ne doivent plus encombrer la navigation.');
const ticketSource = sourceByName.get('38_tickets.js') || '';
if(!ticketSource.includes('ticket-action-list') || !ticketSource.includes('data-ticket-button-edit')) throw new Error('Les actions Tickets doivent utiliser la vue compacte.');
if(ticketSource.includes('data-ticket-preset')) throw new Error('Les presets Tickets encombrants doivent être retirés.');


// Tickets : les actions staff doivent vivre dans une sous-page interne dédiée,
// jamais sous le formulaire principal.
if(!navSource.includes("tickets: [['panneaux', 'Panneaux'], ['actions', 'Actions staff']]")) throw new Error('Tickets doit séparer Panneaux et Actions staff.');
if(!ticketSource.includes("if (state.sub === 'actions')")) throw new Error('La page Actions staff Tickets n’est pas routée séparément.');
if(ticketSource.includes('await _renderTicketsBase();\n  await appendTicketButtonSettings();')) throw new Error('Les actions staff ne doivent plus être ajoutées sous le panneau principal.');


// La sous-page Actions staff Tickets ne doit jamais conserver le squelette de navigation
// ni recevoir les cartes d'expérience/KPI de la page principale.
if(!ticketSource.includes('ticket-actions-page')) throw new Error('Actions staff doit recréer son conteneur après le chargement API.');
const moderationSource = sourceByName.get('41_moderation.js') || '';
if(!moderationSource.includes("if(state.page==='tickets')return;")) throw new Error('Tickets doit ignorer le hero/KPI SentriX Experience.');


// Tickets v3 : la page Panneaux doit être une liste compacte et l'éditeur doit
// s'ouvrir comme une vue interne séparée, sans hero/KPI.
const modulesSource = sourceByName.get('30_modules.js') || '';
if(!modulesSource.includes('ticket-panels-home')) throw new Error('Tickets doit afficher une liste compacte de panneaux.');
if(!modulesSource.includes('ticket-panel-editor')) throw new Error('Tickets doit avoir un éditeur interne séparé.');
if(!modulesSource.includes('ticketEditorBack')) throw new Error('L’éditeur Tickets doit proposer un retour aux panneaux.');
if(!modulesSource.includes('state.ticketEditorOpen = true')) throw new Error('L’ouverture interne d’un panneau n’est pas câblée.');
if(!moderationSource.includes("if(state.page==='tickets')return;")) throw new Error('Tickets ne doit plus recevoir le hero/KPI SentriX Experience.');


// Tickets : les vues courtes doivent remplir proprement le viewport au lieu de
// laisser un grand vide noir sous la dernière carte.
const cssSource = css;
if(!cssSource.includes('Tickets viewport fill v4')) throw new Error('Le remplissage vertical Tickets est absent.');
if(!cssSource.includes('.ticket-panels-home,') || !cssSource.includes('.ticket-panel-editor,') || !cssSource.includes('.ticket-actions-page{')) throw new Error('Toutes les vues Tickets doivent partager le fond pleine hauteur.');
if(!cssSource.includes('min-height:calc(100dvh - var(--top-safe) - 156px)')) throw new Error('Tickets doit remplir la hauteur disponible du viewport.');


// Rechargement navigateur : même si l'URL contient ?guild= et une page serveur,
// SentriX doit repartir sur Mon profil. Les liens directs restent possibles lors
// d'une navigation normale.
const bootSource = sourceByName.get('90_boot.js') || '';
if(!bootSource.includes('function isHardReloadNavigation()')) throw new Error('Détection du rechargement navigateur absente.');
if(!bootSource.includes("const wanted = hardReload ? ''")) throw new Error('Un rechargement doit ignorer la guild présente dans l’URL.');
if(!bootSource.includes("state.page = 'profile'")) throw new Error('Le rechargement doit revenir à Mon profil.');


// Surveillance dashboard : avertissement discret si le boot traîne, si /ready échoue
// plusieurs fois ou si une erreur JS survient après l'ouverture.
const coreSource = sourceByName.get('00_core.js') || '';
if(!html.includes('id="healthNotice"')) throw new Error('Annonce santé dashboard absente.');
if(!html.includes('id="startupHint"')) throw new Error('Message de chargement lent absent.');
if(!coreSource.includes('function announceDashboardIssue(')) throw new Error('Gestionnaire d’annonce de bug absent.');
if(!coreSource.includes('SXD-API-')) throw new Error('Les erreurs API 5xx/réseau ne déclenchent pas d’annonce.');
if(!bootSource.includes('scheduleStartupSlowHint')) throw new Error('Le démarrage lent n’est pas détecté.');
if(!bootSource.includes("api('/ready', { background: true })")) throw new Error('Le dashboard ne surveille pas son endpoint /ready.');
if(!bootSource.includes('SXD-RUNTIME-JS') || !bootSource.includes('SXD-RUNTIME-PROMISE')) throw new Error('Les erreurs runtime ne sont pas annoncées.');


// Scrollbars SentriX : la grosse barre système grise ne doit pas revenir.
if(!cssSource.includes('scrollbars SentriX')) throw new Error('Style de scrollbar SentriX absent.');
if(!cssSource.includes('::-webkit-scrollbar-thumb')) throw new Error('Thumb de scrollbar personnalisé absent.');
if(!cssSource.includes('scrollbar-width:thin')) throw new Error('Scrollbar Firefox non affinée.');
if(!cssSource.includes('scroll-behavior:smooth')) throw new Error('Défilement fluide absent.');


// Compatibilité appareils : 320px, tablettes, clavier virtuel, safe areas,
// fenêtres partagées et préférences système.
if(!html.includes('interactive-widget=resizes-content')) throw new Error('Le viewport mobile ne gère pas le clavier virtuel.');
if(!cssSource.includes('compatibilité appareils v4')) throw new Error('La couche de compatibilité appareils est absente.');
for(const token of ['max-width:390px','max-width:340px','max-height:500px','keyboard-open','display-mode:standalone','prefers-contrast:more','forced-colors:active']){
  if(!cssSource.includes(token)) throw new Error('Compatibilité appareil manquante: '+token);
}
if(!bootSource.includes('function syncVisualViewport()')) throw new Error('VisualViewport mobile non synchronisé.');
if(!bootSource.includes("'--visual-height'")) throw new Error('Hauteur visuelle mobile non propagée au CSS.');
if(!bootSource.includes("'keyboard-open'")) throw new Error('Clavier virtuel non détecté.');
