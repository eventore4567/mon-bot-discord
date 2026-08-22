"""Clean Oxyde-inspired page-by-page dashboard for SentriX.

This module intentionally owns only the presentation layer. It keeps the original
``web.dashboard`` routes, OAuth checks, CSRF protection and save handlers intact, while
replacing the accumulated visual layers with one predictable navigation model: one page
is rendered at a time.
"""

from __future__ import annotations


OXYDE_REBUILD_CSS = r"""
    /* SentriX dashboard V4 — Oxyde-inspired, one page at a time. */
    :root{
      --sx-bg:#07080d;
      --sx-sidebar:#0c0f18;
      --sx-panel:#121725;
      --sx-panel-2:#171d2e;
      --sx-panel-3:#1b2235;
      --sx-line:#293149;
      --sx-line-soft:#20273a;
      --sx-text:#f4f3fb;
      --sx-muted:#969eb4;
      --sx-purple:#8f73ff;
      --sx-purple-2:#b09cff;
      --sx-purple-soft:#8f73ff1f;
      --sx-green:#55d89b;
      --sx-red:#ff6d82;
      --sx-amber:#f0bd62;
      --sx-radius:21px;
      --sx-shadow:0 24px 75px rgba(0,0,0,.34);
    }

    html,body{background:var(--sx-bg)!important}
    body{color:var(--sx-text)!important;overflow-x:hidden}
    body::before{
      content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
      background:
        radial-gradient(900px 520px at 76% -160px,rgba(112,75,232,.16),transparent 70%),
        radial-gradient(620px 380px at 18% 105%,rgba(95,65,185,.07),transparent 72%),
        #07080d;
    }

    /* Kill every old alternate-home layer. V4 is the only dashboard surface. */
    #sxSimpleHome,#sxSimpleControls,#sxModeEscape,#sxAdvancedGuide{display:none!important}
    body.sx-simple-mode #navigation,body.sx-simple-advanced #navigation{display:grid!important}
    body.sx-simple-mode.sx-simple-home-active #serverContent{display:block!important}
    body.sx-simple-mode .nav-label,body.sx-simple-advanced .nav-label{display:none!important}

    .shell{
      min-height:100vh!important;
      display:grid!important;
      grid-template-columns:280px minmax(0,1fr)!important;
      background:transparent!important;
    }
    .side{
      position:sticky!important;top:0!important;height:100vh!important;overflow:auto!important;
      padding:0 14px 18px!important;
      border-right:1px solid var(--sx-line-soft)!important;
      background:linear-gradient(180deg,#0d1019 0%,#090b12 100%)!important;
      z-index:40!important;
    }
    .side .brand{
      height:92px!important;margin:0 -14px 12px!important;padding:0 22px!important;
      border-bottom:1px solid var(--sx-line-soft)!important;
      display:flex!important;align-items:center!important;gap:13px!important;
      font-size:19px!important;font-weight:900!important;letter-spacing:-.025em!important;
    }
    .side .brand-logo{
      width:44px!important;height:44px!important;border-radius:14px!important;
      background:linear-gradient(145deg,#9d84ff,#6849dd)!important;
      border:1px solid rgba(218,207,255,.3)!important;
      color:white!important;box-shadow:0 0 28px rgba(120,82,242,.26)!important;
    }
    .side .user{
      margin:8px 2px 15px!important;padding:11px!important;border-radius:14px!important;
      border:1px solid var(--sx-line-soft)!important;background:#10141f!important;
    }
    .side .user .brand-logo{width:36px!important;height:36px!important;border-radius:11px!important}
    .side .user span{color:#798198!important}

    .nav{display:grid!important;gap:3px!important;padding:4px 0 120px!important;overflow:visible!important}
    .nav-label{display:none!important}
    .sx-nav-group{
      padding:17px 12px 7px!important;color:#656d83!important;font-size:10px!important;
      font-weight:900!important;letter-spacing:.13em!important;text-transform:uppercase!important;
    }
    #navigation button{
      min-height:43px!important;width:100%!important;margin:0!important;padding:10px 12px!important;
      display:flex!important;align-items:center!important;gap:11px!important;
      border:1px solid transparent!important;border-radius:11px!important;
      color:#a5abbd!important;background:transparent!important;
      font-size:13px!important;font-weight:720!important;text-align:left!important;
      transition:background .15s ease,border-color .15s ease,color .15s ease,transform .15s ease!important;
    }
    #navigation button:hover{color:#f3f0ff!important;background:#151a29!important;border-color:#232b40!important;transform:translateX(1px)}
    #navigation button.active{
      color:#fff!important;background:linear-gradient(90deg,rgba(143,115,255,.22),rgba(143,115,255,.08))!important;
      border-color:rgba(143,115,255,.22)!important;box-shadow:inset 3px 0 0 var(--sx-purple)!important;
    }
    .sx-nav-icon{
      width:27px;height:27px;border-radius:9px;display:grid;place-items:center;flex:0 0 27px;
      color:#858da3;background:#151a27;border:1px solid #222a3e;font-size:10px;font-weight:950;
    }
    #navigation button.active .sx-nav-icon{color:#d7cdff;background:#241d3d;border-color:#493b76}
    .side-bottom{
      position:absolute!important;left:14px!important;right:14px!important;bottom:15px!important;
      margin:0!important;padding-top:12px!important;background:#090b12!important;
      border-top:1px solid var(--sx-line-soft)!important;display:grid!important;gap:8px!important;
    }
    .side-bottom .btn{min-height:39px!important;border-radius:10px!important;font-size:12px!important}

    .workspace{min-width:0!important;max-width:none!important;padding:0!important;background:transparent!important}
    .sx-topbar{
      height:68px;position:sticky;top:0;z-index:32;display:flex;align-items:center;justify-content:space-between;
      padding:0 34px;border-bottom:1px solid var(--sx-line-soft);
      background:rgba(8,10,16,.86);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
    }
    .sx-breadcrumb{display:flex;align-items:center;gap:9px;color:#6e7589;font-size:12px;font-weight:700}
    .sx-breadcrumb strong{color:#d9d6e4}.sx-breadcrumb i{font-style:normal;color:#3e4558}
    .sx-top-actions{display:flex;align-items:center;gap:9px}
    .sx-top-status{height:38px;padding:0 13px;border:1px solid #242b3f;border-radius:10px;background:#10141e;color:#8d94a8;display:flex;align-items:center;gap:8px;font-size:11px;font-weight:800}
    .sx-top-status::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--sx-green);box-shadow:0 0 12px rgba(85,216,155,.5)}
    .sx-top-save{height:38px;padding:0 15px;border:1px solid #7760d4;border-radius:10px;background:linear-gradient(135deg,#9275ff,#7254e2);color:white;font-weight:850;cursor:pointer;box-shadow:0 9px 25px rgba(111,77,223,.22)}
    .sx-top-save:hover{filter:brightness(1.08)}
    .sx-top-save.hidden{display:none!important}

    .workspace-head{
      margin:0!important;padding:38px 34px 25px!important;display:flex!important;align-items:flex-end!important;
      justify-content:space-between!important;gap:28px!important;border-bottom:1px solid #141927!important;
    }
    .workspace-head>div:first-child{max-width:780px!important}
    .sx-page-eyebrow{
      display:block;margin:0 0 9px;color:var(--sx-purple-2);font-size:11px;font-weight:950;
      letter-spacing:.12em;text-transform:uppercase;
    }
    .workspace-head h1{margin:0!important;color:#f7f5ff!important;font-size:34px!important;font-weight:900!important;letter-spacing:-.045em!important}
    .workspace-head p{margin:7px 0 0!important;color:#8c93a7!important;font-size:14px!important;line-height:1.55!important}
    .server-select{min-width:290px!important}
    .server-select label{display:block!important;margin-bottom:7px!important;color:#70788c!important;font-size:10px!important;font-weight:900!important;letter-spacing:.08em!important;text-transform:uppercase!important}

    .select,input,textarea{
      color:#f4f2fb!important;background:#0d1019!important;border:1px solid #282f43!important;
      border-radius:11px!important;padding:11px 12px!important;outline:none!important;box-shadow:none!important;
      transition:border-color .15s ease,box-shadow .15s ease,background .15s ease!important;
    }
    .select:focus,input:focus,textarea:focus{background:#101420!important;border-color:#6f58cb!important;box-shadow:0 0 0 3px rgba(143,115,255,.1)!important}
    textarea{min-height:122px!important}

    #serverContent{padding:0 34px 78px!important}
    .overview{display:none!important}
    .panel{margin-top:0!important;border:0!important;background:transparent!important;box-shadow:none!important;overflow:visible!important}
    .panel-head{display:none!important}
    .fields{padding:0!important;display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:16px!important}
    .field{
      min-width:0;padding:20px!important;border:1px solid var(--sx-line-soft)!important;border-radius:17px!important;
      background:linear-gradient(145deg,#141925,#10141e)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.018)!important;
    }
    .field.full{grid-column:1/-1!important}
    .field label{color:#ece9f5!important;font-size:13px!important;font-weight:800!important}
    .field .hint{color:#737b90!important;font-size:11px!important;line-height:1.5!important}
    .switch{
      grid-column:1/-1!important;padding:17px 18px!important;border:1px solid var(--sx-line-soft)!important;
      border-radius:15px!important;background:#121722!important;
    }
    .switch div b{color:#f0eef6!important;font-size:13px!important}.switch div span{color:#777f93!important}
    .switch input{background:#30364a!important;border:0!important}.switch input:checked{background:var(--sx-purple)!important}

    .savebar{
      position:sticky!important;bottom:14px!important;z-index:25!important;margin:18px 0 0!important;padding:13px 14px!important;
      border:1px solid rgba(143,115,255,.18)!important;border-radius:14px!important;
      background:rgba(13,16,25,.93)!important;backdrop-filter:blur(14px)!important;box-shadow:0 18px 50px rgba(0,0,0,.28)!important;
    }
    .savebar.hidden{display:none!important}.save-status{color:#7d8497!important}
    .btn{
      min-height:40px!important;border:1px solid #2b3246!important;border-radius:10px!important;
      background:#171c29!important;color:#e8e6ef!important;font-weight:800!important;box-shadow:none!important;
    }
    .btn:hover{border-color:#51436f!important;background:#1b2030!important;transform:translateY(-1px)!important}
    .btn.primary{border-color:#735bd2!important;background:linear-gradient(135deg,#8f73ff,#6f52dd)!important;color:#fff!important;box-shadow:0 9px 25px rgba(100,68,211,.2)!important}
    .btn.danger{background:#30171f!important;border-color:#5d2a37!important;color:#ff9bab!important}

    /* Oxyde-like overview: large simple sections, no tiny page thumbnails. */
    .sx-overview{display:grid;gap:18px;padding-top:26px}
    .sx-summary{
      display:grid;grid-template-columns:minmax(0,1.35fr) repeat(3,minmax(150px,.45fr));gap:13px;
    }
    .sx-summary-main,.sx-summary-stat,.sx-hub-card{
      border:1px solid var(--sx-line)!important;border-radius:var(--sx-radius)!important;
      background:linear-gradient(145deg,#151a2a,#10141f)!important;box-shadow:var(--sx-shadow)!important;
    }
    .sx-summary-main{padding:25px 27px;position:relative;overflow:hidden}
    .sx-summary-main::after{content:"";position:absolute;width:240px;height:240px;right:-110px;top:-125px;border-radius:50%;background:radial-gradient(circle,rgba(143,115,255,.19),transparent 69%)}
    .sx-kicker{color:var(--sx-purple-2);font-size:11px;font-weight:950;letter-spacing:.12em;text-transform:uppercase;margin-bottom:8px}
    .sx-summary-main h2{position:relative;z-index:1;margin:0;color:#f6f4fc;font-size:24px;letter-spacing:-.035em}
    .sx-summary-main p{position:relative;z-index:1;margin:8px 0 0;color:#8991a7;line-height:1.55;font-size:13px;max-width:620px}
    .sx-summary-stat{padding:20px;display:flex;flex-direction:column;justify-content:center;min-height:120px}
    .sx-summary-stat small{color:#71798e;font-size:9px;font-weight:950;letter-spacing:.1em;text-transform:uppercase}
    .sx-summary-stat strong{font-size:24px;margin-top:6px;letter-spacing:-.035em}
    .sx-summary-stat span{color:#747c90;font-size:10px;margin-top:4px}
    .sx-hubs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
    .sx-hub-card{padding:27px;min-height:215px;display:flex;flex-direction:column;justify-content:space-between}
    .sx-hub-card h3{margin:0 0 8px;color:#f4f2f9;font-size:21px;letter-spacing:-.03em}
    .sx-hub-card p{margin:0;color:#9299ad;font-size:13px;line-height:1.6;max-width:620px}
    .sx-hub-actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:24px}
    .sx-hub-button{
      min-height:44px;padding:0 17px;border:1px solid #323a52;border-radius:13px;background:#191f30;color:#f1eff8;
      font-weight:850;cursor:pointer;transition:.15s;
    }
    .sx-hub-button:hover{border-color:#5d4d8f;background:#20263a;transform:translateY(-1px)}
    .sx-hub-button.primary{border-color:#6d56c7;background:linear-gradient(135deg,#2a2246,#1d1930);color:#cabcff}
    .sx-hub-button.primary:hover{border-color:#8f73ff}

    .sx-section-head{grid-column:1/-1;margin-top:26px;padding-bottom:3px}
    .sx-section-head small{display:block;color:var(--sx-purple-2);font-size:10px;font-weight:950;letter-spacing:.12em;text-transform:uppercase;margin-bottom:7px}
    .sx-section-head h2{margin:0;color:#f3f1f8;font-size:19px;letter-spacing:-.025em}
    .sx-section-head p{margin:5px 0 0;color:#747c91;font-size:12px}

    /* Existing sanctions / notifications keep their backend logic, only get the V4 skin. */
    .sanctions-shell,.notification-builder,.notification-list{grid-column:1/-1!important}
    .sanction-card,.notification-item,.notification-empty{
      border-color:var(--sx-line-soft)!important;background:#121722!important;border-radius:15px!important;
    }
    .sanction-toolbar{gap:10px!important}.sanction-summary{color:#7f8799!important}
    .sanction-badge{border:1px solid transparent}.sanction-badge.ban{background:#351923!important}.sanction-badge.mute{background:#302718!important}.sanction-badge.warn{background:#2d2518!important}.sanction-badge.positive{background:#143126!important}
    .notification-list h3{color:#f0eef6!important}

    /* Hide legacy visual clutter injected by older dashboard layers. */
    #sentrixOxydeHero,.sentrix-control-center,.sentrix-nav-search,.sentrix-advanced-guide{display:none!important}

    @media(max-width:1180px){
      .sx-summary{grid-template-columns:1fr 1fr}.sx-summary-main{grid-column:1/-1}.sx-hubs{grid-template-columns:1fr}
    }
    @media(max-width:980px){
      .shell{grid-template-columns:1fr!important}.side{position:relative!important;height:auto!important;padding-bottom:10px!important;border-right:0!important;border-bottom:1px solid var(--sx-line-soft)!important}.side .brand{height:72px!important}.side .user,.side-bottom{display:none!important}.nav{display:flex!important;overflow:auto!important;padding:8px 0 10px!important}.sx-nav-group{display:none!important}#navigation button{min-width:max-content!important}.sx-topbar{position:relative!important;padding:0 18px!important}.workspace-head{padding:28px 20px 22px!important;align-items:stretch!important;flex-direction:column!important}.server-select{min-width:0!important;width:100%!important}#serverContent{padding-left:20px!important;padding-right:20px!important}.fields{grid-template-columns:1fr!important}.field.full{grid-column:auto!important}}
    @media(max-width:680px){
      .sx-topbar{height:58px!important}.sx-breadcrumb span,.sx-top-status{display:none!important}.workspace-head h1{font-size:28px!important}.sx-summary{grid-template-columns:1fr}.sx-summary-main{grid-column:auto}.sx-hub-card{padding:21px}.sx-hub-actions{display:grid;grid-template-columns:1fr 1fr}.sx-hub-button{padding:0 10px}.sanction-toolbar{grid-template-columns:1fr!important}.sanction-head,.sanction-body{display:grid!important;grid-template-columns:1fr!important}
    }
"""


