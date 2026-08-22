"""SentriX dashboard visual system.

This module keeps the dashboard backend untouched and upgrades the single-page
interface with dedicated, responsive views for the main configuration modules.
"""

from __future__ import annotations


DASHBOARD_V2_CSS = r"""
    :root{
      --bg:#05080e;--panel:#0b1119;--panel2:#101824;--panel3:#151f2e;
      --line:#1e2b3d;--line-soft:#142031;--text:#f4f8ff;--muted:#718099;
      --brand:#2f7dff;--brand2:#65a7ff;--brand-soft:#2f7dff1c;
      --ok:#27d17f;--bad:#ff5574;--warn:#f5b94d;--shadow:0 22px 70px #0008;
    }
    body{
      background-color:var(--bg);
      background-image:
        linear-gradient(#17223255 1px,transparent 1px),
        linear-gradient(90deg,#17223255 1px,transparent 1px),
        radial-gradient(circle at 82% -15%,#0c56d51c,transparent 34%);
      background-size:42px 42px,42px 42px,auto;
    }
    #landing{background:linear-gradient(180deg,#05080ee8,#05080ef7);min-height:100vh}
    .top{background:#060a11e8;border-color:#142033;padding:0 clamp(18px,4vw,64px)}
    .brand-logo{background:linear-gradient(145deg,#4a96ff,#164ccc);box-shadow:0 0 32px #2f7dff50}
    .btn{border-radius:12px;background:#111a28;border-color:#26364c}
    .btn:hover{border-color:#4c78b8;box-shadow:0 0 0 3px #2f7dff12}
    .btn.primary{background:linear-gradient(135deg,#3488ff,#1554d8);box-shadow:0 13px 30px #1760e338}
    .eyebrow{color:var(--brand2);border-color:#2f7dff55;background:#2f7dff12}
    .hero h1 span{color:#66a8ff}.preview,.feature{background:#0a1018;border-color:#1b2a3d}

    .shell{grid-template-columns:286px minmax(0,1fr)}
    .side{padding:22px 18px;background:#070b12f5;border-color:#172235;box-shadow:18px 0 55px #0003}
    .side .brand{padding:0 8px;margin-bottom:20px}.side .brand-logo{border-radius:11px}
    .user{background:#0c131e;border-color:#1b293b;padding:11px;border-radius:13px}
    .nav-label{color:#52709c;margin:22px 12px 7px;font-size:10px;letter-spacing:.14em}
    .nav{display:grid;gap:3px}
    .nav button{display:flex;align-items:center;gap:11px;padding:11px 12px;color:#8693a8;border:1px solid transparent;border-radius:11px}
    .nav button:hover{background:#0e1826;color:#dce9ff;border-color:#1a2c44}
    .nav button.active{background:linear-gradient(90deg,#17335b,#101b2b);color:#fff;border-color:#2d69bd;box-shadow:inset 3px 0 #4594ff,0 10px 24px #0003}
    .nav-ico{width:25px;height:25px;border-radius:8px;display:grid;place-items:center;background:#15243a;color:#69a9ff;font-size:12px;font-weight:900;flex:0 0 auto}
    .nav button.active .nav-ico{background:#2b78ed;color:white;box-shadow:0 0 18px #2f7dff55}
    .side-bottom{padding-top:18px;border-top:1px solid #162235}

    .workspace{padding:38px clamp(22px,3.2vw,58px) 90px;max-width:1800px;width:100%;margin:0 auto}
    .workspace-head{margin-bottom:28px;align-items:flex-end}
    .page-eyebrow{display:block;color:var(--brand2);font-size:11px;font-weight:850;letter-spacing:.15em;text-transform:uppercase;margin-bottom:9px}
    .workspace-head h1{font-size:clamp(28px,3vw,42px);letter-spacing:-.045em;margin-bottom:8px}
    .workspace-head p{font-size:15px;color:#6f7e95}
    .server-picker{min-width:290px}.server-picker label{display:block;color:#6f829f;font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin:0 0 7px 2px}
    .select,input,textarea{background:#0a1018;border:1px solid #243247;border-radius:12px;color:#eef5ff;min-height:46px;padding:11px 14px}
    .select:hover,input:hover,textarea:hover{border-color:#354b69}.select:focus,input:focus,textarea:focus{border-color:#438ef8;box-shadow:0 0 0 3px #2f7dff18}
    .overview{grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:24px}
    body[data-tab]:not([data-tab="general"]) .overview{display:none}
    .metric{position:relative;overflow:hidden;background:#0b1119;border-color:#1d2a3b;border-radius:18px;padding:21px}
    .metric:before{content:"";position:absolute;left:0;top:18px;bottom:18px;width:3px;border-radius:9px;background:#3488ff;box-shadow:0 0 16px #3488ff}
    .metric small{margin-left:4px;text-transform:uppercase;letter-spacing:.08em;font-size:10px;font-weight:800}.metric strong{margin-left:4px}
    .panel{background:transparent;border:0;border-radius:0;overflow:visible}
    .panel-head{padding:0 0 19px;border:0;align-items:flex-end}
    .panel-head h2{font-size:21px}.panel-head p{font-size:13px}
    .fields{padding:0;gap:18px}
    .fields.default-grid{background:#0b1119;border:1px solid #1d2a3b;border-radius:22px;padding:24px}
    .field label{color:#9aabc2;font-size:12px;letter-spacing:.03em}.field .hint{color:#617089}
    .savebar{margin-top:20px;padding:15px 18px;border:1px solid #1d2b40;border-radius:16px;background:#0a111bd9;backdrop-filter:blur(12px);position:sticky;bottom:18px;z-index:8;box-shadow:0 16px 45px #0007}
    .switch{background:#0d151f;border-color:#213047;border-radius:14px}
    .switch input{min-height:0;width:46px;height:26px;background:#273449;border:1px solid #34445c}
    .switch input:after{width:18px;height:18px;top:3px}.switch input:checked{background:#1f68dd;border-color:#4c98ff;box-shadow:0 0 20px #2f7dff42}.switch input:checked:after{left:23px}
    .empty{background:#0a1018;border:1px dashed #25354c;border-radius:22px;min-height:260px;display:grid;place-items:center}

    .studio-summary{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:6px}
    .summary-card{display:flex;align-items:center;gap:16px;min-height:126px;padding:22px;background:#0b1119;border:1px solid #1c2a3c;border-radius:19px}
    .summary-icon{width:50px;height:50px;border-radius:14px;display:grid;place-items:center;background:#0d2846;color:#57a6ff;font-size:20px;font-weight:900}
    .summary-icon.ok{background:#0c2d24;color:#2bd081}.summary-icon.off{background:#102838;color:#45bff0}
    .summary-card small{display:block;color:#718098;text-transform:uppercase;font-size:10px;font-weight:850;letter-spacing:.1em;margin-bottom:5px}.summary-card strong{font-size:26px}.summary-card span{display:block;color:#56647a;font-size:12px;margin-top:4px}
    .section-line{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;margin:14px 0 0;padding-bottom:13px;border-bottom:1px solid #152236}
    .section-line h3{margin:0;font-size:17px}.section-line h3:before{content:"";display:inline-block;width:3px;height:18px;background:#3b8fff;border-radius:4px;box-shadow:0 0 13px #3b8fff;margin-right:11px;vertical-align:-3px}
    .count-pill,.status-pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:6px 10px;background:#172235;border:1px solid #25344b;color:#8290a8;font-size:11px;font-weight:800}
    .status-pill.active{background:#0d3024;border-color:#16593d;color:#32d486}.status-pill.active:before,.status-pill.inactive:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 9px currentColor}

    .module-grid,.log-grid{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
    .module-card,.log-card{position:relative;min-height:205px;padding:22px;background:#0b1119;border:1px solid #1d2a3a;border-radius:20px;display:flex;flex-direction:column;overflow:hidden}
    .module-card.on{border-top-color:#3d8cf2}.module-card.on:before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:linear-gradient(90deg,#2f7dff,transparent 75%)}
    .module-head,.log-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
    .module-head h3,.log-head h3{margin:0 0 8px;font-size:16px}.module-card p,.log-card p{margin:0;color:#617089;line-height:1.55;font-size:13px}
    .module-card .switch-control{appearance:none;width:46px;height:26px;min-height:0;padding:0;border-radius:999px;background:#233047;border:1px solid #33445f;position:relative;cursor:pointer;flex:0 0 auto}
    .module-card .switch-control:after{content:"";position:absolute;width:18px;height:18px;border-radius:50%;background:#71829d;left:3px;top:3px;transition:.2s}.module-card .switch-control:checked{background:#1e66d9;border-color:#4494ff;box-shadow:0 0 20px #2f7dff44}.module-card .switch-control:checked:after{left:23px;background:white}
    .module-foot{margin-top:auto;padding-top:17px;border-top:1px solid #172333;display:flex;justify-content:space-between;gap:10px;align-items:center}.mini-action{border:1px solid #25344a;background:#0a1017;color:#b7c4d8;border-radius:999px;padding:7px 10px;font-weight:750;font-size:11px;cursor:pointer}.mini-action:hover{border-color:#3c78c5;color:#fff}
    .log-card{min-height:220px}.log-icon{width:42px;height:42px;border-radius:12px;background:#111d2b;border:1px solid #223247;display:grid;place-items:center;color:#65a7ff;font-weight:900;margin-bottom:15px}.log-card .select{margin-top:17px}.log-card details{margin-top:12px;color:#62728a;font-size:12px}.log-card summary{cursor:pointer}.event-list{margin:9px 0 0;padding:9px 0 0 18px;border-top:1px solid #172333;line-height:1.7}

    .welcome-studio,.ticket-studio{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.65fr);gap:18px;align-items:start}
    .editor-card,.preview-card,.ticket-card{background:#0b1119;border:1px solid #1d2a3b;border-radius:21px;overflow:hidden}
    .editor-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:17px 20px;border-bottom:1px solid #1a2738;background:#0d141e}
    .editor-toolbar h3{margin:0;font-size:16px}.segmented{display:flex;gap:5px;padding:4px;background:#080d14;border:1px solid #1b293c;border-radius:12px}.segment{border:0;background:transparent;color:#6f7f97;padding:8px 12px;border-radius:8px;font-weight:800;cursor:pointer}.segment.active{background:#163b6c;color:#76b4ff;box-shadow:inset 0 0 0 1px #2e6ebd}
    .studio-tabs{display:flex;padding:0 20px;border-bottom:1px solid #172334}.studio-tab{border:0;background:transparent;color:#65758c;padding:16px 14px;border-bottom:2px solid transparent;font-weight:800;cursor:pointer}.studio-tab.active{color:#68aaff;border-color:#3488ff}
    .message-pane{display:none;padding:22px}.message-pane.active{display:grid;grid-template-columns:1fr 1fr;gap:17px}.message-pane .full{grid-column:1/-1}.token-row{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 10px}.token{border:1px solid #294361;background:#101b29;color:#68b7f1;border-radius:999px;padding:5px 9px;font:700 11px ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer}
    .preview-card{position:sticky;top:22px}.preview-title{padding:17px 19px;border-bottom:1px solid #1c293a;display:flex;justify-content:space-between;align-items:center}.preview-title b{display:flex;align-items:center;gap:8px}.live-pill{color:#ff6380;background:#38131d;border:1px solid #682637;border-radius:7px;padding:4px 7px;font-size:10px;font-weight:900}.discord-preview{background:#252832;padding:20px;min-height:360px}.discord-user{display:flex;gap:11px;align-items:center;margin-bottom:12px}.discord-avatar{width:38px;height:38px;border-radius:50%;background:linear-gradient(145deg,#4b9aff,#174cbb);display:grid;place-items:center;font-weight:900}.discord-message{background:#2d3038;border-left:4px solid #3488ff;border-radius:4px;padding:16px;color:#d9dce3;white-space:pre-wrap;line-height:1.55;overflow-wrap:anywhere}.discord-message b{display:block;color:white;margin-bottom:9px}.discord-message img{display:block;max-width:100%;max-height:170px;object-fit:cover;border-radius:8px;margin-top:12px}.preview-note{padding:14px 18px;color:#5f6d82;font-size:11px;line-height:1.5}

    .ticket-studio{grid-template-columns:1fr}.ticket-card{padding:22px}.ticket-card + .ticket-card{margin-top:0}.ticket-section-title{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px}.ticket-section-title h3{margin:0;font-size:17px}.ticket-basic{display:grid;grid-template-columns:1fr 1fr;gap:18px}.component-choice{display:grid;grid-template-columns:1fr 1fr;gap:12px}.choice-card{border:1px solid #26364c;background:#0d151f;color:#8e9cb0;border-radius:16px;padding:20px;text-align:center;cursor:pointer}.choice-card.active{border-color:#3d8df6;background:#102746;color:#74b6ff;box-shadow:0 0 0 2px #2f7dff1a}.choice-card b{display:block;margin:7px 0}.choice-card small{color:#65748a}.ticket-layout{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr);gap:18px}.option-card{border:1px solid #1f2e41;background:#0d141d;border-radius:16px;padding:18px}.option-number{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:8px;background:#153d70;color:#72b3ff;font-weight:900;margin-bottom:14px}.empty-inline{border:1px dashed #2b3a50;background:#0d141e;border-radius:16px;min-height:92px;display:grid;place-items:center;color:#5e6c81;text-align:center;padding:18px}

    .toast{background:#101a28;border-color:#2a4566}.toast.bad{border-color:#79344b}
    @media(max-width:1180px){.module-grid,.log-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.welcome-studio{grid-template-columns:1fr}.preview-card{position:relative;top:0}.ticket-layout{grid-template-columns:1fr}}
    @media(max-width:980px){.shell{grid-template-columns:1fr}.side{position:relative;height:auto}.nav{display:flex;overflow:auto;padding-bottom:4px}.nav button{min-width:max-content}.workspace{padding-top:26px}.welcome-studio{grid-template-columns:1fr}}
    @media(max-width:720px){.workspace-head{align-items:stretch}.server-picker{min-width:0}.studio-summary,.module-grid,.log-grid,.ticket-basic,.component-choice,.message-pane.active{grid-template-columns:1fr}.welcome-studio,.ticket-layout{grid-template-columns:1fr}.summary-card{min-height:105px}.module-card,.log-card{min-height:185px}.savebar{bottom:8px}.overview{grid-template-columns:1fr 1fr}}
    @media(max-width:480px){.overview{grid-template-columns:1fr}.workspace{padding:22px 14px 70px}.editor-toolbar{align-items:flex-start;flex-direction:column}.segmented{width:100%}.segment{flex:1}.studio-tabs{overflow:auto}.ticket-card{padding:17px}}
"""


