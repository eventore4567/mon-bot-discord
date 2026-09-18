"""Final presentation authority for the SentriX dashboard.

V23 is intentionally presentation-only. It runs after the canonical V18/V19 product UI and
Growth V12 surfaces, then normalizes responsive behavior, focus/touch affordances, navigation
busy state, route announcements and network state without adding data, routes or polling.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-visual-finish-v23")

STYLE_MARKER = "sentrix-dashboard-visual-finish-v23"
JS_MARKER = "__sentrixDashboardVisualFinishV23"

STYLE = f'''<style id="{STYLE_MARKER}">
:root{{--sx23-focus:#78b9ed;--sx23-line:#334354;--sx23-surface:#121820;--sx23-radius:14px}}
html{{scrollbar-gutter:stable;color-scheme:dark;scroll-behavior:smooth}}
body{{text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased}}
::selection{{background:rgba(77,163,255,.28);color:#fff}}
*{{scrollbar-width:thin;scrollbar-color:#3d5267 #0d1218}}
*::-webkit-scrollbar{{width:9px;height:9px}}*::-webkit-scrollbar-track{{background:#0d1218}}*::-webkit-scrollbar-thumb{{background:#3d5267;border:2px solid #0d1218;border-radius:999px}}
.workspace,#content{{min-width:0}}#content{{isolation:isolate}}
:where(.card,.p18-card,.sx12-card,.metric,.p18-kpi,.sx12-kpi){{contain:paint}}
:where(.card,.p18-card,.sx12-card) :where(h1,h2,h3,p,small,strong,span){{overflow-wrap:anywhere}}
:where(button,.btn,.p18-tab,.palette-item,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]){{touch-action:manipulation;-webkit-tap-highlight-color:transparent}}
:where(button,.btn,.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(.sx12-switch){{min-height:38px}}
:where(button,.btn,.p18-tab,.palette-item,.guild-btn,.nav button,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page],a):focus-visible{{outline:2px solid var(--sx23-focus)!important;outline-offset:2px;box-shadow:0 0 0 4px rgba(120,185,237,.14)}}
:where(input,select,textarea):focus-visible{{outline:0;border-color:#5796c9!important;box-shadow:0 0 0 3px rgba(87,150,201,.16)!important}}
:where(.p18-table,.sx12-table){{font-variant-numeric:tabular-nums}}
:where(.p18-card,.sx12-table-wrap){{overscroll-behavior-inline:contain}}
.sx23-sr{{position:fixed!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}}
body.sx23-offline #runtimeText{{color:#efc47a}}
body.sx23-offline #runtimeDot{{filter:saturate(.55)}}
#content[aria-busy="true"]{{cursor:progress}}
#content[aria-busy="true"] :where(button,.btn,[role="button"]){{pointer-events:none}}
@media(hover:hover) and (pointer:fine){{
  :where(.card,.p18-card,.sx12-card,.metric,.p18-kpi,.sx12-kpi):hover{{transform:translateY(-1px)}}
}}
@media(max-width:760px){{
  html{{scrollbar-gutter:auto}}
  .workspace{{padding-left:14px!important;padding-right:14px!important}}
  :where(.metrics,.p18-kpis,.sx12-kpis){{grid-template-columns:repeat(2,minmax(0,1fr))!important}}
  :where(.sx12-invite-grid,.sx12-webhook-grid,.sx12-flow-grid){{grid-template-columns:1fr!important}}
  .sx12-flow-steps{{grid-template-columns:1fr!important;gap:7px!important}}
  .sx12-flow-arrow{{transform:rotate(90deg);justify-self:center}}
  .sx12-section-head{{align-items:stretch;flex-direction:column}}
  .sx12-section-head>.btn{{align-self:flex-start}}
}}
@media(max-width:520px){{
  .workspace{{padding:16px 10px 70px!important}}
  :where(.metrics,.p18-kpis,.sx12-kpis){{grid-template-columns:1fr!important}}
  :where(.card,.p18-card,.sx12-card){{border-radius:12px!important}}
  .sx12-hero{{padding:17px 15px!important;border-radius:14px!important}}
  .sx12-hero h1{{font-size:24px!important}}
  .sx12-invite-meta{{grid-template-columns:1fr!important}}
  .sx12-bar-row{{grid-template-columns:88px minmax(0,1fr) 42px!important}}
  .sx12-staff-line{{grid-template-columns:minmax(74px,1fr) 1.4fr 36px!important}}
  .p18-table,.sx12-table{{min-width:520px!important}}
  :where(button,.btn,.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(.sx12-switch){{min-height:42px}}
}}
@media(prefers-contrast:more){{
  :where(.card,.p18-card,.sx12-card,.metric,.p18-kpi,.sx12-kpi,.sx12-item){{border-color:#53687d!important}}
  :where(.badge,.sx12-badge){{border-width:2px}}
}}
@media(prefers-reduced-motion:reduce){{
  html{{scroll-behavior:auto}}
  *,*::before,*::after{{scroll-behavior:auto!important;animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important}}
}}
@media(forced-colors:active){{
  *{{scrollbar-color:auto}}
  :where(.card,.p18-card,.sx12-card,.metric,.p18-kpi,.sx12-kpi,.sx12-item){{border:1px solid CanvasText!important}}
  :where(button,.btn,.p18-tab,.palette-item,.guild-btn,.nav button,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page],a):focus-visible{{outline:2px solid Highlight!important;box-shadow:none!important}}
}}
</style>'''

SCRIPT = r'''<script id="sentrix-dashboard-visual-finish-v23-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardVisualFinishV23) return;
  window.__sentrixDashboardVisualFinishV23 = true;

  const content = document.getElementById("content");
  const announcer = document.createElement("div");
  announcer.id = "sx23RouteStatus";
  announcer.className = "sx23-sr";
  announcer.setAttribute("role", "status");
  announcer.setAttribute("aria-live", "polite");
  announcer.setAttribute("aria-atomic", "true");
  document.body.appendChild(announcer);

  let settleTimer = null;
  let lastHeading = "";
  const currentHeading = () => content?.querySelector("h1,h2")?.textContent?.trim() || "Dashboard";
  const syncCurrent = () => {
    document.querySelectorAll(".nav button,[data-sx12-tab],[data-p18-tab],[data-page]").forEach(node => {
      const active = node.classList.contains("active") || node.getAttribute("aria-selected") === "true";
      if (active) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
  };
  const settle = () => {
    if (content) content.setAttribute("aria-busy", "false");
    syncCurrent();
    const heading = currentHeading();
    if (heading && heading !== lastHeading) {
      lastHeading = heading;
      announcer.textContent = `${heading} chargé`;
      if (!document.title.toLocaleLowerCase("fr").includes(heading.toLocaleLowerCase("fr"))) {
        document.title = `${heading} · SentriX`;
      }
    }
  };
  const queueSettle = () => {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(settle, 90);
  };
  const beginNavigation = () => {
    // A click is not a loading state by itself. The actual request HUD owns
    // loading feedback; marking #content busy here made V25/V26 dim/blur the
    // whole dashboard for every navigation, even when the page rendered in ms.
    clearTimeout(settleTimer);
    settleTimer = setTimeout(settle, 1400);
  };

  if (content) {
    content.setAttribute("aria-busy", "false");
    new MutationObserver(queueSettle).observe(content, {childList:true, subtree:true});
  }

  document.addEventListener("click", event => {
    const target = event.target.closest(".nav button,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page],.palette-item,[data-guild]");
    if (!target) return;
    beginNavigation();
    queueMicrotask(syncCurrent);
  }, true);

  const syncNetwork = () => {
    const offline = !navigator.onLine;
    document.body.classList.toggle("sx23-offline", offline);
    if (offline) announcer.textContent = "Connexion réseau perdue";
    else if (document.body.dataset.sx23NetworkSeen === "1") announcer.textContent = "Connexion réseau rétablie";
    document.body.dataset.sx23NetworkSeen = "1";
  };
  window.addEventListener("online", () => { syncNetwork(); queueSettle(); });
  window.addEventListener("offline", syncNetwork);
  window.addEventListener("pageshow", () => { syncNetwork(); queueSettle(); });
  document.addEventListener("sentrix:live", queueSettle);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) queueSettle(); });

  syncNetwork();
  queueSettle();
})();
</script>'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if STYLE_MARKER not in html and "</head>" in html:
        html = html.replace("</head>", STYLE + "\n</head>", 1)
    if "sentrix-dashboard-visual-finish-v23-js" not in html and "</body>" in html:
        html = html.replace("</body>", SCRIPT + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    ok = STYLE_MARKER in html and JS_MARKER in html
    logger.info("Dashboard Visual Finish V23 installed=%s.", ok)
    return ok


__all__ = ["install", "STYLE_MARKER", "JS_MARKER", "STYLE", "SCRIPT"]
