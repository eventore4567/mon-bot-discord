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
      if(url.pathname==="/api/guilds/1/dm/apercu") return response({guild:{id:"1",name:"Serveur Test"},destinataires:11,bots_ignores:1,duree_estimee_secondes:8});
      if(url.pathname==="/api/guilds/1/dm/job") return response({actif:false,etat:null});
      if(url.pathname==="/api/guilds/1/dm/all") return response({demarre:true,etat:{total:11,envoyes:0,dms_fermes:0,echecs:0,bots_ignores:1,traites:0,termine:false}});
      if(url.pathname==="/api/guilds/1/dm/user") return response({resultat:"envoye",message:"Message envoyé.",bilan:{envoyes:1}});
      return response({error:`Route mock inconnue: ${url.pathname}`},404);
    };
    window.confirm=()=>true;window.prompt=()=>"Test dashboard";window.scrollTo=()=>{};
  },
});

const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
await sleep(1200);
const bootstrapPaths=requests.map(x=>x.path);
for(const required of ["/api/public","/api/me","/api/guilds","/api/guilds/1"]){
  if(!bootstrapPaths.includes(required)) throw new Error(`Bootstrap manquant: ${required}`);
}

const dashboard=dom.window.document.getElementById("dashboard");
if(!dashboard||dashboard.classList.contains("hidden")) throw new Error("Dashboard masqué après session.");
if(!dom.window.document.getElementById("sentrix-dashboard-unified-v2")) throw new Error("Frontend unifié absent.");
if(!dom.window.document.getElementById("sentrix-unified-runtime-v2")) throw new Error("Runtime unifié absent.");
if(dom.window.document.querySelector("#sxFeaturesFrame,.sx-features-shell,#sentrix-v64-final")) throw new Error("Une ancienne couche frontend est encore embarquée.");

const expectedTabs=["overview","welcome","levels","security","moderation","logs","verification","roles","economy","notifications","tickets","ai","embeds","config","access","dm","diagnostic"];
const actualTabs=[...dom.window.document.querySelectorAll("#navigation button[data-tab]")].map(b=>b.dataset.tab);
for(const tab of expectedTabs) if(!actualTabs.includes(tab)) throw new Error(`Page unifiée absente: ${tab}`);

const checks={
  overview:".score", welcome:'[data-setting="welcome_message"]', levels:'[data-setting="level_message"]',
  security:"[data-automod]", moderation:"#sanctionList", logs:'[data-setting="log_channel"]',
  verification:"#verifyRules", roles:'[data-setting="mod_role"]', economy:"#goAccess", notifications:"#notifAdd",
  tickets:"#ticketSave", ai:"[data-ai]", embeds:"#embedSend", config:'[data-setting="prefix"]',
  access:"#commandList", dm:"#dmAllMessage", diagnostic:".permission-grid",
};
for(const tab of expectedTabs){
  const button=dom.window.document.querySelector(`#navigation button[data-tab="${tab}"]`);
  button.click();
  await sleep(["overview","security","moderation","verification","economy","tickets","access","dm","diagnostic"].includes(tab)?130:35);
  const currentButton=dom.window.document.querySelector(`#navigation button[data-tab="${tab}"]`);
  if(!currentButton?.classList.contains("active")) throw new Error(`L'onglet ${tab} ne devient pas actif.`);
  if(!dom.window.document.getElementById("pageTitle")?.textContent?.trim()) throw new Error(`Titre vide: ${tab}`);
  if(!dom.window.document.querySelector(checks[tab])) throw new Error(`Contenu fonctionnel absent: ${tab} (${checks[tab]})`);
}

const interactivePaths=requests.map(x=>x.path);
for(const required of ["/api/guilds/1/diagnostics","/api/guilds/1/sanctions","/api/guilds/1/v62","/api/guilds/1/setup-tools","/api/guilds/1/dm/apercu","/api/guilds/1/dm/job"]){
  if(!interactivePaths.includes(required)) throw new Error(`Route réelle jamais chargée: ${required}`);
}

const paletteInput=dom.window.document.getElementById("paletteInput");
dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown",{key:"k",metaKey:true,bubbles:true}));
await sleep(20);
if(dom.window.document.getElementById("paletteBackdrop").classList.contains("hidden")) throw new Error("Palette ⌘K inaccessible.");
paletteInput.value="messages privés";paletteInput.dispatchEvent(new dom.window.Event("input",{bubbles:true}));
if(!dom.window.document.querySelector('[data-palette-tab="dm"]')) throw new Error("Recherche globale Messages privés absente.");

if(runtimeErrors.some(message=>/SyntaxError|ReferenceError|TypeError/.test(message))){
  console.error(runtimeErrors.join("\n"));throw new Error("Erreur JavaScript dans le dashboard unifié.");
}
console.log("Dashboard unified-v2 browser smoke OK:",interactivePaths.join(" -> "));
console.log("Pages unified-v2 OK:",expectedTabs.join(", "));
dom.window.close();