DASHBOARD_V2_JS = r"""
    const studioMeta={
      general:["TABLEAU DE BORD","Configuration générale"],security:["PROTECTION","Protection AntiRaid"],
      sanctions:["MODÉRATION","Historique des sanctions"],logs:["MODULES","Logs du serveur"],
      welcome:["MODULES","Accueil et départ"],levels:["PROGRESSION","Niveaux et expérience"],
      tickets:["MODULES","Configuration des tickets"],ai:["OUTILS","Intelligence artificielle"],
      notifications:["AUTOMATISATION","Notifications sociales"],roles:["SERVEUR","Rôles et salons"]
    };
    const logEvents={
      log_moderation:["Bannissements et exclusions","Avertissements","Mutes et sanctions"],
      log_members:["Arrivées et départs","Profils mis à jour","Rôles des membres"],
      log_messages:["Messages modifiés","Messages supprimés","Pièces jointes"],
      log_voice:["Entrées et sorties","Déplacements","Mises en sourdine"],
      log_automod:["Filtres déclenchés","Actions automatiques","Contenu bloqué"],
      log_server:["Paramètres du serveur","Intégrations","Invitations"],
      log_roles:["Création et suppression","Permissions modifiées","Hiérarchie"],
      log_channel:["Salons créés","Salons supprimés","Paramètres modifiés"]
    };
    const logIcons={log_moderation:"M",log_members:"U",log_messages:"#",log_voice:"V",log_automod:"A",log_server:"S",log_roles:"R",log_channel:"C"};

    function dashboardSource(field){return state.tab==="security"?state.guildData.automod:state.tab==="ai"?state.guildData.ai:state.guildData.settings;}
    function setPageIdentity(tab){
      document.body.dataset.tab=state.tab;
      const meta=studioMeta[state.tab]||["SENTRIX",tab.title];
      $("pageEyebrow").textContent=meta[0];$("pageTitle").textContent=meta[1];$("pageSubtitle").textContent=tab.description;
      $("guildContext").textContent=state.guildData?.guild?.name||"Serveur actif";
    }
    function markDirty(){state.dirty=true;$("saveStatus").textContent="Modifications non enregistrées";}
    function bindDashboardInputs(){
      $("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{markDirty();if(state.tab==="welcome")refreshWelcomePreview();if(state.tab==="security")refreshModuleCard(el);}));
      $("fields").querySelectorAll("[data-soft-action]").forEach(el=>el.addEventListener("click",()=>toast(el.dataset.softAction)));
    }
    function refreshModuleCard(input){
      const card=input.closest(".module-card");if(!card)return;card.classList.toggle("on",input.checked);
      const pill=card.querySelector(".status-pill");pill.className=`status-pill ${input.checked?"active":"inactive"}`;pill.textContent=input.checked?"Actif":"Inactif";
    }
    function renderModuleGrid(tab){
      const source=state.guildData.automod||{};
      const enabled=tab.fields.filter(f=>Number(source[f.key])).length;
      $("fields").innerHTML=`<div class="section-line"><h3>Modules de protection</h3><span class="count-pill">${tab.fields.length} modules · ${enabled} actifs</span></div><div class="module-grid">${tab.fields.map((f,index)=>{const on=Number(source[f.key]);return `<article class="module-card ${on?"on":""}"><div class="module-head"><div><span class="page-eyebrow">MODULE ${String(index+1).padStart(2,"0")}</span><h3>${esc(f.label)}</h3></div><input class="switch-control" data-key="${esc(f.key)}" type="checkbox" ${on?"checked":""} aria-label="Activer ${esc(f.label)}"></div><p>${esc(f.hint)}</p><div class="module-foot"><span class="status-pill ${on?"active":"inactive"}">${on?"Actif":"Inactif"}</span><button class="mini-action" type="button" data-soft-action="Les réglages avancés de ${esc(f.label)} seront ajoutés dans le prochain écran.">Réglages</button></div></article>`;}).join("")}</div>`;
    }
    function renderLogStudio(tab){
      const source=state.guildData.settings||{};const active=tab.fields.filter(f=>source[f.key]).length;const totalEvents=tab.fields.reduce((sum,f)=>sum+(logEvents[f.key]?.length||0),0);
      $("fields").innerHTML=`<div class="studio-summary"><article class="summary-card"><span class="summary-icon ok">✓</span><div><small>Catégories actives</small><strong>${active}</strong><span>sur ${tab.fields.length} catégories</span></div></article><article class="summary-card"><span class="summary-icon off">×</span><div><small>Désactivées</small><strong>${tab.fields.length-active}</strong><span>sans salon configuré</span></div></article><article class="summary-card"><span class="summary-icon">≡</span><div><small>Événements suivis</small><strong>${totalEvents}</strong><span>répartis par catégorie</span></div></article></div><div class="section-line"><h3>Catégories de logs</h3><span class="count-pill">${tab.fields.length} catégories</span></div><div class="log-grid">${tab.fields.map(f=>{const value=source[f.key];const events=logEvents[f.key]||[];return `<article class="log-card"><div class="log-head"><div><span class="log-icon">${logIcons[f.key]||"L"}</span><h3>${esc(f.label)}</h3><p>${events.length} événements surveillés</p></div><span class="status-pill ${value?"active":"inactive"}">${value?"Actif":"Inactif"}</span></div><select class="select" data-key="${esc(f.key)}">${optionList("channel",value)}</select><details><summary>Voir les événements</summary><ul class="event-list">${events.map(e=>`<li>${esc(e)}</li>`).join("")}</ul></details></article>`;}).join("")}</div>`;
    }
    function studioTokens(){return `<div class="token-row"><button class="token" type="button" data-token="{member}">{member}</button><button class="token" type="button" data-token="{username}">{username}</button><button class="token" type="button" data-token="{server}">{server}</button><button class="token" type="button" data-token="{member_count}">{member_count}</button></div>`;}
    function renderWelcomeStudio(){
      const s=state.guildData.settings||{};
      const welcome=s.welcome_message||"Bienvenue {member} ! Tu viens de rejoindre {server}. Tu es maintenant notre membre n°{member_count}.";
      const goodbye=s.goodbye_message||"À bientôt {username}. Merci d'avoir fait partie de {server}.";
      $("fields").innerHTML=`<div class="welcome-studio"><section class="editor-card"><div class="editor-toolbar"><h3>Éditeur de messages</h3><div class="segmented"><button class="segment active" type="button" data-message-kind="welcome">Bienvenue</button><button class="segment" type="button" data-message-kind="goodbye">Au revoir</button></div></div><div class="studio-tabs"><button class="studio-tab active" type="button" data-pane="content">Contenu</button><button class="studio-tab" type="button" data-pane="banner">Bannière</button><button class="studio-tab" type="button" data-pane="channel">Salon</button></div><div data-message-form="welcome"><div class="message-pane active" data-pane-content="content"><div class="field full"><label>Message envoyé au nouveau membre</label>${studioTokens()}<textarea data-key="welcome_message" rows="8">${esc(welcome)}</textarea><div class="hint">Rédige un message propre à SentriX. Les variables sont remplacées automatiquement.</div></div></div><div class="message-pane" data-pane-content="banner"><div class="field full"><label>Image ou GIF de bienvenue</label><input data-key="welcome_image_url" type="url" value="${esc(s.welcome_image_url||"")}" placeholder="https://exemple.com/banniere.png"><div class="hint">URL HTTPS directe. L'aperçu se met à jour automatiquement.</div></div></div><div class="message-pane" data-pane-content="channel"><div class="field full"><label>Salon d'arrivée</label><select class="select" data-key="welcome_channel">${optionList("channel",s.welcome_channel)}</select></div><div class="field full"><label>Rôle attribué à l'arrivée</label><select class="select" data-key="autorole">${optionList("role",s.autorole)}</select></div></div></div><div class="hidden" data-message-form="goodbye"><div class="message-pane active" data-pane-content="content"><div class="field full"><label>Message envoyé lors d'un départ</label>${studioTokens()}<textarea data-key="goodbye_message" rows="8">${esc(goodbye)}</textarea></div></div><div class="message-pane" data-pane-content="banner"><div class="empty-inline full">Le message de départ utilise un affichage léger, sans bannière imposée.</div></div><div class="message-pane" data-pane-content="channel"><div class="field full"><label>Salon de départ</label><select class="select" data-key="goodbye_channel">${optionList("channel",s.goodbye_channel)}</select></div></div></div></section><aside class="preview-card"><div class="preview-title"><b>◉ Aperçu en direct</b><span class="live-pill">LIVE</span></div><div class="discord-preview"><div class="discord-user"><span class="discord-avatar">S</span><div><b>SentriX</b><small style="color:#8b93a5"> BOT · maintenant</small></div></div><div class="discord-message"><b id="previewHeading">Nouveau membre</b><span id="previewCopy"></span><img id="previewImage" class="hidden" alt="Aperçu de la bannière"></div></div><div class="preview-note">Aperçu indicatif : Discord appliquera sa propre police et remplacera les variables par les vraies données.</div></aside></div>`;
      let kind="welcome",pane="content";
      const sync=()=>{$("fields").querySelectorAll("[data-message-kind]").forEach(b=>b.classList.toggle("active",b.dataset.messageKind===kind));$("fields").querySelectorAll("[data-message-form]").forEach(f=>f.classList.toggle("hidden",f.dataset.messageForm!==kind));$("fields").querySelectorAll(".studio-tab").forEach(b=>b.classList.toggle("active",b.dataset.pane===pane));$("fields").querySelectorAll("[data-message-form]:not(.hidden) [data-pane-content]").forEach(p=>p.classList.toggle("active",p.dataset.paneContent===pane));refreshWelcomePreview();};
      $("fields").querySelectorAll("[data-message-kind]").forEach(b=>b.addEventListener("click",()=>{kind=b.dataset.messageKind;$("fields").dataset.messageKind=kind;pane="content";sync();}));$("fields").querySelectorAll(".studio-tab").forEach(b=>b.addEventListener("click",()=>{pane=b.dataset.pane;sync();}));
      $("fields").querySelectorAll("[data-token]").forEach(b=>b.addEventListener("click",()=>{const form=b.closest("[data-message-form]");const area=form.querySelector("textarea");const start=area.selectionStart,end=area.selectionEnd;area.value=area.value.slice(0,start)+b.dataset.token+area.value.slice(end);area.focus();area.selectionStart=area.selectionEnd=start+b.dataset.token.length;area.dispatchEvent(new Event("input",{bubbles:true}));}));
      $("fields").dataset.messageKind=kind;$("fields").addEventListener("click",e=>{const b=e.target.closest("[data-message-kind]");if(b)$("fields").dataset.messageKind=b.dataset.messageKind;});sync();
    }
    function refreshWelcomePreview(){
      const kind=$("fields").dataset.messageKind||"welcome";const key=kind==="welcome"?"welcome_message":"goodbye_message";const area=$("fields").querySelector(`[data-key="${key}"]`);if(!area||!$("previewCopy"))return;
      let value=area.value||"";const guild=state.guildData?.guild?.name||"ce serveur";value=value.replaceAll("{member}","@NouveauMembre").replaceAll("{username}","NouveauMembre").replaceAll("{server}",guild).replaceAll("{member_count}",number((state.guildData?.guild?.members||0)+1));
      $("previewHeading").textContent=kind==="welcome"?"Bienvenue sur SentriX":"Un membre nous quitte";$("previewCopy").textContent=value;
      const img=$("previewImage");const url=$("fields").querySelector('[data-key="welcome_image_url"]')?.value.trim();if(kind==="welcome"&&url){img.src=url;img.classList.remove("hidden");}else img.classList.add("hidden");
    }
    function renderTicketStudio(){
      const s=state.guildData.settings||{};
      $("fields").innerHTML=`<div class="ticket-studio"><section class="ticket-card"><div class="ticket-section-title"><div><span class="page-eyebrow">CONFIGURATION</span><h3>Réglages du système</h3></div><span class="count-pill">SentriX Support</span></div><div class="ticket-basic"><div class="field"><label>Catégorie des tickets</label><select class="select" data-key="ticket_category">${optionList("category",s.ticket_category)}</select></div><div class="field"><label>Salon des comptes rendus</label><select class="select" data-key="ticket_log_channel">${optionList("channel",s.ticket_log_channel)}</select></div><div class="field"><label>Délai avant suppression</label><input data-key="ticket_delete_delay" type="number" min="0" max="3600" value="${esc(s.ticket_delete_delay??0)}"><div class="hint">Durée en secondes après la fermeture.</div></div><div class="component-choice"><button class="choice-card active" type="button"><b>Menu déroulant</b><small>Jusqu'à 25 motifs</small></button><button class="choice-card" type="button"><b>Boutons</b><small>Jusqu'à 5 choix</small></button></div></div></section><div class="ticket-layout"><section class="ticket-card"><div class="ticket-section-title"><div><span class="page-eyebrow">OPTIONS DU PANNEAU</span><h3>Parcours du membre</h3></div><span class="count-pill">1 option</span></div><article class="option-card"><span class="option-number">1</span><h3 style="margin:0 0 7px">Assistance générale</h3><p style="margin:0 0 18px;color:#68778d">Une demande privée est créée et transmise à l'équipe du serveur.</p><div class="field"><label>Nom du salon généré</label><input value="ticket-{username}" disabled></div></article></section><aside class="preview-card"><div class="preview-title"><b>◉ Aperçu du panneau</b><span class="live-pill">LIVE</span></div><div class="discord-preview"><div class="discord-user"><span class="discord-avatar">S</span><div><b>SentriX</b><small style="color:#8b93a5"> BOT · maintenant</small></div></div><div class="discord-message"><b>Centre d'assistance</b>Choisis le motif qui correspond à ta demande. SentriX ouvrira un espace privé avec l'équipe du serveur.<div class="select" style="margin-top:14px;color:#8d9bb0">Sélectionner un motif…</div></div></div></aside></div><section class="ticket-card"><div class="ticket-section-title"><h3>Après la fermeture</h3></div><div class="ticket-basic"><label class="switch full"><div><b>Envoyer le transcript au membre</b><span>Le membre reçoit une copie de la conversation en message privé.</span></div><input data-key="ticket_transcript_dm" type="checkbox" ${Number(s.ticket_transcript_dm)?"checked":""}></label><label class="switch full"><div><b>Demander une évaluation</b><span>Une note rapide est proposée après la résolution.</span></div><input data-key="ticket_rating_enabled" type="checkbox" ${Number(s.ticket_rating_enabled)?"checked":""}></label></div></section></div>`;
      $("fields").querySelectorAll(".choice-card").forEach(b=>b.addEventListener("click",()=>{$("fields").querySelectorAll(".choice-card").forEach(x=>x.classList.toggle("active",x===b));}));
    }
    function renderDefaultStudio(tab){$("fields").classList.add("default-grid");$("fields").innerHTML=tab.fields.map(fieldHTML).join("");}
    function renderTab(){
      if(!state.guildData)return;const tab=tabs[state.tab];$("fields").className="fields";setPageIdentity(tab);
      $("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;
      if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else if(state.tab==="security")renderModuleGrid(tab);else if(state.tab==="logs")renderLogStudio(tab);else if(state.tab==="welcome")renderWelcomeStudio();else if(state.tab==="tickets")renderTicketStudio();else renderDefaultStudio(tab);
      $("saveBar").classList.toggle("hidden",Boolean(tab.sanctions));$("saveButton").textContent=tab.notifications?"Ajouter la notification":"Enregistrer les modifications";$("saveStatus").textContent=tab.notifications?"Vérification automatique toutes les 5 minutes":"Toutes les données sont à jour";state.dirty=false;bindDashboardInputs();
    }
"""


