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
    welcome:{code:"active",status:"ACTIF",detail:"Bienvenue configurée."},
    levels:{code:"active",status:"ACTIF",detail:"Niveaux configurés."},
    logs:{code:"active",status:"ACTIF",detail:"Logs configurés."},
    roles:{code:"active",status:"ACTIF",detail:"Rôles configurés."},
    tickets:{code:"active",status:"ACTIF",detail:"Tickets configurés."},
    automod:{code:"active",status:"ACTIF",detail:"AutoMod actif."},
    ai:{code:"inactive",status:"INACTIF",detail:"IA désactivée."},
    notifications:{code:"missing",status:"NON CONFIGURÉ",detail:"Aucune source."},
    moderation:{code:"active",status:"ACTIF",detail:"Permissions disponibles."},
  },
  permissions:[{key:"administrator",name:"Administrateur",granted:true},{key:"manage_roles",name:"Gérer les rôles",granted:true}],
  invalid_resources:[], bot:{id:"999",top_role_position:10},
};

const setupPayload = {
  ok:true,
  commands:[{name:"help",description:"Aide",protected:true},{name:"ban",description:"Bannir",protected:false},{name:"ticket",description:"Tickets",protected:false}],
  disabled_commands:["ticket"], ignored_channels:[], automod_exempt_roles:[], antinuke_whitelist:[], managers:[],
  manager_categories:{configuration:"Configuration",tickets:"Tickets",moderation:"Modération",securite:"Sécurité",economie:"Économie et jeux",complete:"Accès complet"},
  history:[], verification:{role_id:"15",channel_id:"22"},
  games:{enabled:true,logs_enabled:true,leaderboard_enabled:true,dm_results:false,compact_mode:false,daily_limit:50,event_multiplier:1,min_reward_multiplier:1,max_reward_multiplier:1,default_difficulty:"normal",disabled_games:[],allowed_channel_ids:[],blocked_channel_ids:[],allowed_role_ids:[],blocked_role_ids:[]},
  game_names:["guess","coinflip","quiz"],
};

const designPayload = {
  ok:true,
  design:{primary_color:0xd66f55,secondary_color:0x5865f2,success_color:0x35d66f,warning_color:0xe9bd67,danger_color:0xe36b78,footer:"SentriX",progress_length:10,progress_filled:"■",progress_empty:"□",show_avatars:true,compact_mode:false,charts_enabled:true},
};

const dom = new JSDOM(html, {
  url:"https://sentrix.test/app", runScripts:"dangerously", pretendToBeVisual:true, virtualConsole,
  beforeParse(window){
    window.fetch = async (input, options={}) => {
      const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
      const method = String(options.method || "GET").toUpperCase();
      requests.push({path:url.pathname,method});
      if(url.pathname==="/api/public") return response({ok:true,online:true,guilds:20,members:1000,latency_ms:42,uptime_seconds:3600,invite_url:"https://discord.com/oauth2/authorize?client_id=1",avatar_url:null,oauth_ready:true});
      if(url.pathname==="/api/me") return response({ok:true,user:{id:"42",username:"SentriX Test",avatar_url:null},csrf:"test-csrf"});
      if(url.pathname==="/api/guilds") return response({ok:true,guilds:[{id:"1",name:"Serveur Test",icon_url:null,installed:true}]});
      if(url.pathname==="/api/guilds/1") return response({
        ok:true,guild:{id:"1",name:"Serveur Test",members:12,channels_count:7,roles_count:7},metrics:{commands_24h:3,open_tickets:1,warnings:0,economy_accounts:2},settings:{},automod:{},ai:{},
        roles:[{id:"10",name:"Staff"},{id:"11",name:"Membre"},{id:"12",name:"Booster"},{id:"13",name:"Modérateur"},{id:"14",name:"Admin"},{id:"15",name:"Vérifié"}],
        channels:[{id:"20",name:"general",type:"text"},{id:"21",name:"logs",type:"text"},{id:"22",name:"welcome",type:"text"},{id:"23",name:"tickets",type:"text"},{id:"24",name:"reports",type:"text"},{id:"25",name:"staff",type:"text"},{id:"26",name:"Tickets",type:"category"}],social_notifications:[],
      });
      if(url.pathname==="/api/guilds/1/sanctions") return response({ok:true,sanctions:[],next_offset:null,total:0});
      if(url.pathname==="/api/guilds/1/diagnostics") return response(diagnosticsPayload);
      if(url.pathname==="/api/guilds/1/setup-tools") return method==="POST" ? response({ok:true,message:"Configuration appliquée."}) : response(setupPayload);
      if(url.pathname==="/api/guilds/1/systems") return method==="PUT" ? response({ok:true,message:"Système mis à jour.",systems:{economy_enabled:false,levels_enabled:true}}) : response({ok:true,systems:{economy_enabled:true,levels_enabled:true}});
      if(url.pathname==="/api/guilds/1/games") return response({ok:true,message:"Mini-jeux enregistrés.",games:setupPayload.games});
      if(url.pathname==="/api/guilds/1/design") return method==="PUT" ? response({ok:true,message:"Design enregistré.",design:designPayload.design}) : response(designPayload);
      if(url.pathname==="/api/guilds/1/dm/apercu") return response({guild:{id:"1",name:"Serveur Test"},destinataires:11,bots_ignores:1,duree_estimee_secondes:8});
      if(url.pathname==="/api/guilds/1/dm/job") return response({actif:false,etat:null});
      return response({error:`Route mock inconnue: ${url.pathname}`},404);
    };
    window.confirm=()=>true;window.scrollTo=()=>{};
  },
});

