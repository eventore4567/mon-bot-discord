"""Major V5 presentation/UX upgrade for the SentriX dashboard.

This layer deliberately stays client-side. It does not replace OAuth, guild permission
checks, CSRF protection, database writes or any dashboard API. It enhances the V4/V3
page router with a stronger visual hierarchy, setup health, live page summaries, search,
a command palette, better dirty-state feedback and a live welcome preview.
"""

from __future__ import annotations


MAJOR_V5_CSS = r"""
<style id="sentrix-dashboard-v5-css">
  :root{
    --v5-bg:#07080c;
    --v5-panel:#111621;
    --v5-panel-2:#151b29;
    --v5-panel-3:#1a2131;
    --v5-border:#252d40;
    --v5-border-strong:#343e57;
    --v5-text:#f5f3fb;
    --v5-muted:#8d95aa;
    --v5-purple:#9277ff;
    --v5-purple-2:#b7a6ff;
    --v5-green:#55d99c;
    --v5-amber:#efbd63;
    --v5-red:#ff7187;
    --v5-shadow:0 20px 60px rgba(0,0,0,.28);
  }

  body{
    background:
      radial-gradient(900px 520px at 82% -180px,rgba(113,77,235,.16),transparent 72%),
      radial-gradient(620px 420px at 12% 112%,rgba(81,55,155,.07),transparent 72%),
      var(--v5-bg)!important;
  }

  /* Public landing: cleaner, more premium, less empty. */
  #landing .top{height:76px!important;border-bottom-color:#1d2332!important;background:rgba(7,8,12,.82)!important}
  #landing .hero{padding-top:105px!important;padding-bottom:78px!important;gap:76px!important}
  #landing .hero h1{max-width:760px!important;font-weight:900!important}
  #landing .hero p{max-width:640px!important;color:#929aaf!important}
  #landing .preview{border-color:#2b344a!important;background:linear-gradient(155deg,#161b29,#0c0f17)!important;box-shadow:0 34px 95px rgba(0,0,0,.42)!important;transform:none!important}
  #landing .feature{border-color:#242d41!important;background:linear-gradient(145deg,#111622,#0d111a)!important;transition:.16s ease!important}
  #landing .feature:hover{transform:translateY(-2px)!important;border-color:#43395f!important}

  /* Desktop shell. */
  #dashboard .shell{grid-template-columns:294px minmax(0,1fr)!important}
  #dashboard .side{padding-left:16px!important;padding-right:16px!important;background:linear-gradient(180deg,#0d1018 0%,#090b11 100%)!important}
  #dashboard .side .brand{height:88px!important;padding-left:18px!important;padding-right:18px!important;margin-left:-16px!important;margin-right:-16px!important}
  #dashboard .side .user{margin:8px 0 14px!important;border-color:#222a3d!important;background:#10151f!important;box-shadow:0 9px 30px rgba(0,0,0,.16)!important}
  #dashboard #navigation{padding-top:4px!important}
  #dashboard .sx-nav-group{padding:17px 10px 6px!important;color:#5f687d!important}
  #dashboard #navigation button{min-height:45px!important;border-radius:12px!important;padding:9px 11px!important}
  #dashboard #navigation button.active{background:linear-gradient(90deg,rgba(146,119,255,.19),rgba(146,119,255,.055))!important;border-color:rgba(146,119,255,.19)!important;box-shadow:inset 3px 0 0 #9277ff!important}
  #dashboard #navigation button.active .sx-nav-icon{background:#211b36!important;border-color:#4a3a76!important;color:#d8d0ff!important}

  /* Sidebar page search. */
  .sx-v5-nav-search{margin:0 0 7px;padding:0 1px}
  .sx-v5-nav-search label{display:block;margin:0 0 6px 7px;color:#5f687c;font-size:9px;font-weight:900;letter-spacing:.12em;text-transform:uppercase}
  .sx-v5-nav-search-box{position:relative}
  .sx-v5-nav-search input{height:39px!important;padding:0 54px 0 12px!important;border-radius:11px!important;border-color:#222a3d!important;background:#0c1018!important;font-size:12px!important}
  .sx-v5-nav-search kbd{position:absolute;right:9px;top:9px;border:1px solid #30384d;border-radius:6px;background:#141927;color:#70798e;padding:2px 5px;font:700 9px ui-monospace,SFMono-Regular,Menlo,monospace}
  #navigation button.sx-v5-filtered,.sx-nav-group.sx-v5-filtered{display:none!important}

  /* Top bar + page chrome. */
  #dashboard .sx-topbar{height:72px!important;padding:0 36px!important;border-bottom-color:#1d2434!important;background:rgba(8,10,15,.87)!important}
  .sx-v5-command-button{height:38px;padding:0 12px;border:1px solid #272f43;border-radius:10px;background:#111621;color:#8e96a9;cursor:pointer;font-size:11px;font-weight:800;display:flex;align-items:center;gap:8px}
  .sx-v5-command-button:hover{border-color:#4b406b;color:#d9d3ed;background:#151b29}
  .sx-v5-command-button kbd{border:1px solid #353e55;border-radius:6px;padding:2px 5px;background:#0b0e15;color:#727b90;font:800 9px ui-monospace,SFMono-Regular,Menlo,monospace}
  #dashboard .workspace-head{padding:36px 36px 25px!important;background:linear-gradient(180deg,rgba(15,18,28,.5),transparent)!important}
  #dashboard .workspace-head h1{font-size:36px!important}
  #dashboard .workspace-head p{max-width:760px!important;color:#858da2!important}
  #dashboard #serverContent{padding-left:36px!important;padding-right:36px!important;animation:sxV5PageIn .2s ease both}
  @keyframes sxV5PageIn{from{opacity:.25;transform:translateY(4px)}to{opacity:1;transform:none}}

  /* Overview hero. */
  .sx-v5-overview-hero{
    position:relative;overflow:hidden;display:grid;grid-template-columns:minmax(0,1.4fr) minmax(320px,.6fr);gap:20px;
    padding:30px;border:1px solid #2b344a;border-radius:24px;background:linear-gradient(145deg,#171d2c,#10141e 72%);
    box-shadow:0 28px 80px rgba(0,0,0,.31);min-height:250px;
  }
  .sx-v5-overview-hero::after{content:"";position:absolute;right:-90px;top:-150px;width:420px;height:420px;border-radius:50%;background:radial-gradient(circle,rgba(147,119,255,.23),rgba(91,62,183,.09) 42%,transparent 69%);pointer-events:none}
  .sx-v5-identity{position:relative;z-index:1;display:flex;gap:18px;align-items:flex-start}
  .sx-v5-guild-avatar{width:72px;height:72px;flex:0 0 72px;border-radius:20px;border:1px solid #4b4167;background:linear-gradient(145deg,#2b2442,#151824);display:grid;place-items:center;overflow:hidden;color:#d6cdff;font-size:24px;font-weight:950;box-shadow:0 14px 38px rgba(0,0,0,.23)}
  .sx-v5-guild-avatar img{width:100%;height:100%;object-fit:cover}
  .sx-v5-identity-copy{min-width:0}
  .sx-v5-kicker{color:#b7a6ff;font-size:10px;font-weight:950;letter-spacing:.13em;text-transform:uppercase;margin:2px 0 8px}
  .sx-v5-identity h2{margin:0;font-size:29px;letter-spacing:-.04em;color:#f7f5fd}
  .sx-v5-identity p{max-width:650px;margin:9px 0 0;color:#9098ad;line-height:1.58;font-size:13px}
  .sx-v5-quick-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:22px}
  .sx-v5-quick-actions button{height:41px;padding:0 14px;border:1px solid #343d54;border-radius:11px;background:#171d2a;color:#e8e5f0;font-weight:820;cursor:pointer}
  .sx-v5-quick-actions button:first-child{border-color:#674fbd;background:linear-gradient(135deg,#2c2449,#1d1931);color:#cbbfff}
  .sx-v5-quick-actions button:hover{transform:translateY(-1px);border-color:#61517f}
  .sx-v5-health{position:relative;z-index:1;border:1px solid #2a3247;border-radius:19px;background:rgba(10,13,20,.62);padding:21px;display:grid;grid-template-columns:112px 1fr;gap:18px;align-items:center;align-self:stretch}
  .sx-v5-score{--score:0;position:relative;width:108px;height:108px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#9277ff calc(var(--score)*1%),#242b3d 0);box-shadow:inset 0 0 0 1px #343c53}
  .sx-v5-score::before{content:"";position:absolute;inset:9px;border-radius:50%;background:#10141e;border:1px solid #262e42}
  .sx-v5-score strong,.sx-v5-score span{position:relative;z-index:1;display:block;text-align:center}
  .sx-v5-score strong{font-size:25px;letter-spacing:-.04em}.sx-v5-score span{font-size:9px;color:#727a8f;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-top:-2px}
  .sx-v5-health-copy h3{margin:0;color:#f2eff8;font-size:16px}.sx-v5-health-copy p{margin:7px 0 0;color:#7f879b;font-size:11px;line-height:1.55}
  .sx-v5-health-meta{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}
  .sx-v5-health-meta div{padding:10px;border:1px solid #252d40;border-radius:10px;background:#111621}
  .sx-v5-health-meta small{display:block;color:#6e768a;font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.08em}.sx-v5-health-meta b{display:block;margin-top:4px;font-size:13px}

  .sx-v5-insights{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
  .sx-v5-insight{padding:18px;border:1px solid #252d40;border-radius:16px;background:linear-gradient(145deg,#131824,#0f131c);min-height:116px}
  .sx-v5-insight small{display:block;color:#767f94;font-size:9px;font-weight:900;letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px}.sx-v5-insight b{font-size:14px;color:#ece9f4}.sx-v5-insight p{margin:6px 0 0;color:#747d91;font-size:11px;line-height:1.5}.sx-v5-insight.ready{border-color:#294837;background:linear-gradient(145deg,#111c19,#0e1416)}

  /* Existing V4 cards get a stronger hierarchy. */
  #dashboard .sx-summary{gap:14px!important}
  #dashboard .sx-summary-main,#dashboard .sx-summary-stat,#dashboard .sx-hub-card{border-color:#283147!important;background:linear-gradient(145deg,#151b29,#10141e)!important;box-shadow:0 18px 52px rgba(0,0,0,.21)!important}
  #dashboard .sx-summary-main{display:none!important}
  #dashboard .sx-hub-card{min-height:230px!important;padding:28px!important}
  #dashboard .sx-hub-card h3{font-size:22px!important}
  #dashboard .sx-hub-card p{color:#8790a5!important}

  /* Per-page health/status strip. */
  .sx-v5-page-status{grid-column:1/-1!important;display:grid;grid-template-columns:minmax(0,1fr) repeat(3,minmax(115px,.32fr));gap:10px;padding:16px;border:1px solid #252e42;border-radius:17px;background:linear-gradient(145deg,#121722,#0e121b);box-shadow:0 14px 42px rgba(0,0,0,.16)}
  .sx-v5-page-status-main{padding:3px 5px}.sx-v5-page-status-main small,.sx-v5-status-cell small{display:block;color:#70798e;font-size:8px;font-weight:950;letter-spacing:.1em;text-transform:uppercase}.sx-v5-page-status-main b{display:block;margin-top:5px;font-size:14px;color:#eeeaf6}.sx-v5-page-status-main p{margin:4px 0 0;color:#727b90;font-size:10px;line-height:1.45}
  .sx-v5-status-cell{padding:11px 12px;border:1px solid #242c3e;border-radius:11px;background:#111621}.sx-v5-status-cell b{display:block;margin-top:4px;font-size:14px;color:#e8e5ef}

  /* Form fields become clear setting cards. */
  #dashboard .fields{gap:14px!important}
  #dashboard .field,#dashboard .switch{position:relative!important;border-color:#252d40!important;background:linear-gradient(145deg,#131824,#10141e)!important;box-shadow:0 13px 38px rgba(0,0,0,.14)!important;transition:border-color .15s ease,transform .15s ease,box-shadow .15s ease!important}
  #dashboard .field:hover,#dashboard .switch:hover{border-color:#343e56!important;box-shadow:0 18px 46px rgba(0,0,0,.2)!important}
  #dashboard .field:focus-within,#dashboard .switch:focus-within{border-color:#5d4b96!important}
  #dashboard .field.sx-v5-configured::after{content:"Configuré";position:absolute;right:14px;top:14px;border:1px solid #304a40;border-radius:999px;background:#13221d;color:#76cba5;padding:3px 7px;font-size:8px;font-weight:900;letter-spacing:.05em;text-transform:uppercase}
  #dashboard .field.sx-v5-dirty,#dashboard .switch.sx-v5-dirty{border-color:#6c55bd!important;box-shadow:0 0 0 3px rgba(146,119,255,.08),0 16px 44px rgba(0,0,0,.18)!important}
  #dashboard .switch.sx-v5-enabled{border-color:#30493e!important;background:linear-gradient(145deg,#131e1b,#10171a)!important}
  #dashboard .switch input{box-shadow:none!important}
  #dashboard .switch input:checked{background:#9277ff!important}

  /* Welcome page live preview. */
  .sx-v5-preview-wrap{grid-column:1/-1!important;display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);gap:14px;margin-top:4px}
  .sx-v5-preview-copy,.sx-v5-discord-preview{border:1px solid #252d40;border-radius:17px;background:linear-gradient(145deg,#131824,#0f131c);padding:20px}
  .sx-v5-preview-copy small{display:block;color:#9d8cff;font-size:9px;font-weight:950;letter-spacing:.1em;text-transform:uppercase}.sx-v5-preview-copy h3{margin:7px 0 7px;font-size:17px}.sx-v5-preview-copy p{margin:0;color:#778095;font-size:11px;line-height:1.55}
  .sx-v5-discord-preview{background:#111318!important}
  .sx-v5-discord-line{display:flex;gap:12px}.sx-v5-discord-avatar{width:42px;height:42px;flex:0 0 42px;border-radius:50%;background:linear-gradient(145deg,#8e72ff,#4b3898);display:grid;place-items:center;font-weight:900;color:#fff}.sx-v5-discord-message{min-width:0}.sx-v5-discord-author{display:flex;gap:7px;align-items:center}.sx-v5-discord-author b{font-size:13px;color:#f1f2f5}.sx-v5-discord-author span{font-size:9px;color:#697080}.sx-v5-discord-text{margin-top:4px;color:#d6d8dd;font-size:12px;line-height:1.55;white-space:pre-wrap;word-break:break-word}

  /* Save state. */
  #dashboard .savebar{border-color:#2d3650!important;background:rgba(10,13,20,.94)!important}
  #dashboard .savebar.sx-v5-dirty-bar{border-color:#604b9e!important;box-shadow:0 20px 58px rgba(0,0,0,.32),0 0 0 3px rgba(146,119,255,.05)!important}
  #dashboard #sxV4Save.sx-v5-dirty-save{box-shadow:0 0 0 3px rgba(146,119,255,.1),0 12px 30px rgba(99,67,204,.24)!important}

  /* Sanctions / notifications. */
  #dashboard .sanction-toolbar{padding:14px;border:1px solid #252d40;border-radius:15px;background:#111621!important}
  #dashboard .sanction-card,#dashboard .notification-item{border-color:#252d40!important;background:linear-gradient(145deg,#131824,#10141e)!important;box-shadow:0 14px 42px rgba(0,0,0,.16)!important}
  #dashboard .sanction-card:hover,#dashboard .notification-item:hover{border-color:#353e55!important}

  /* Command palette. */
  .sx-v5-palette{position:fixed;inset:0;z-index:9999;display:grid;place-items:start center;padding-top:min(13vh,120px);background:rgba(3,4,7,.68);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
  .sx-v5-palette.hidden{display:none!important}
  .sx-v5-palette-card{width:min(640px,calc(100vw - 34px));overflow:hidden;border:1px solid #343d55;border-radius:19px;background:#0e121b;box-shadow:0 36px 120px rgba(0,0,0,.58)}
  .sx-v5-palette-head{padding:14px;border-bottom:1px solid #232b3d}.sx-v5-palette-head input{height:46px!important;border:0!important;background:#141925!important;font-size:14px!important}
  .sx-v5-palette-results{max-height:420px;overflow:auto;padding:8px}.sx-v5-palette-result{width:100%;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:12px;border:1px solid transparent;border-radius:11px;background:transparent;color:#d9d6e2;text-align:left;cursor:pointer}.sx-v5-palette-result:hover,.sx-v5-palette-result.active{background:#171c29;border-color:#2b3448;color:#fff}.sx-v5-palette-result span{color:#6e768a;font-size:10px}.sx-v5-palette-empty{padding:28px;text-align:center;color:#777f94;font-size:12px}
  .sx-v5-palette-foot{padding:11px 14px;border-top:1px solid #232b3d;color:#626a7d;font-size:10px;display:flex;justify-content:space-between}

  /* Mobile/tablet remains one real page at a time. */
  @media(max-width:1180px){
    .sx-v5-overview-hero{grid-template-columns:1fr}.sx-v5-health{grid-template-columns:112px minmax(0,1fr)}.sx-v5-insights{grid-template-columns:1fr 1fr}.sx-v5-page-status{grid-template-columns:1fr 1fr}.sx-v5-page-status-main{grid-column:1/-1}
  }
  @media(max-width:980px){
    #dashboard .shell{grid-template-columns:1fr!important}#dashboard .sx-v5-nav-search{display:none!important}#dashboard .sx-topbar{padding-left:20px!important;padding-right:20px!important}#dashboard .workspace-head{padding-left:20px!important;padding-right:20px!important}#dashboard #serverContent{padding-left:20px!important;padding-right:20px!important}.sx-v5-preview-wrap{grid-template-columns:1fr}.sx-v5-command-button kbd{display:none}
  }
  @media(max-width:680px){
    .sx-v5-overview-hero{padding:20px;border-radius:19px}.sx-v5-identity{display:grid}.sx-v5-guild-avatar{width:58px;height:58px;flex-basis:58px;border-radius:16px}.sx-v5-identity h2{font-size:24px}.sx-v5-health{grid-template-columns:1fr;text-align:center}.sx-v5-score{margin:auto}.sx-v5-health-meta{grid-template-columns:1fr 1fr}.sx-v5-insights{grid-template-columns:1fr}.sx-v5-page-status{grid-template-columns:1fr}.sx-v5-page-status-main{grid-column:auto}.sx-v5-quick-actions{display:grid;grid-template-columns:1fr 1fr}.sx-v5-command-button{width:38px;padding:0;justify-content:center;font-size:0}.sx-v5-command-button::after{content:"K";font-size:11px}.sx-v5-palette{padding-top:12px;place-items:start center}
  }
  @media(prefers-reduced-motion:reduce){#dashboard #serverContent{animation:none!important}.sx-v5-quick-actions button,#dashboard .field,#dashboard .switch{transition:none!important}}
</style>
"""


