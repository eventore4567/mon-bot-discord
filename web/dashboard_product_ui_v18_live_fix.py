"""V18 live-bundle anchor repair + final product polish.

Production V15 expands the native Administration navigation and render switch before V18 sees
the response. The first V18 implementation used exact pre-V15 strings, so its backend loaded
but its UI correctly failed open to V16. This repair keeps the existing V18 UI/body, makes the
insertion points tolerant of the live V15/V16 bundle, and applies the final lightweight V19 UX
polish without introducing another dashboard patch module.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-product-ui-v18-live-fix")
MARKER = "sentrix-dashboard-product-ui-v18-live-fix"
POLISH_MARKER = "sentrix-dashboard-v19-polish"
POLISH_JS_MARKER = "__sentrixDashboardV19Polish"

_POLISH_STYLE = f'''<style id="{POLISH_MARKER}">
:root{{--sx19-fast:160ms;--sx19-soft:220ms;--sx19-radius:14px;--sx19-elev:0 12px 32px rgba(0,0,0,.16)}}
.workspace{{padding-top:28px}}#content{{animation:sx19-enter var(--sx19-fast) ease both}}
@keyframes sx19-enter{{from{{opacity:.55;transform:translateY(3px)}}to{{opacity:1;transform:none}}}}
.card,.p18-card,.metric,.row{{transition:border-color var(--sx19-fast) ease,background var(--sx19-fast) ease,box-shadow var(--sx19-fast) ease,transform var(--sx19-fast) ease}}
.card,.p18-card{{border-radius:var(--sx19-radius);background:linear-gradient(180deg,rgba(25,30,37,.96),rgba(19,23,29,.98));box-shadow:0 1px 0 rgba(255,255,255,.018)}}
.card:hover,.p18-card:hover{{border-color:#394552;box-shadow:var(--sx19-elev)}}
.card h2,.card h3,.p18-card h3{{letter-spacing:-.025em}}.card h3,.p18-card h3{{font-size:15px}}
.card>p,.card-copy,.p18-card>p{{font-size:11px;line-height:1.6;color:#98a4b3}}
.metrics,.p18-kpis{{gap:11px}}.metric,.p18-kpi{{border-radius:11px;background:linear-gradient(180deg,#151a21,#12171d);padding:13px 14px}}
.metric strong,.p18-kpi strong{{font-variant-numeric:tabular-nums;letter-spacing:-.03em}}.p18-kpi strong{{font-size:24px}}
.p18-tabs{{position:sticky;top:8px;z-index:34;padding:6px;border-radius:12px;background:rgba(15,19,24,.88);backdrop-filter:blur(16px);box-shadow:0 8px 26px rgba(0,0,0,.18)}}
.p18-tab{{min-height:34px;padding:8px 12px;transition:background var(--sx19-fast),color var(--sx19-fast),box-shadow var(--sx19-fast)}}
.p18-tab.active{{background:#1b344b;box-shadow:inset 0 0 0 1px #3e75a5,0 4px 12px rgba(0,0,0,.16)}}
.p18-table{{border-spacing:0}}.p18-table th{{position:sticky;top:0;background:#151a20;z-index:1;letter-spacing:.04em}}
.p18-table tbody tr:hover td{{background:#171d24}}.p18-table td{{font-size:11px}}
.p18-search input,.field input,.field select,.field textarea{{transition:border-color var(--sx19-fast),box-shadow var(--sx19-fast),background var(--sx19-fast)}}
.btn{{transition:transform var(--sx19-fast) ease,border-color var(--sx19-fast) ease,background var(--sx19-fast) ease,opacity var(--sx19-fast) ease}}
.btn:not(:disabled):active{{transform:translateY(1px) scale(.99)}}
.badge{{letter-spacing:.025em}}.row:hover{{border-color:#384451;background:#141a21}}.row-actions{{align-items:center}}
.sx19-command-hint{{position:fixed;right:18px;bottom:18px;z-index:82;min-height:34px;padding:0 11px;border:1px solid #354250;border-radius:9px;background:rgba(17,22,28,.92);backdrop-filter:blur(12px);color:#aeb9c6;font-size:10px;font-weight:850;cursor:pointer;box-shadow:0 10px 30px rgba(0,0,0,.24)}}
.sx19-command-hint:hover{{border-color:#4b6f90;color:#eef5fb}}
.sx19-command-overlay{{position:fixed;inset:0;z-index:140;background:rgba(3,6,9,.68);backdrop-filter:blur(5px);display:grid;place-items:start center;padding:clamp(76px,12vh,132px) 16px 24px}}
.sx19-command-overlay[hidden]{{display:none}}
.sx19-command{{width:min(680px,100%);border:1px solid #394757;border-radius:15px;background:#11161c;box-shadow:0 30px 90px rgba(0,0,0,.52);overflow:hidden}}
.sx19-command-head{{display:flex;align-items:center;gap:10px;padding:12px;border-bottom:1px solid var(--line)}}
.sx19-command-head input{{flex:1;height:42px;border:0;background:transparent;color:var(--text);outline:0;font-size:14px}}
.sx19-command-head kbd{{border:1px solid var(--line2);border-radius:6px;padding:3px 7px;color:var(--muted);font-size:9px;background:#191f26}}
.sx19-command-list{{max-height:min(52vh,430px);overflow:auto;padding:7px}}
.sx19-command-item{{width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--text);padding:10px 11px;text-align:left;cursor:pointer}}
.sx19-command-item:hover,.sx19-command-item.active{{background:#17222d;border-color:#2f5778}}
.sx19-command-item b{{display:block;font-size:12px}}.sx19-command-item span{{display:block;color:var(--muted);font-size:10px;margin-top:2px}}
.sx19-command-item small{{color:#718092;font-size:9px}}
.sx19-loading-bar{{position:fixed;left:0;top:0;height:2px;width:100%;z-index:200;pointer-events:none;overflow:hidden;opacity:0;transition:opacity .12s}}
.sx19-loading-bar.active{{opacity:1}}.sx19-loading-bar:before{{content:"";display:block;width:34%;height:100%;background:var(--blue);animation:sx19-load .75s ease-in-out infinite}}
@keyframes sx19-load{{from{{transform:translateX(-110%)}}to{{transform:translateX(330%)}}}}
@media(max-width:900px){{.workspace{{padding-left:18px;padding-right:18px}}.sx19-command-hint{{right:12px;bottom:12px}}}}
@media(max-width:620px){{.workspace{{padding:20px 13px 72px}}.card,.p18-card{{padding:14px}}.p18-tabs{{top:4px;overflow-x:auto;flex-wrap:nowrap}}.p18-tab{{white-space:nowrap}}.sx19-command-hint{{display:none}}}}
@media(prefers-reduced-motion:reduce){{#content,.card,.p18-card,.metric,.row,.btn,.p18-tab{{animation:none!important;transition:none!important}}}}
</style>'''

_POLISH_JS = r'''<script id="sentrix-dashboard-v19-polish-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardV19Polish) return;
  window.__sentrixDashboardV19Polish = true;

  const COMMANDS = [
    ["overview","Vue d’ensemble","État du serveur, métriques et raccourcis"],
    ["moderation","Modération","Sanctions et outils staff"],
    ["tickets","Tickets","Support, panneaux et configuration"],
    ["logs","Logs","Journalisation du serveur"],
    ["security","Sécurité","Anti-spam, anti-raid et protections"],
    ["verification","Vérification Discord","Règlement, rôle et CAPTCHA"],
    ["roles","Rôles","Attribution et gestion des rôles"],
    ["economy","Économie","Monnaie, banque et boutique"],
    ["levels","Niveaux","XP, progression et récompenses"],
    ["notifications","Notifications","Réseaux et notifications serveur"],
    ["autoreact","Réactions automatiques","Réactions configurables"],
    ["giveaway","Giveaway","Création et gestion des giveaways"],
    ["embeds","Embeds & design","Créateur d’embeds"],
    ["ai","Intelligence artificielle","Réglages IA SentriX"],
    ["diagnostic","Diagnostic","Permissions et ressources cassées"],
    ["product","Centre avancé","Membres, automations, audit, templates et accès"],
    ["configuration","Configuration","Réglages généraux du serveur"]
  ];

  let overlay = null, input = null, list = null, current = [], selected = 0;
  const escHtml = value => String(value ?? "").replace(/[&<>\"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));

  function navigate(id) {
    closePalette();
    try {
      if (typeof window.go === "function") return window.go(id);
      if (typeof go === "function") return go(id);
    } catch (_) {}
    const button = document.querySelector(`[data-page="${CSS.escape(id)}"],[data-nav="${CSS.escape(id)}"],[data-v17-go="${CSS.escape(id)}"]`);
    if (button) button.click();
  }

  function ensurePalette() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.className = "sx19-command-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `<div class="sx19-command" role="dialog" aria-modal="true" aria-label="Recherche rapide SentriX"><div class="sx19-command-head"><input aria-label="Rechercher une page" placeholder="Rechercher une fonction…" autocomplete="off"><kbd>ESC</kbd></div><div class="sx19-command-list" role="listbox"></div></div>`;
    document.body.appendChild(overlay);
    input = overlay.querySelector("input");
    list = overlay.querySelector(".sx19-command-list");
    input.addEventListener("input", () => { selected = 0; renderPalette(); });
    input.addEventListener("keydown", event => {
      if (event.key === "ArrowDown") { event.preventDefault(); selected = Math.min(selected + 1, Math.max(0, current.length - 1)); renderPalette(); }
      else if (event.key === "ArrowUp") { event.preventDefault(); selected = Math.max(0, selected - 1); renderPalette(); }
      else if (event.key === "Enter" && current[selected]) { event.preventDefault(); navigate(current[selected][0]); }
      else if (event.key === "Escape") { event.preventDefault(); closePalette(); }
    });
    overlay.addEventListener("mousedown", event => { if (event.target === overlay) closePalette(); });
  }

  function renderPalette() {
    if (!list) return;
    const query = (input?.value || "").trim().toLocaleLowerCase("fr");
    current = COMMANDS.filter(item => !query || `${item[1]} ${item[2]}`.toLocaleLowerCase("fr").includes(query)).slice(0, 12);
    if (!current.length) {
      list.innerHTML = '<div class="empty" style="margin:8px">Aucune fonction trouvée.</div>';
      return;
    }
    if (selected >= current.length) selected = current.length - 1;
    list.innerHTML = current.map((item, index) => `<button type="button" class="sx19-command-item ${index === selected ? "active" : ""}" data-sx19-command="${escHtml(item[0])}" role="option" aria-selected="${index === selected}"><span><b>${escHtml(item[1])}</b><span>${escHtml(item[2])}</span></span><small>Ouvrir</small></button>`).join("");
    list.querySelectorAll("[data-sx19-command]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.sx19Command)));
    list.querySelector(".active")?.scrollIntoView({block:"nearest"});
  }

  function openPalette() {
    ensurePalette();
    overlay.hidden = false;
    input.value = "";
    selected = 0;
    renderPalette();
    requestAnimationFrame(() => input.focus());
  }

  function closePalette() {
    if (!overlay) return;
    overlay.hidden = true;
  }

  const hint = document.createElement("button");
  hint.type = "button";
  hint.className = "sx19-command-hint";
  hint.textContent = navigator.platform?.toLowerCase().includes("mac") ? "⌘ K  Recherche" : "Ctrl K  Recherche";
  hint.setAttribute("aria-label", "Ouvrir la recherche rapide SentriX");
  hint.addEventListener("click", openPalette);
  document.body.appendChild(hint);

  const loadBar = document.createElement("div");
  loadBar.className = "sx19-loading-bar";
  document.body.appendChild(loadBar);
  let loadTimer = null;
  document.addEventListener("click", event => {
    const target = event.target.closest(".nav button,[data-p18-tab],[data-p18-go],[data-page]");
    if (!target) return;
    loadBar.classList.add("active");
    clearTimeout(loadTimer);
    loadTimer = setTimeout(() => loadBar.classList.remove("active"), 900);
  }, true);

  document.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openPalette();
    } else if (event.key === "Escape" && overlay && !overlay.hidden) {
      closePalette();
    }
  });
})();
</script>'''


def _inject_polish(source: str) -> str:
    text = str(source or "")
    if POLISH_MARKER not in text and "</head>" in text:
        text = text.replace("</head>", _POLISH_STYLE + "\n</head>", 1)
    if "sentrix-dashboard-v19-polish-js" not in text and "</body>" in text:
        text = text.replace("</body>", _POLISH_JS + "\n</body>", 1)
    return text


def patch_html(html: str) -> str:
    from web import dashboard_product_ui_v18 as v18

    source = str(html or "")
    # Let the original implementation handle native/pre-V15 HTML when it can.
    patched = v18._ORIGINAL_PATCH_HTML_V18(source) if hasattr(v18, "_ORIGINAL_PATCH_HTML_V18") else source
    if v18.JS_MARKER in patched and v18.MARKER in patched and '["product","Centre avancé","PX"]' in patched:
        return _inject_polish(patched)

    source = patched
    tag = '<script id="sentrix-dashboard-unified-v2">'
    start = source.find(tag)
    if start < 0:
        return _inject_polish(source)
    body_start = start + len(tag)
    end = source.find("</script>", body_start)
    if end < 0:
        return _inject_polish(source)
    body = source[body_start:end]

    # V15 keeps the Diagnostic token but appends several technical entries after it.
    # Insert Product beside Diagnostic without assuming what comes after it.
    product_nav = '["product","Centre avancé","PX"]'
    diagnostic_nav = '["diagnostic","Diagnostic","DG"]'
    if product_nav not in body:
        if diagnostic_nav not in body:
            return _inject_polish(source)
        body = body.replace(diagnostic_nav, diagnostic_nav + ',' + product_nav, 1)

    meta_anchor = 'diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],'
    product_meta = 'product:["Centre avancé","Actions staff, automations, membres, audit, templates et accès dashboard."],'
    if product_meta not in body:
        if meta_anchor not in body:
            return _inject_polish(source)
        body = body.replace(meta_anchor, meta_anchor + product_meta, 1)

    render_anchor = 'async function render(force=false)'
    if v18.JS_MARKER not in body:
        if render_anchor not in body:
            return _inject_polish(source)
        body = body.replace(
            render_anchor,
            f'window.{v18.JS_MARKER}=true;\n' + v18._NATIVE_JS + '\n' + render_anchor,
            1,
        )

    # V15 inserts its own cases between Diagnostic and default. Anchor on default itself.
    product_case = "case'product':await renderProductV18();break;"
    default_case = "default:await renderOverview()"
    if product_case not in body:
        if default_case not in body:
            return _inject_polish(source)
        body = body.replace(default_case, product_case + default_case, 1)

    source = source[:body_start] + body + source[end:]
    if v18.MARKER not in source and "</head>" in source:
        source = source.replace("</head>", v18._STYLE + "\n</head>", 1)
    if 'name="sentrix-dashboard-product-build"' not in source and "</head>" in source:
        source = source.replace(
            "</head>",
            f'<meta name="sentrix-dashboard-product-build" content="{v18.BUILD}">\n</head>',
            1,
        )
    if MARKER not in source and "</head>" in source:
        source = source.replace("</head>", f'<meta name="{MARKER}" content="1">\n</head>', 1)
    return _inject_polish(source)


def install(dashboard) -> bool:
    from web import dashboard_product_ui_v18 as v18

    if not hasattr(v18, "_ORIGINAL_PATCH_HTML_V18"):
        v18._ORIGINAL_PATCH_HTML_V18 = v18.patch_html
    v18.patch_html = patch_html

    # V18's request-time wrapper resolves its module-global patch_html at call time, so
    # replacing that function repairs both the current startup snapshot and future /app bytes.
    dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
    ok = (
        v18.JS_MARKER in dashboard.INDEX_HTML
        and v18.MARKER in dashboard.INDEX_HTML
        and '["product","Centre avancé","PX"]' in dashboard.INDEX_HTML
        and "case'product':await renderProductV18();break;" in dashboard.INDEX_HTML
        and POLISH_MARKER in dashboard.INDEX_HTML
        and POLISH_JS_MARKER in dashboard.INDEX_HTML
    )
    logger.info("Dashboard Product UI V18 live repair + V19 polish installed=%s.", ok)
    return ok


__all__ = ["install", "patch_html", "MARKER", "POLISH_MARKER", "POLISH_JS_MARKER"]