await new Promise(resolve=>setTimeout(resolve,1400));
const bootstrapPaths=requests.map(x=>x.path);
for(const required of ["/api/public","/api/me","/api/guilds","/api/guilds/1"]){
  if(!bootstrapPaths.includes(required)) throw new Error(`Bootstrap manquant: ${required}`);
}

const dashboard=dom.window.document.getElementById("dashboard");
if(!dashboard||dashboard.classList.contains("hidden")) throw new Error("Dashboard masqué après session.");
if(dom.window.document.querySelector('[data-tab="features"]')) throw new Error("L'ancien onglet Fonctions avancées est encore visible.");
if(dom.window.document.querySelector("#sxFeaturesFrame,.sx-features-shell")) throw new Error("L'ancien centre avancé est encore embarqué.");

const expectedTabs=["overview","welcome","messages","levels","roles","secure_roles","reaction_roles","sanctions","security","reports","logs","tickets","notifications","ai","embeds","games","design","setup","access","dm","status","general"];
const actualTabs=[...dom.window.document.querySelectorAll("#navigation button[data-tab]")].map(b=>b.dataset.tab);
for(const tab of expectedTabs) if(!actualTabs.includes(tab)) throw new Error(`Page V61 absente: ${tab}`);

for(const group of ["Général","Membres & rôles","Modération","Outils","Configuration"]){
  if(![...dom.window.document.querySelectorAll(".sx-nav-group")].some(n=>n.textContent.trim()===group)) throw new Error(`Groupe sidebar absent: ${group}`);
}

for(const tab of ["overview","welcome","security","sanctions","logs","tickets","ai","notifications","embeds","roles","reaction_roles","games","design","setup","access","dm","status","general"]){
  const button=dom.window.document.querySelector(`#navigation button[data-tab="${tab}"]`);button.click();
  await new Promise(resolve=>setTimeout(resolve,["overview","access","dm","status","setup","games","design"].includes(tab)?140:60));
  if(!button.classList.contains("active")) throw new Error(`L'onglet ${tab} ne devient pas actif.`);
  const title=dom.window.document.getElementById("tabTitle")?.textContent?.trim();if(!title) throw new Error(`Titre vide: ${tab}`);
  if(tab==="overview"&&!dom.window.document.querySelector(".sx-config-hero")) throw new Error("Vue d'ensemble sans diagnostic.");
  if(tab==="access"&&!dom.window.document.querySelector(".sx-permission-grid,.sx-command-list")) throw new Error("Accès & commandes vide.");
  if(tab==="dm"&&!dom.window.document.querySelector("#dmAllMessage,#dmOneMessage")) throw new Error("Messages privés vide.");
  if(tab==="setup"&&!dom.window.document.querySelector(".sx-unified-grid")) throw new Error("Configuration V61 vide.");
  if(tab==="games"&&!dom.window.document.querySelector(".sx-games-grid")) throw new Error("Mini-jeux V61 vides.");
  if(tab==="design"&&!dom.window.document.querySelector(".sx-design-preview")) throw new Error("Design V61 vide.");
  if(tab==="status"&&!dom.window.document.querySelector(".sx-status-grid")) throw new Error("Statut V61 vide.");
  if(tab==="reaction_roles"&&!dom.window.document.querySelector("#rr_publish")) throw new Error("Rôles-réactions V61 vide.");
}

const topLinks=[...dom.window.document.querySelectorAll(".topnav a")];
if(topLinks.some(a=>["/setup-center","/feature-suite","/operations","/community"].includes(new URL(a.href,dom.window.location.href).pathname))) throw new Error("La topbar mène encore vers un ancien centre.");

const interactivePaths=requests.map(x=>x.path);
for(const required of ["/api/guilds/1/diagnostics","/api/guilds/1/setup-tools","/api/guilds/1/systems","/api/guilds/1/design","/api/guilds/1/dm/apercu","/api/guilds/1/dm/job"]){
  if(!interactivePaths.includes(required)) throw new Error(`Route V61 jamais chargée: ${required}`);
}

if(runtimeErrors.some(message=>/SyntaxError|ReferenceError|TypeError/.test(message))){
  console.error(runtimeErrors.join("\n"));throw new Error("Erreur JavaScript V61.");
}
console.log("Dashboard V61 browser smoke OK:",interactivePaths.join(" -> "));
console.log("Pages V61 OK:",expectedTabs.join(", "));
dom.window.close();
