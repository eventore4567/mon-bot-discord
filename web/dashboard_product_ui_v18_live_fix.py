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
.palette{{width:min(680px,100%);border-radius:15px;background:#11161c;box-shadow:0 30px 90px rgba(0,0,0,.52)}}
.palette input{{height:56px;font-size:14px}}.palette-results{{padding:7px;max-height:min(52vh,440px)}}
.palette-item{{border:1px solid transparent;padding:10px 11px;transition:background var(--sx19-fast),border-color var(--sx19-fast),color var(--sx19-fast)}}
.palette-item:hover,.palette-item.active{{background:#17222d;border-color:#2f5778}}.palette-item[data-sx19-external] small{{color:#8ba3b9}}
.sx19-loading-bar{{position:fixed;left:0;top:0;height:2px;width:100%;z-index:240;pointer-events:none;overflow:hidden;opacity:0;transition:opacity .12s}}
.sx19-loading-bar.active{{opacity:1}}.sx19-loading-bar:before{{content:"";display:block;width:34%;height:100%;background:var(--blue);animation:sx19-load .75s ease-in-out infinite}}
@keyframes sx19-load{{from{{transform:translateX(-110%)}}to{{transform:translateX(330%)}}}}
@media(max-width:900px){{.workspace{{padding-left:18px;padding-right:18px}}}}
@media(max-width:620px){{.workspace{{padding:20px 13px 72px}}.card,.p18-card{{padding:14px}}.p18-tabs{{top:4px;overflow-x:auto;flex-wrap:nowrap}}.p18-tab{{white-space:nowrap}}.palette-backdrop{{padding:7vh 8px}}}}
@media(prefers-reduced-motion:reduce){{#content,.card,.p18-card,.metric,.row,.btn,.p18-tab,.palette-item{{animation:none!important;transition:none!important}}}}
</style>'''

_POLISH_JS = r'''<script id="sentrix-dashboard-v19-polish-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardV19Polish) return;
  window.__sentrixDashboardV19Polish = true;

  // Unified V2 already owns the global Cmd/Ctrl+K palette. V19 extends that single
  // source of truth instead of creating a second command system beside it.
  const extras = [
    ["/giveaways", "Giveaways", "Outil complet · création et gestion"],
    ["/embed-builder", "Créateur d’embeds", "Outil complet · aperçu Discord et brouillons"]
  ];
  const paletteResults = document.getElementById("paletteResults");
  const paletteInput = document.getElementById("paletteInput");
  let decorating = false;
  const addExternalPaletteItems = () => {
    if (!paletteResults || !paletteInput || decorating) return;
    decorating = true;
    try {
      const query = paletteInput.value.trim().toLocaleLowerCase("fr");
      paletteResults.querySelectorAll("[data-sx19-external]").forEach(node => node.remove());
      extras
        .filter(([, label, detail]) => !query || `${label} ${detail}`.toLocaleLowerCase("fr").includes(query))
        .forEach(([href, label, detail]) => {
          const link = document.createElement("a");
          link.className = "palette-item";
          link.href = href;
          link.dataset.sx19External = "1";
          const title = document.createElement("span");
          title.textContent = label;
          const meta = document.createElement("small");
          meta.textContent = detail;
          link.append(title, meta);
          paletteResults.appendChild(link);
        });
    } finally {
      decorating = false;
    }
  };
  if (paletteResults && paletteInput) {
    new MutationObserver(addExternalPaletteItems).observe(paletteResults, {childList:true});
    paletteInput.addEventListener("input", () => queueMicrotask(addExternalPaletteItems));
    document.getElementById("globalSearch")?.addEventListener("focus", () => queueMicrotask(addExternalPaletteItems));
    queueMicrotask(addExternalPaletteItems);
  }

  const loadBar = document.createElement("div");
  loadBar.className = "sx19-loading-bar";
  document.body.appendChild(loadBar);
  let loadTimer = null;
  document.addEventListener("click", event => {
    const target = event.target.closest(".nav button,[data-p18-tab],[data-p18-go],[data-page],.palette-item");
    if (!target) return;
    loadBar.classList.add("active");
    clearTimeout(loadTimer);
    loadTimer = setTimeout(() => loadBar.classList.remove("active"), 900);
  }, true);
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