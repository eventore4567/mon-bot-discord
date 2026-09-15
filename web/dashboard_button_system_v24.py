"""SentriX Dashboard V24 — semantic button system.

Presentation-only final layer for buttons across the real dashboard surfaces. V24 gives every
interactive button a consistent visual language by intent (primary, secondary, success,
warning, danger, ghost) and normalizes hover, pressed, focus, disabled, busy, touch and
high-contrast states. It does not add routes, data or business behavior.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-button-system-v24")

STYLE_MARKER = "sentrix-dashboard-button-system-v24"
JS_MARKER = "__sentrixDashboardButtonSystemV24"

STYLE = f'''<style id="{STYLE_MARKER}">
:root{{
  --sx24-blue:#2563eb;--sx24-blue-hover:#3b82f6;--sx24-blue-active:#1d4ed8;--sx24-blue-line:#60a5fa;
  --sx24-secondary:#18212b;--sx24-secondary-hover:#202c38;--sx24-secondary-active:#111923;--sx24-secondary-line:#344152;
  --sx24-success:#22c55e;--sx24-success-bg:#12351f;--sx24-success-hover:#174729;--sx24-success-line:#2f8a51;
  --sx24-warning:#f59e0b;--sx24-warning-bg:#2d210d;--sx24-warning-hover:#3a2a0e;--sx24-warning-line:#76591c;
  --sx24-danger:#ef4444;--sx24-danger-bg:#261316;--sx24-danger-hover:#39191e;--sx24-danger-active:#4a1c23;--sx24-danger-line:#6d3039;
  --sx24-ghost-hover:#18212b;--sx24-focus:#78b9ed;--sx24-radius:10px;--sx24-fast:150ms;
}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]){{
  appearance:none;display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:40px;padding:9px 13px;
  border:1px solid var(--sx24-secondary-line);border-radius:var(--sx24-radius);background:linear-gradient(180deg,#1b2631,var(--sx24-secondary));
  color:#d9e2ec;font:inherit;font-size:11px;font-weight:800;line-height:1;letter-spacing:.005em;text-decoration:none;white-space:nowrap;
  cursor:pointer;user-select:none;box-shadow:inset 0 1px rgba(255,255,255,.035),0 4px 12px rgba(0,0,0,.08);
  transition:background var(--sx24-fast) ease,border-color var(--sx24-fast) ease,color var(--sx24-fast) ease,
             box-shadow var(--sx24-fast) ease,transform 90ms ease,opacity var(--sx24-fast) ease;
}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):focus-visible{{
  outline:2px solid var(--sx24-focus)!important;outline-offset:2px;box-shadow:0 0 0 4px rgba(120,185,237,.16),0 7px 18px rgba(0,0,0,.16)!important;
}}
[data-sx24-intent="primary"],.btn.primary{{
  background:linear-gradient(180deg,var(--sx24-blue-hover),var(--sx24-blue));border-color:#4d91f0;color:#fff;
  box-shadow:inset 0 1px rgba(255,255,255,.18),0 6px 18px rgba(37,99,235,.22);
}}
[data-sx24-intent="success"]{{background:linear-gradient(180deg,#174529,var(--sx24-success-bg));border-color:var(--sx24-success-line);color:#9af0b8;box-shadow:inset 0 1px rgba(255,255,255,.04),0 5px 16px rgba(34,197,94,.09)}}
[data-sx24-intent="warning"]{{background:linear-gradient(180deg,#35270f,var(--sx24-warning-bg));border-color:var(--sx24-warning-line);color:#ffd37a;box-shadow:inset 0 1px rgba(255,255,255,.035)}}
[data-sx24-intent="danger"],.btn.danger{{background:linear-gradient(180deg,#2c171b,var(--sx24-danger-bg));border-color:var(--sx24-danger-line);color:#ff9aa7;box-shadow:inset 0 1px rgba(255,255,255,.025)}}
[data-sx24-intent="ghost"]{{background:transparent;border-color:transparent;color:#9eabba;box-shadow:none}}
[data-sx24-intent="icon"]{{min-width:28px;min-height:28px;padding:4px;border-color:transparent;background:transparent;color:#8595a7;box-shadow:none;border-radius:8px}}
[data-sx24-intent="server"]{{box-shadow:0 0 0 1px rgba(255,255,255,.02);transition:transform var(--sx24-fast),border-color var(--sx24-fast),box-shadow var(--sx24-fast),background var(--sx24-fast)}}
.sx12-switch{{transition:background var(--sx24-fast),border-color var(--sx24-fast),box-shadow var(--sx24-fast)!important}}
.sx12-switch:focus-visible{{outline:2px solid var(--sx24-focus)!important;outline-offset:3px;box-shadow:0 0 0 4px rgba(120,185,237,.14)!important}}
.sx12-switch:checked{{background:#1f6f43!important;border-color:#3aa765!important;box-shadow:0 0 0 3px rgba(34,197,94,.08)!important}}
:where(.p18-tab,[data-sx12-tab],[data-p18-tab])[aria-current="page"],:where(.p18-tab,[data-sx12-tab],[data-p18-tab]).active{{
  background:#183a59!important;border-color:#3c77aa!important;color:#d9efff!important;box-shadow:inset 0 0 0 1px rgba(96,165,250,.13),0 4px 14px rgba(0,0,0,.12)!important;
}}
:where(.nav button)[aria-current="page"],:where(.nav button).active{{background:linear-gradient(90deg,rgba(37,99,235,.18),rgba(37,99,235,.04));color:#d9efff}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):disabled,
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page])[aria-disabled="true"]{{opacity:.42;cursor:not-allowed;filter:saturate(.55);transform:none!important;box-shadow:none!important}}
:where(.btn,button[data-sx24-intent])[aria-busy="true"]{{position:relative;color:transparent!important;pointer-events:none}}
:where(.btn,button[data-sx24-intent])[aria-busy="true"]:after{{content:"";position:absolute;width:14px;height:14px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;color:#fff;animation:sx24-spin .65s linear infinite}}
@keyframes sx24-spin{{to{{transform:rotate(360deg)}}}}
@media(hover:hover) and (pointer:fine){{
  :where(.btn,button[data-sx24-intent="secondary"]):not(:disabled):hover{{background:linear-gradient(180deg,#24313f,var(--sx24-secondary-hover));border-color:#46596c;color:#fff;box-shadow:inset 0 1px rgba(255,255,255,.05),0 7px 18px rgba(0,0,0,.14)}}
  [data-sx24-intent="primary"]:not(:disabled):hover,.btn.primary:not(:disabled):hover{{background:linear-gradient(180deg,#60a5fa,var(--sx24-blue-hover));border-color:#7ab7f4;box-shadow:inset 0 1px rgba(255,255,255,.22),0 9px 24px rgba(37,99,235,.29)}}
  [data-sx24-intent="success"]:not(:disabled):hover{{background:linear-gradient(180deg,#1d5b35,var(--sx24-success-hover));border-color:#43a769;color:#b9f6cd}}
  [data-sx24-intent="warning"]:not(:disabled):hover{{background:linear-gradient(180deg,#493512,var(--sx24-warning-hover));border-color:#9a7424;color:#ffe1a1}}
  [data-sx24-intent="danger"]:not(:disabled):hover,.btn.danger:not(:disabled):hover{{background:linear-gradient(180deg,#522029,var(--sx24-danger-hover));border-color:#a94352;color:#ffd1d7;box-shadow:0 8px 20px rgba(239,68,68,.10)}}
  [data-sx24-intent="ghost"]:not(:disabled):hover{{background:var(--sx24-ghost-hover);border-color:#2d3b49;color:#dbe8f5}}
  [data-sx24-intent="icon"]:not(:disabled):hover{{background:#1a2530;border-color:#304153;color:#d9e8f6}}
  [data-sx24-intent="server"]:hover{{transform:translateY(-1px);border-color:#4b6883;box-shadow:0 7px 18px rgba(0,0,0,.18)}}
}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(:disabled):active{{transform:translateY(1px) scale(.985);box-shadow:inset 0 2px 5px rgba(0,0,0,.2)}}
[data-sx24-intent="primary"]:not(:disabled):active,.btn.primary:not(:disabled):active{{background:var(--sx24-blue-active)}}
[data-sx24-intent="danger"]:not(:disabled):active,.btn.danger:not(:disabled):active{{background:var(--sx24-danger-active)}}
@media(max-width:520px){{
  :where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(.sx12-switch){{min-height:44px;padding:10px 14px}}
  :where(.p18-actions,.sx12-actions)>.btn{{flex:1 1 auto}}
}}
@media(prefers-reduced-motion:reduce){{
  :where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page],.sx12-switch){{transition:none!important}}
  :where(.btn,button[data-sx24-intent])[aria-busy="true"]:after{{animation:none!important;border-right-color:currentColor}}
}}
@media(forced-colors:active){{
  :where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]){{background:ButtonFace!important;color:ButtonText!important;border:1px solid ButtonText!important;box-shadow:none!important}}
  :where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):focus-visible{{outline:2px solid Highlight!important;box-shadow:none!important}}
}}
</style>'''

SCRIPT = r'''<script id="sentrix-dashboard-button-system-v24-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardButtonSystemV24) return;
  window.__sentrixDashboardButtonSystemV24 = true;

  const danger = ["supprimer","delete","remove","ban","kick","révoquer","revoke","wipe","purge","effacer","retirer accès","reset"];
  const warning = ["timeout","mute","désactiver","disable","suspendre","pause","stop"];
  const success = ["activer","enable","confirmer","confirm","valider","validate","approuver","approve"];
  const primary = ["créer","create","enregistrer","save","appliquer","apply","réparer","repair","rechercher","search","ajouter","add","connecter","connect","continuer","continue","envoyer","send"];
  const ghost = ["annuler","cancel","fermer","close","retour","back"];

  const tokenText = node => {
    const dataset = Object.keys(node.dataset || {}).join(" ");
    return `${node.id || ""} ${node.className || ""} ${node.getAttribute("aria-label") || ""} ${dataset} ${node.textContent || ""}`.toLocaleLowerCase("fr");
  };
  const includesAny = (value, words) => words.some(word => value.includes(word));
  const classify = node => {
    if (!(node instanceof HTMLElement)) return;
    if (node.matches(".sx12-switch")) return;
    if (node.matches(".sx12-emoji-chip button")) { node.dataset.sx24Intent = "icon"; return; }
    if (node.matches(".guild-btn")) { node.dataset.sx24Intent = "server"; return; }
    if (!node.matches("button,.btn,[role='button']")) return;
    if (node.matches(".p18-tab,.nav button,.palette-item,[data-sx12-tab],[data-p18-tab],[data-page]")) { node.dataset.sx24Intent = "ghost"; return; }
    const value = tokenText(node);
    if (node.classList.contains("danger") || includesAny(value, danger)) node.dataset.sx24Intent = "danger";
    else if (includesAny(value, warning)) node.dataset.sx24Intent = "warning";
    else if (includesAny(value, success)) node.dataset.sx24Intent = "success";
    else if (node.classList.contains("primary") || includesAny(value, primary)) node.dataset.sx24Intent = "primary";
    else if (includesAny(value, ghost)) node.dataset.sx24Intent = "ghost";
    else node.dataset.sx24Intent = "secondary";
  };
  const decorate = root => {
    if (root instanceof HTMLElement && root.matches("button,.btn,[role='button']")) classify(root);
    root.querySelectorAll?.("button,.btn,[role='button']").forEach(classify);
  };

  decorate(document);
  new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(node => {
      if (node instanceof HTMLElement) decorate(node);
    }));
  }).observe(document.body, {childList:true,subtree:true});

  document.addEventListener("sentrix:live", () => decorate(document));
  window.addEventListener("pageshow", () => decorate(document));
})();
</script>'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if STYLE_MARKER not in html and "</head>" in html:
        html = html.replace("</head>", STYLE + "\n</head>", 1)
    if "sentrix-dashboard-button-system-v24-js" not in html and "</body>" in html:
        html = html.replace("</body>", SCRIPT + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    ok = STYLE_MARKER in html and JS_MARKER in html
    logger.info("Dashboard Button System V24 installed=%s.", ok)
    return ok


__all__ = ["install", "STYLE_MARKER", "JS_MARKER", "STYLE", "SCRIPT"]