OXYDE_REBUILD_JS = r"""
    // SentriX V4 — the historical API/save code stays untouched; only the page renderer changes.
    (() => {
      "use strict";
      const MODE_KEY="sentrix_dashboard_mode_v1";
      try{localStorage.setItem(MODE_KEY,"advanced");}catch(_){}

      const sxPages={
        overview:{label:"Vue d'ensemble",group:"Dashboard",icon:"V",eyebrow:"TABLEAU DE BORD"},
        general:{label:"Général",group:"Configuration",icon:"G",eyebrow:"CONFIGURATION"},
        security:{label:"Sécurité",group:"Configuration",icon:"S",eyebrow:"PROTECTION"},
        sanctions:{label:"Sanctions",group:"Configuration",icon:"M",eyebrow:"MODÉRATION"},
        logs:{label:"Logs",group:"Configuration",icon:"L",eyebrow:"JOURNAUX"},
        welcome:{label:"Accueil",group:"Communauté",icon:"A",eyebrow:"COMMUNAUTÉ"},
        levels:{label:"Niveaux",group:"Communauté",icon:"N",eyebrow:"COMMUNAUTÉ"},
        tickets:{label:"Tickets",group:"Communauté",icon:"T",eyebrow:"COMMUNAUTÉ"},
        ai:{label:"Intelligence artificielle",group:"Outils",icon:"IA",eyebrow:"OUTILS"},
        notifications:{label:"Notifications",group:"Outils",icon:"NT",eyebrow:"OUTILS"},
        embeds:{label:"Embeds",group:"Outils",icon:"E",eyebrow:"OUTILS"},
        roles:{label:"Rôles et salons",group:"Outils",icon:"R",eyebrow:"SERVEUR"}
      };

      tabs.overview={title:"Vue d'ensemble",description:"Pilotez les fonctions essentielles de SentriX depuis un seul espace.",fields:[]};

      const originalRenderTab=renderTab;
      const originalSelectGuild=selectGuild;

      function pageInfo(){return sxPages[state.tab]||sxPages.general;}
      function activePageLabel(){return pageInfo().label;}

      function ensureTopbar(){
        const workspace=document.querySelector("#dashboard .workspace");
        const head=workspace?.querySelector(".workspace-head");
        if(!workspace||!head)return;
        let top=document.getElementById("sxV4Topbar");
        if(!top){
          top=document.createElement("div");
          top.id="sxV4Topbar";
          top.className="sx-topbar";
          top.innerHTML='<div class="sx-breadcrumb"><strong>SentriX</strong><i>/</i><span id="sxV4Crumb">Dashboard</span></div><div class="sx-top-actions"><div class="sx-top-status">Opérationnel</div><button id="sxV4Save" class="sx-top-save hidden" type="button">Enregistrer</button></div>';
          workspace.insertBefore(top,head);
          document.getElementById("sxV4Save")?.addEventListener("click",()=>document.getElementById("settingsForm")?.requestSubmit());
        }
      }

      function ensureEyebrow(){
        const title=document.getElementById("tabTitle");
        const wrap=title?.parentElement;
        if(!wrap)return null;
        let eyebrow=document.getElementById("sxV4Eyebrow");
        if(!eyebrow){eyebrow=document.createElement("span");eyebrow.id="sxV4Eyebrow";eyebrow.className="sx-page-eyebrow";wrap.insertBefore(eyebrow,title);}
        return eyebrow;
      }

      function rebuildNavigation(){
        const nav=document.getElementById("navigation");
        if(!nav||nav.dataset.sxV4Ready==="1")return;
        nav.dataset.sxV4Ready="1";
        const groups=["Dashboard","Configuration","Communauté","Outils"];
        nav.innerHTML=groups.map(group=>{
          const pages=Object.entries(sxPages).filter(([,meta])=>meta.group===group);
          return '<div class="sx-nav-group">'+group+'</div>'+pages.map(([key,meta])=>'<button type="button" data-tab="'+key+'"><span class="sx-nav-icon">'+meta.icon+'</span><span>'+meta.label+'</span></button>').join("");
        }).join("");
      }

      function syncChrome(){
        ensureTopbar();rebuildNavigation();
        const info=pageInfo();
        const eye=ensureEyebrow();if(eye)eye.textContent=info.eyebrow;
        const crumb=document.getElementById("sxV4Crumb");if(crumb)crumb.textContent=info.label;
        document.body.dataset.tab=state.tab;
        document.getElementById("navigation")?.querySelectorAll("button[data-tab]").forEach(btn=>btn.classList.toggle("active",btn.dataset.tab===state.tab));
        const save=document.getElementById("sxV4Save");
        if(save)save.classList.toggle("hidden",state.tab==="overview"||state.tab==="sanctions");
      }

      function overviewCard(kicker,title,copy,actions){
        return '<article class="sx-hub-card"><div><div class="sx-kicker">'+kicker+'</div><h3>'+title+'</h3><p>'+copy+'</p></div><div class="sx-hub-actions">'+actions.map((a,i)=>'<button type="button" class="sx-hub-button '+(i===0?'primary':'')+'" data-go-tab="'+a[0]+'">'+a[1]+'</button>').join("")+'</div></article>';
      }

      function renderOverview(){
        const d=state.guildData||{},g=d.guild||{},m=d.metrics||{};
        const latency=state.publicData?.latency_ms==null?"—":number(state.publicData.latency_ms)+" ms";
        const fields=document.getElementById("fields");if(!fields)return;
        fields.innerHTML='<div class="sx-overview">'
          +'<div class="sx-summary"><section class="sx-summary-main"><div class="sx-kicker">SENTRIX</div><h2>'+esc(g.name||"Votre serveur")+'</h2><p>Configurez, sécurisez et gérez votre communauté. Chaque bouton ouvre une seule page complète : aucune mosaïque, aucun aperçu miniature.</p></section>'
          +'<article class="sx-summary-stat"><small>Membres</small><strong>'+number(g.members||0)+'</strong><span>sur le serveur</span></article>'
          +'<article class="sx-summary-stat"><small>Tickets ouverts</small><strong>'+number(m.open_tickets||0)+'</strong><span>à traiter</span></article>'
          +'<article class="sx-summary-stat"><small>Latence</small><strong>'+latency+'</strong><span>Discord</span></article></div>'
          +'<div class="sx-hubs">'
          +overviewCard('COMMUNAUTÉ','Accueil et tickets','Préparez l’arrivée des membres et organisez le support de votre serveur.',[['welcome','Accueil'],['tickets','Tickets']])
          +overviewCard('PROTECTION','Sécurité et modération','Réglez l’AutoMod, consultez les sanctions et gardez un historique clair des actions importantes.',[['security','Sécurité'],['sanctions','Sanctions'],['logs','Logs']])
          +overviewCard('PERSONNALISATION','Niveaux, rôles et salons','Adaptez la progression des membres et reliez les rôles et salons utilisés par SentriX.',[['levels','Niveaux'],['roles','Rôles et salons']])
          +overviewCard('OUTILS','IA, notifications et embeds','Configurez l’intelligence artificielle, vos notifications sociales et les messages enrichis.',[['ai','Intelligence artificielle'],['notifications','Notifications'],['embeds','Embeds']])
          +'</div></div>';
        fields.querySelectorAll("[data-go-tab]").forEach(button=>button.addEventListener("click",()=>openTab(button.dataset.goTab)));
      }

      function addSectionHeading(){
        if(state.tab==="overview"||state.tab==="sanctions"||state.tab==="notifications")return;
        const fields=document.getElementById("fields");
        if(!fields||fields.querySelector(".sx-section-head"))return;
        const head=document.createElement("div");head.className="sx-section-head";
        head.innerHTML='<small>'+pageInfo().eyebrow+'</small><h2>'+esc(activePageLabel())+'</h2><p>Modifiez uniquement les réglages nécessaires puis enregistrez vos changements.</p>';
        fields.insertBefore(head,fields.firstChild);
      }

      function renderV4(){
        if(!state.guildData)return;
        syncChrome();
        if(state.tab==="overview"){
          document.getElementById("tabTitle").textContent="Vue d'ensemble";
          document.getElementById("tabDescription").textContent="Retrouvez les fonctions principales de SentriX, organisées comme un vrai panneau de configuration.";
          renderOverview();
          document.getElementById("saveBar")?.classList.add("hidden");
          state.dirty=false;
          return;
        }
        originalRenderTab();
        syncChrome();
        addSectionHeading();
      }
      renderTab=renderV4;

      function openTab(tab){
        if(!sxPages[tab]||!tabs[tab])return;
        if(state.dirty&&!confirm("Vous avez des modifications non enregistrées. Changer de page ?"))return;
        state.tab=tab;state.dirty=false;
        try{history.replaceState(null,"","#"+tab);}catch(_){}
        renderTab();window.scrollTo({top:0,behavior:"smooth"});
      }

      selectGuild=async function(value){
        await originalSelectGuild(value);
        if(state.guildData){
          const wanted=(location.hash||"").replace(/^#/,"");
          if(wanted&&sxPages[wanted]&&tabs[wanted])state.tab=wanted;
          else if(!sxPages[state.tab])state.tab="overview";
          renderTab();
        }
      };

      function initialPage(){
        const q=new URLSearchParams(location.search).get("tab");
        const h=(location.hash||"").replace(/^#/,"");
        const wanted=q||h;
        state.tab=(wanted&&sxPages[wanted]&&tabs[wanted])?wanted:"overview";
      }

      // Original dashboard listener still handles all nav buttons. We only add hash/chrome sync.
      document.getElementById("navigation")?.addEventListener("click",event=>{
        const button=event.target.closest("button[data-tab]");if(!button)return;
        state.tab=button.dataset.tab;
        try{history.replaceState(null,"","#"+state.tab);}catch(_){}
        setTimeout(syncChrome,0);
      });

      // Force the old simple-mode scripts to stay dormant even when they are appended later.
      const neutralizeLegacy=()=>{
        try{localStorage.setItem(MODE_KEY,"advanced");}catch(_){}
        document.body?.classList.remove("sx-simple-mode","sx-simple-home-active","sx-simple-detail");
        document.body?.classList.add("sx-simple-advanced");
        document.getElementById("sxSimpleHome")?.classList.add("hidden");
      };

      initialPage();ensureTopbar();rebuildNavigation();syncChrome();neutralizeLegacy();
      window.addEventListener("hashchange",()=>{const page=(location.hash||"").replace(/^#/,"");if(page&&sxPages[page]&&tabs[page]&&state.guildData){state.tab=page;renderTab();}});
      document.addEventListener("DOMContentLoaded",()=>{neutralizeLegacy();syncChrome();setTimeout(neutralizeLegacy,150);setTimeout(neutralizeLegacy,700);},{once:true});
    })();
"""


def apply_dashboard_pages(html: str) -> str:
    """Apply the clean V4 presentation to the native SentriX dashboard HTML."""
    if not isinstance(html, str) or "</style>" not in html:
        return html
    if "SentriX dashboard V4" not in html:
        html = html.replace("  </style>", OXYDE_REBUILD_CSS + "\n  </style>", 1)
    marker = "    Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true));"
    if marker in html and "SentriX V4" not in html:
        html = html.replace(marker, OXYDE_REBUILD_JS + "\n" + marker, 1)
    return html
