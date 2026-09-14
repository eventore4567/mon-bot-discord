"""Execute additive dashboard controllers inside the canonical unified V2 script.

Production serves the unified V2 inline script reliably, while historical late script tags can
be present in INDEX_HTML without changing the browser-visible dashboard.  V14 therefore takes
the already-finalized V9/V12/V13 JavaScript (after their syntax guards ran) and embeds it into
the canonical V2 script itself.  This keeps the existing APIs and listeners unchanged while
making the visible controls execute in the same browser program that already renders SentriX.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-native-bundle-v14")

MARKER = "__sentrixNativeBundleV14"
_BASE_ID = 'id="sentrix-dashboard-unified-v2"'
_SOURCE_IDS = (
    "sentrix-unified-adapter-v9-js",
    "sentrix-growth-v12-js",
    "sentrix-dashboard-visibility-v13-js",
)


def _script_body(html: str, script_id: str) -> str | None:
    marker = f'<script id="{script_id}">'
    start = html.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = html.find("</script>", start)
    if end < 0:
        return None
    return html[start:end].strip()


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False
    if MARKER in html:
        return True

    base_tag = '<script id="sentrix-dashboard-unified-v2">'
    base_start = html.find(base_tag)
    if base_start < 0:
        logger.error("Native Bundle V14: unified V2 script missing.")
        return False
    base_body_start = base_start + len(base_tag)
    base_end = html.find("</script>", base_body_start)
    if base_end < 0:
        logger.error("Native Bundle V14: unified V2 script terminator missing.")
        return False

    bodies: list[str] = []
    for script_id in _SOURCE_IDS:
        body = _script_body(html, script_id)
        if not body:
            logger.error("Native Bundle V14: source script missing: %s", script_id)
            return False
        bodies.append(body)

    base = html[base_body_start:base_end]
    # The unified V2 script is one IIFE.  Execute the finalized additive controllers immediately
    # before that IIFE closes, after the native dashboard has registered its own handlers.
    close = base.rfind("})();")
    if close < 0:
        logger.error("Native Bundle V14: unified V2 IIFE closing marker missing.")
        return False

    native = (
        "\n/* SentriX Native Bundle V14: browser-visible controllers */\n"
        f"window.{MARKER}=true;\n"
        + "\n".join(bodies)
        + "\n/* End SentriX Native Bundle V14 */\n"
    )
    base = base[:close] + native + base[close:]
    html = html[:base_body_start] + base + html[base_end:]

    # Make the real V96 control visible even if every enhancement layer is disabled by the
    # browser: this text belongs to the canonical V2 verification renderer itself.
    html = html.replace(
        "<b>CAPTCHA</b><span>Demande le code visuel avant d’attribuer le rôle.</span>",
        "<b>CAPTCHA V96 RÉEL</b><span>Le membre résout le code visuel avant que SentriX attribue le rôle.</span>",
        1,
    )
    html = html.replace(
        "card('Règlement & vérification','Écrivez le texte exact présenté aux membres.'",
        "card('Règlement & vérification · CAPTCHA V96 RÉEL','Écrivez le texte exact présenté aux membres.'",
        1,
    )

    dashboard.INDEX_HTML = html
    ok = all(
        token in html
        for token in (
            MARKER,
            "Réactions automatiques",
            "Statistiques",
            "CAPTCHA V96 RÉEL",
            "sentrix-dashboard-unified-v2",
        )
    )
    logger.warning(
        "Dashboard Native Bundle V14 installed=%s: V9/V12/V13 execute inside canonical unified V2 browser script.",
        ok,
    )
    return ok


__all__ = ["install", "MARKER"]