MAJOR_V5_JS = r"""
<script id="sentrix-dashboard-v5-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardV5) return;
  window.__sentrixDashboardV5 = true;

  const PAGE_META = {
    overview:["Vue d'ensemble","Résumé du serveur et accès rapides"],
    general:["Général","Réglages de base du serveur"],
    security:["Sécurité","Protections automatiques actives"],
    sanctions:["Sanctions","Historique et actions de modération"],
    logs:["Logs","Destination des journaux du serveur"],
    welcome:["Accueil","Arrivée et départ des membres"],
    levels:["Niveaux","Progression et annonces d'expérience"],
    tickets:["Tickets","Organisation du support"],
    ai:["Intelligence artificielle","Modèle, limites et mémoire"],
    notifications:["Notifications","Publications sociales automatiques"],
    embeds:["Embeds","Créateur de messages enrichis"],
    roles:["Rôles et salons","Connexions entre SentriX et Discord"]
  };
  const dirtyKeys = new Set();
  let decorateTimer = null;
  let paletteIndex = 0;

  const getState = () => {
    try { return typeof state !== "undefined" ? state : null; }
    catch (_) { return null; }
  };
  const text = value => String(value ?? "");
  const html = value => text(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const fmt = value => Number(value || 0).toLocaleString("fr-FR");
  const isSet = value => value !== null && value !== undefined && value !== "" && value !== 0 && value !== false;

  function scheduleDecorate(delay=0){
    clearTimeout(decorateTimer);
    decorateTimer=setTimeout(decorate,delay);
  }

  function ensureSidebarSearch(){
    const nav=document.getElementById("navigation");
    if(!nav || document.getElementById("sxV5NavSearch")) return;
    const wrap=document.createElement("div");
    wrap.id="sxV5NavSearch";
    wrap.className="sx-v5-nav-search";
    wrap.innerHTML='<label for="sxV5NavSearchInput">Navigation</label><div class="sx-v5-nav-search-box"><input id="sxV5NavSearchInput" autocomplete="off" placeholder="Rechercher une page"><kbd>/</kbd></div>';
    nav.parentNode.insertBefore(wrap,nav);
    const input=document.getElementById("sxV5NavSearchInput");
    const apply=()=>{
      const q=text(input.value).trim().toLocaleLowerCase("fr");
      nav.querySelectorAll("button[data-tab]").forEach(button=>button.classList.toggle("sx-v5-filtered",!!q&&!text(button.textContent).toLocaleLowerCase("fr").includes(q)));
      nav.querySelectorAll(".sx-nav-group").forEach(group=>{
        let node=group.nextElementSibling,visible=false;
        while(node && !node.classList.contains("sx-nav-group")){
          if(node.matches?.("button[data-tab]") && !node.classList.contains("sx-v5-filtered")) visible=true;
          node=node.nextElementSibling;
        }
        group.classList.toggle("sx-v5-filtered",!visible);
      });
    };
    input.addEventListener("input",apply);
    input.addEventListener("keydown",event=>{if(event.key==="Escape"){input.value="";apply();input.blur();}});
  }

  function navPages(){
    return [...document.querySelectorAll("#navigation button[data-tab]")].map(button=>({key:button.dataset.tab,label:text(button.textContent).trim()}));
  }

  function ensurePalette(){
    if(document.getElementById("sxV5Palette")) return;
    const root=document.createElement("div");
    root.id="sxV5Palette";
    root.className="sx-v5-palette hidden";
    root.innerHTML='<div class="sx-v5-palette-card" role="dialog" aria-modal="true" aria-label="Navigation rapide"><div class="sx-v5-palette-head"><input id="sxV5PaletteInput" autocomplete="off" placeholder="Aller vers une page…"></div><div class="sx-v5-palette-results" id="sxV5PaletteResults"></div><div class="sx-v5-palette-foot"><span>Entrée pour ouvrir</span><span>Échap pour fermer</span></div></div>';
    document.body.appendChild(root);
    root.addEventListener("mousedown",event=>{if(event.target===root)closePalette();});
    document.getElementById("sxV5PaletteInput")?.addEventListener("input",()=>{paletteIndex=0;renderPalette();});
    document.getElementById("sxV5PaletteInput")?.addEventListener("keydown",event=>{
      const rows=[...document.querySelectorAll(".sx-v5-palette-result")];
      if(event.key==="ArrowDown"){event.preventDefault();paletteIndex=Math.min(rows.length-1,paletteIndex+1);renderPalette();}
      else if(event.key==="ArrowUp"){event.preventDefault();paletteIndex=Math.max(0,paletteIndex-1);renderPalette();}
      else if(event.key==="Enter"){event.preventDefault();rows[paletteIndex]?.click();}
      else if(event.key==="Escape")closePalette();
    });
  }

  function renderPalette(){
    const list=document.getElementById("sxV5PaletteResults");
    const input=document.getElementById("sxV5PaletteInput");
    if(!list||!input)return;
    const q=text(input.value).trim().toLocaleLowerCase("fr");
    const pages=navPages().filter(page=>!q||page.label.toLocaleLowerCase("fr").includes(q)||page.key.includes(q));
    if(!pages.length){list.innerHTML='<div class="sx-v5-palette-empty">Aucune page trouvée.</div>';return;}
    paletteIndex=Math.max(0,Math.min(paletteIndex,pages.length-1));
    list.innerHTML=pages.map((page,index)=>'<button type="button" class="sx-v5-palette-result '+(index===paletteIndex?'active':'')+'" data-v5-page="'+html(page.key)+'"><b>'+html(page.label)+'</b><span>'+html(PAGE_META[page.key]?.[1]||"Ouvrir")+'</span></button>').join("");
    list.querySelectorAll("[data-v5-page]").forEach(button=>button.addEventListener("click",()=>{goPage(button.dataset.v5Page);closePalette();}));
    list.querySelector(".active")?.scrollIntoView({block:"nearest"});
  }

  function openPalette(){
    ensurePalette();
    const root=document.getElementById("sxV5Palette"),input=document.getElementById("sxV5PaletteInput");
    if(!root||!input)return;
    root.classList.remove("hidden");
    input.value="";paletteIndex=0;renderPalette();setTimeout(()=>input.focus(),0);
  }
  function closePalette(){document.getElementById("sxV5Palette")?.classList.add("hidden");}

  function ensureTopAction(){
    const actions=document.querySelector("#sxV4Topbar .sx-top-actions");
    if(!actions || document.getElementById("sxV5Command")) return;
    const button=document.createElement("button");
    button.id="sxV5Command";
    button.type="button";
    button.className="sx-v5-command-button";
    button.innerHTML='<span>Rechercher</span><kbd>⌘ K</kbd>';
    button.addEventListener("click",openPalette);
    actions.insertBefore(button,actions.firstChild);
  }

  function goPage(key){
    const button=document.querySelector('#navigation button[data-tab="'+CSS.escape(key)+'"]');
    if(button){button.click();setTimeout(()=>window.scrollTo({top:0,behavior:"smooth"}),10);}
  }

  function completionData(s){
    const settings=s?.guildData?.settings||{};
    const automod=s?.guildData?.automod||{};
    const ai=s?.guildData?.ai||{};
    const logKeys=["log_messages","log_members","log_voice","log_roles","log_server","log_automod","log_moderation","log_channel"];
    const protectionKeys=["antispam","antilink","antiinvite","antimention","anticaps","antiemoji","antiraid","antibot","antiaccount","antiscam","antinuke","escalation"];
    const logs=logKeys.filter(key=>isSet(settings[key])).length;
    const protections=protectionKeys.filter(key=>Number(automod[key])).length;
    const checks=[
      isSet(settings.prefix),
      isSet(settings.mod_role)||isSet(settings.admin_role),
      logs>0,
      isSet(settings.welcome_channel)&&isSet(settings.welcome_message),
      isSet(settings.autorole)||isSet(settings.member_role),
      isSet(settings.ticket_category)||isSet(settings.ticket_log_channel),
      protections>=3,
      isSet(settings.verification_channel)||isSet(settings.verification_role),
      Number(ai.enabled)===1,
      isSet(settings.level_channel)
    ];
    return {score:Math.round(checks.filter(Boolean).length/checks.length*100),logs,protections,totalProtections:protectionKeys.length};
  }

  function recommendations(s){
    const settings=s.guildData?.settings||{},automod=s.guildData?.automod||{},data=completionData(s);
    const rows=[];
    if(!settings.welcome_channel)rows.push(["Accueil non configuré","Choisissez un salon de bienvenue pour compléter l’arrivée des membres.","welcome"]);
    if(data.logs===0)rows.push(["Logs à relier","Définissez au moins un salon de logs pour garder un historique exploitable.","logs"]);
    if(data.protections<3)rows.push(["Protection à renforcer","Activez plusieurs protections AutoMod adaptées à votre communauté.","security"]);
    if(!settings.ticket_category&&!settings.ticket_log_channel)rows.push(["Support à préparer","Reliez les tickets à une catégorie ou un salon de logs.","tickets"]);
    if(!settings.mod_role&&!settings.admin_role)rows.push(["Équipe staff à relier","Associez au moins un rôle de modération ou d’administration.","roles"]);
    while(rows.length<3)rows.push(["Configuration solide","Cette partie essentielle est déjà prête sur votre serveur.","overview"]);
    return rows.slice(0,3);
  }

  function enhanceOverview(){
    const s=getState();
    if(!s?.guildData || s.tab!=="overview")return;
    const overview=document.querySelector("#fields .sx-overview");
    if(!overview)return;
    overview.querySelectorAll(".sx-v5-overview-hero,.sx-v5-insights").forEach(node=>node.remove());
    const guild=s.guildData.guild||{},metrics=s.guildData.metrics||{},health=completionData(s);
    const first=text(guild.name||"S").trim().slice(0,1).toUpperCase();
    const icon=guild.icon_url?'<img src="'+html(guild.icon_url)+'" alt="">':html(first);
    const hero=document.createElement("section");
    hero.className="sx-v5-overview-hero";
    hero.innerHTML='<div class="sx-v5-identity"><div class="sx-v5-guild-avatar">'+icon+'</div><div class="sx-v5-identity-copy"><div class="sx-v5-kicker">CENTRE DE CONTRÔLE</div><h2>'+html(guild.name||"Votre serveur")+'</h2><p>Retrouvez les réglages importants de SentriX dans des pages séparées, avec une vue claire de ce qui est déjà prêt et de ce qui mérite votre attention.</p><div class="sx-v5-quick-actions"><button type="button" data-v5-go="security">Configurer la sécurité</button><button type="button" data-v5-go="welcome">Personnaliser l’accueil</button><button type="button" data-v5-go="tickets">Configurer les tickets</button><button type="button" data-v5-go="logs">Voir les logs</button></div></div></div><aside class="sx-v5-health"><div class="sx-v5-score" style="--score:'+health.score+'"><div><strong>'+health.score+'%</strong><span>configuration</span></div></div><div class="sx-v5-health-copy"><h3>État du serveur</h3><p>Un score indicatif basé sur les réglages principaux déjà reliés à Discord.</p><div class="sx-v5-health-meta"><div><small>Protections</small><b>'+health.protections+'/'+health.totalProtections+'</b></div><div><small>Logs reliés</small><b>'+health.logs+'/8</b></div><div><small>Commandes 24 h</small><b>'+fmt(metrics.commands_24h)+'</b></div><div><small>Tickets ouverts</small><b>'+fmt(metrics.open_tickets)+'</b></div></div></div></aside>';
    overview.insertBefore(hero,overview.firstChild);
    hero.querySelectorAll("[data-v5-go]").forEach(button=>button.addEventListener("click",()=>goPage(button.dataset.v5Go)));

    const insight=document.createElement("section");
    insight.className="sx-v5-insights";
    insight.innerHTML=recommendations(s).map(row=>'<article class="sx-v5-insight '+(row[2]==="overview"?'ready':'')+'"><small>'+(row[2]==="overview"?'PRÊT':'À VÉRIFIER')+'</small><b>'+html(row[0])+'</b><p>'+html(row[1])+'</p></article>').join("");
    const hubs=overview.querySelector(".sx-hubs");
    overview.insertBefore(insight,hubs||null);
  }

  function pageStatusData(s){
    const settings=s.guildData?.settings||{},automod=s.guildData?.automod||{},ai=s.guildData?.ai||{},health=completionData(s);
    const configuredRoles=["mod_role","admin_role","mute_role","warn_role","member_role","booster_role","verification_role"].filter(k=>isSet(settings[k])).length;
    const configuredChannels=["rules_channel","verification_channel","bot_commands_channel","suggest_channel","announce_channel","giveaway_channel","report_channel","error_channel"].filter(k=>isSet(settings[k])).length;
    const notificationCount=(s.guildData?.social_notifications||[]).length;
    const map={
      general:["Configuration principale","Préfixe et niveau de protection utilisés actuellement.",["Préfixe",settings.prefix||"+"],["Sécurité",settings.security_level||"moyen"],["Seuil warns",settings.warn_ban_threshold||"—"]],
      security:["Protection automatique",health.protections+" protections sont actives sur "+health.totalProtections+" disponibles.",["Actives",health.protections],["Disponibles",health.totalProtections],["État",health.protections>=5?"Renforcé":health.protections?"Partiel":"Inactif"]],
      logs:["Journalisation",health.logs+" destinations de logs sont déjà reliées.",["Reliés",health.logs],["Disponibles",8],["État",health.logs>=4?"Complet":health.logs?"Partiel":"À configurer"]],
      welcome:["Accueil des membres",settings.welcome_channel?"Un salon de bienvenue est relié.":"Aucun salon de bienvenue n’est encore relié.",["Bienvenue",settings.welcome_channel?"Configuré":"Non configuré"],["Départ",settings.goodbye_channel?"Configuré":"Non configuré"],["Autorôle",settings.autorole?"Configuré":"Non configuré"]],
      levels:["Progression",settings.level_channel?"Les annonces de niveau ont un salon dédié.":"Aucun salon de niveau n’est encore relié.",["Salon",settings.level_channel?"Configuré":"Non configuré"],["Multiplicateur",settings.xp_multiplier||"1"],["Message",settings.level_message?"Personnalisé":"Par défaut"]],
      tickets:["Support",settings.ticket_category||settings.ticket_log_channel?"Le système de tickets est relié à Discord.":"Le support doit encore être relié à une catégorie ou un salon.",["Catégorie",settings.ticket_category?"Configurée":"Non configurée"],["Logs",settings.ticket_log_channel?"Configurés":"Non configurés"],["Évaluation",Number(settings.ticket_rating_enabled)?"Active":"Inactive"]],
      ai:["Intelligence artificielle",Number(ai.enabled)?"Les fonctions IA sont disponibles sur ce serveur.":"Les fonctions IA sont désactivées.",["État",Number(ai.enabled)?"Active":"Inactive"],["Modèle",ai.default_model||"luna"],["Mémoire",Number(ai.memory_enabled)?"Active":"Inactive"]],
      notifications:["Notifications sociales",notificationCount?notificationCount+" source(s) sont surveillées.":"Aucune source sociale n’est encore configurée.",["Sources",notificationCount],["État",notificationCount?"Actif":"Vide"],["Publication","Automatique"]],
      roles:["Connexions Discord",configuredRoles+" rôles et "+configuredChannels+" salons sont reliés à SentriX.",["Rôles",configuredRoles],["Salons",configuredChannels],["Total",configuredRoles+configuredChannels]]
    };
    return map[s.tab]||null;
  }

  function enhancePageStatus(){
    const s=getState();
    if(!s?.guildData || ["overview","sanctions","embeds"].includes(s.tab))return;
    const fields=document.getElementById("fields");
    if(!fields)return;
    fields.querySelectorAll(".sx-v5-page-status").forEach(node=>node.remove());
    const data=pageStatusData(s);if(!data)return;
    const card=document.createElement("section");
    card.className="sx-v5-page-status";
    card.innerHTML='<div class="sx-v5-page-status-main"><small>APERÇU DE LA PAGE</small><b>'+html(data[0])+'</b><p>'+html(data[1])+'</p></div>'+data.slice(2).map(cell=>'<div class="sx-v5-status-cell"><small>'+html(cell[0])+'</small><b>'+html(cell[1])+'</b></div>').join("");
    const heading=fields.querySelector(".sx-section-head");
    if(heading)heading.insertAdjacentElement("afterend",card);else fields.insertBefore(card,fields.firstChild);
  }

  function controlValue(control){
    if(!control)return"";
    if(control.type==="checkbox")return control.checked;
    return control.value;
  }

  function decorateFields(){
    const fields=document.getElementById("fields");if(!fields)return;
    fields.querySelectorAll(".field").forEach(card=>{
      const control=card.querySelector("[data-key]");
      if(!control)return;
      card.classList.toggle("sx-v5-configured",isSet(controlValue(control)));
      card.classList.toggle("sx-v5-dirty",dirtyKeys.has(control.dataset.key));
    });
    fields.querySelectorAll("label.switch").forEach(card=>{
      const control=card.querySelector("input[data-key]");
      if(!control)return;
      card.classList.toggle("sx-v5-enabled",control.checked);
      card.classList.toggle("sx-v5-dirty",dirtyKeys.has(control.dataset.key));
    });
  }

  function resolvedWelcomeMessage(raw,s){
    const guild=s.guildData?.guild||{};
    return text(raw||"Bienvenue {member} sur {server} !")
      .replaceAll("{member}","@Membre")
      .replaceAll("{username}","membre")
      .replaceAll("{server}",guild.name||"le serveur")
      .replaceAll("{member_count}",fmt(guild.members||0));
  }

  function enhanceWelcomePreview(){
    const s=getState();if(!s?.guildData||s.tab!=="welcome")return;
    const fields=document.getElementById("fields");if(!fields)return;
    fields.querySelectorAll(".sx-v5-preview-wrap").forEach(node=>node.remove());
    const raw=fields.querySelector('[data-key="welcome_message"]')?.value||s.guildData.settings?.welcome_message||"";
    const wrap=document.createElement("section");
    wrap.className="sx-v5-preview-wrap";
    wrap.innerHTML='<div class="sx-v5-preview-copy"><small>PRÉVISUALISATION</small><h3>Voyez le message avant de l’enregistrer</h3><p>Les variables sont remplacées par un exemple pour montrer directement le rendu du texte de bienvenue.</p></div><div class="sx-v5-discord-preview"><div class="sx-v5-discord-line"><div class="sx-v5-discord-avatar">S</div><div class="sx-v5-discord-message"><div class="sx-v5-discord-author"><b>SentriX</b><span>BOT · maintenant</span></div><div class="sx-v5-discord-text" id="sxV5WelcomeText">'+html(resolvedWelcomeMessage(raw,s))+'</div></div></div></div>';
    fields.appendChild(wrap);
  }

  function updateWelcomePreview(){
    const s=getState();if(!s||s.tab!=="welcome")return;
    const target=document.getElementById("sxV5WelcomeText");if(!target)return;
    const raw=document.querySelector('#fields [data-key="welcome_message"]')?.value||"";
    target.textContent=resolvedWelcomeMessage(raw,s);
  }

  function updateDirtyUI(){
    const s=getState();if(!s)return;
    if(!s.dirty && dirtyKeys.size)dirtyKeys.clear();
    const count=dirtyKeys.size;
    const bar=document.getElementById("saveBar"),status=document.getElementById("saveStatus"),top=document.getElementById("sxV4Save");
    bar?.classList.toggle("sx-v5-dirty-bar",!!s.dirty);
    top?.classList.toggle("sx-v5-dirty-save",!!s.dirty);
    if(top && s.dirty)top.textContent=count?"Enregistrer · "+count:"Enregistrer";
    else if(top)top.textContent="Enregistrer";
    if(status && s.dirty && !/enregistrement/i.test(status.textContent||""))status.textContent=count?count+" modification"+(count>1?"s":"")+" non enregistrée"+(count>1?"s":""):"Modifications non enregistrées";
  }

  function decorate(){
    ensureSidebarSearch();ensurePalette();ensureTopAction();
    const s=getState();
    if(!s?.guildData)return;
    enhanceOverview();enhancePageStatus();decorateFields();enhanceWelcomePreview();updateDirtyUI();
  }

  document.addEventListener("input",event=>{
    const control=event.target?.closest?.("#fields [data-key]");
    if(!control)return;
    dirtyKeys.add(control.dataset.key);control.closest(".field,.switch")?.classList.add("sx-v5-dirty");
    updateWelcomePreview();setTimeout(updateDirtyUI,0);
  },true);
  document.addEventListener("change",event=>{
    const control=event.target?.closest?.("#fields [data-key]");
    if(control){dirtyKeys.add(control.dataset.key);scheduleDecorate(20);}
  },true);
  document.addEventListener("submit",event=>{
    if(event.target?.id!=="settingsForm")return;
    setTimeout(()=>{if(!getState()?.dirty){dirtyKeys.clear();scheduleDecorate(20);}},900);
  },true);
  document.addEventListener("click",event=>{
    if(event.target?.closest?.("#navigation button[data-tab]")){dirtyKeys.clear();scheduleDecorate(35);}
  },true);
  document.addEventListener("keydown",event=>{
    const target=event.target;
    const typing=target instanceof HTMLInputElement||target instanceof HTMLTextAreaElement||target instanceof HTMLSelectElement||target?.isContentEditable;
    if((event.metaKey||event.ctrlKey)&&event.key.toLocaleLowerCase()==="k"){event.preventDefault();openPalette();return;}
    if((event.metaKey||event.ctrlKey)&&event.key.toLocaleLowerCase()==="s"&&getState()?.user){event.preventDefault();document.getElementById("settingsForm")?.requestSubmit();return;}
    if(event.key==="/"&&!typing&&!event.metaKey&&!event.ctrlKey&&!event.altKey){const input=document.getElementById("sxV5NavSearchInput");if(input){event.preventDefault();input.focus();}}
    if(event.key==="Escape")closePalette();
  },true);

  const observer=new MutationObserver(mutations=>{
    let relevant=false;
    for(const mutation of mutations){
      if([...mutation.addedNodes].some(node=>node.nodeType===1&&(node.id==="fields"||node.id==="serverContent"||node.querySelector?.("#fields,.sx-overview,.field,.switch")))){relevant=true;break;}
    }
    if(relevant)scheduleDecorate(20);
  });

  function start(){
    if(document.body)observer.observe(document.body,{childList:true,subtree:true});
    [0,120,450,1000,2200].forEach(delay=>setTimeout(decorate,delay));
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
</script>
"""


def apply_major_v5(html: str) -> str:
    """Inject V5 after the stable page router without touching backend handlers."""
    if not isinstance(html, str):
        return html
    if 'id="sentrix-dashboard-v5-css"' not in html:
        html = html.replace("</head>", MAJOR_V5_CSS + "\n</head>", 1)
    if 'id="sentrix-dashboard-v5-js"' not in html:
        html = html.replace("</body>", MAJOR_V5_JS + "\n</body>", 1)
    return html


__all__ = ["apply_major_v5"]