def apply_dashboard_theme(html: str) -> str:
    """Inject the SentriX V2 theme and dedicated module renderers."""

    nav_old = """      <nav class="nav" id="navigation">
        <button data-tab="general" class="active">Général</button>
        <button data-tab="security">Sécurité</button>
        <button data-tab="sanctions">Sanctions</button>
        <button data-tab="logs">Logs</button>
        <button data-tab="welcome">Accueil</button>
        <button data-tab="levels">Niveaux</button>
        <button data-tab="tickets">Tickets</button>
        <button data-tab="ai">Intelligence artificielle</button>
        <button data-tab="notifications">Notifications</button>
        <button data-tab="roles">Rôles et salons</button>
      </nav>"""
    nav_new = """      <nav class="nav" id="navigation">
        <button data-tab="general" class="active"><span class="nav-ico">⌂</span>Vue d'ensemble</button>
        <button data-tab="security"><span class="nav-ico">◇</span>Protection AntiRaid</button>
        <button data-tab="logs"><span class="nav-ico">≡</span>Logs du serveur</button>
        <button data-tab="sanctions"><span class="nav-ico">!</span>Sanctions</button>
        <button data-tab="welcome"><span class="nav-ico">↗</span>Bienvenue et départ</button>
        <button data-tab="tickets"><span class="nav-ico">#</span>Tickets</button>
        <button data-tab="levels"><span class="nav-ico">↑</span>Niveaux</button>
        <button data-tab="ai"><span class="nav-ico">✦</span>Intelligence artificielle</button>
        <button data-tab="notifications"><span class="nav-ico">●</span>Notifications</button>
        <button data-tab="roles"><span class="nav-ico">R</span>Rôles et salons</button>
      </nav>"""
    head_old = """      <div class="workspace-head">
        <div><h1 id="pageTitle">Dashboard</h1><p id="pageSubtitle">Choisissez un serveur que vous gérez.</p></div>
        <select id="serverSelect" class="select server-select"><option value="">Chargement des serveurs…</option></select>
      </div>"""
    head_new = """      <div class="workspace-head">
        <div><span class="page-eyebrow" id="pageEyebrow">TABLEAU DE BORD</span><h1 id="pageTitle">Dashboard</h1><p id="pageSubtitle">Choisissez un serveur que vous gérez.</p></div>
        <div class="server-picker"><label id="guildContext">Serveur actif</label><select id="serverSelect" class="select server-select"><option value="">Chargement des serveurs…</option></select></div>
      </div>"""
    html = html.replace("  </style>", DASHBOARD_V2_CSS + "\n  </style>", 1)
    html = html.replace(nav_old, nav_new, 1)
    html = html.replace(head_old, head_new, 1)
    html = html.replace(
        "    Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true));",
        DASHBOARD_V2_JS + "\n    Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true));",
        1,
    )
    return html
