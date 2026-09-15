"""V18 live-bundle anchor repair.

Production V15 expands the native Administration navigation and render switch before V18 sees
the response. The first V18 implementation used exact pre-V15 strings, so its backend loaded
but its UI correctly failed open to V16. This repair keeps the existing V18 UI/body and only
makes the three insertion points tolerant of the live V15/V16 bundle.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-product-ui-v18-live-fix")
MARKER = "sentrix-dashboard-product-ui-v18-live-fix"


def patch_html(html: str) -> str:
    from web import dashboard_product_ui_v18 as v18

    source = str(html or "")
    # Let the original implementation handle native/pre-V15 HTML when it can.
    patched = v18._ORIGINAL_PATCH_HTML_V18(source) if hasattr(v18, "_ORIGINAL_PATCH_HTML_V18") else source
    if v18.JS_MARKER in patched and v18.MARKER in patched and '["product","Centre avancé","PX"]' in patched:
        return patched

    source = patched
    tag = '<script id="sentrix-dashboard-unified-v2">'
    start = source.find(tag)
    if start < 0:
        return source
    body_start = start + len(tag)
    end = source.find("</script>", body_start)
    if end < 0:
        return source
    body = source[body_start:end]

    # V15 keeps the Diagnostic token but appends several technical entries after it.
    # Insert Product beside Diagnostic without assuming what comes after it.
    product_nav = '["product","Centre avancé","PX"]'
    diagnostic_nav = '["diagnostic","Diagnostic","DG"]'
    if product_nav not in body:
        if diagnostic_nav not in body:
            return source
        body = body.replace(diagnostic_nav, diagnostic_nav + ',' + product_nav, 1)

    meta_anchor = 'diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],'
    product_meta = 'product:["Centre avancé","Actions staff, automations, membres, audit, templates et accès dashboard."],'
    if product_meta not in body:
        if meta_anchor not in body:
            return source
        body = body.replace(meta_anchor, meta_anchor + product_meta, 1)

    render_anchor = 'async function render(force=false)'
    if v18.JS_MARKER not in body:
        if render_anchor not in body:
            return source
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
            return source
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
    return source


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
    )
    logger.warning("Dashboard Product UI V18 live-anchor fix installed=%s.", ok)
    return ok


__all__ = ["install", "patch_html", "MARKER"]
