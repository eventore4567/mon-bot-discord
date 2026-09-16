"""Execute additive dashboard controllers inside the canonical unified V2 script.

Production serves the unified V2 inline script reliably, while historical late script tags can
be present in INDEX_HTML without changing the browser-visible dashboard. V14 therefore takes
the already-finalized V9/V12/V13 JavaScript and embeds it into the canonical V2 script itself.

V28 also bridges the final V27 motion/audio controller at request time. This is necessary
because V27 is installed after V14 and a late <script> tag can exist in INDEX_HTML without
being part of the browser-visible canonical V2 program.
"""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard-native-bundle-v14")

MARKER = "__sentrixNativeBundleV14"
LATE_MOTION_BRIDGE_MARKER = "__sentrixMotionNativeBridgeV28"
LATE_MOTION_SCRIPT_ID = "sentrix-dashboard-motion-audio-v27-js"
LATE_MOTION_JS_MARKER = "__sentrixDashboardMotionAudioV27"
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


def inject_late_motion_into_native_v2(html: str) -> str:
    """Move the V27 controller into the canonical script that production really executes."""
    source = _script_body(html, LATE_MOTION_SCRIPT_ID)
    if not source:
        return html

    base_tag = '<script id="sentrix-dashboard-unified-v2">'
    base_start = html.find(base_tag)
    if base_start < 0:
        return html
    base_body_start = base_start + len(base_tag)
    base_end = html.find("</script>", base_body_start)
    if base_end < 0:
        return html

    base = html[base_body_start:base_end]
    if LATE_MOTION_BRIDGE_MARKER in base or LATE_MOTION_JS_MARKER in base:
        return html

    close = base.rfind("})();")
    if close < 0:
        return html

    native = (
        "\n/* SentriX V28: execute final V27 motion/audio in canonical V2 */\n"
        f"window.{LATE_MOTION_BRIDGE_MARKER}=true;\n"
        + source
        + "\n/* End SentriX V28 native motion bridge */\n"
    )
    base = base[:close] + native + base[close:]
    return html[:base_body_start] + base + html[base_end:]


def _install_late_motion_response_bridge(dashboard) -> None:
    """Patch /app at request time, after V27 has been installed by the finalizer."""
    previous = dashboard.handle_index
    if getattr(previous, "_sentrix_native_motion_v28", False):
        return

    async def native_motion_index(request: web.Request):
        response = await previous(request)
        if request.path != "/app" or not isinstance(response, web.Response) or response.status >= 300:
            return response

        source = response.text if isinstance(response.text, str) else str(
            getattr(dashboard, "INDEX_HTML", "") or ""
        )
        html = inject_late_motion_into_native_v2(source)
        if html == source:
            return response

        headers = dict(response.headers)
        for key in ("Content-Type", "Content-Length"):
            headers.pop(key, None)
        headers["X-SentriX-Motion-Native"] = "1"
        logger.warning(
            "Dashboard V28 native motion bridge applied on /app: v27_inside_canonical=%s bytes=%s.",
            LATE_MOTION_JS_MARKER in _script_body(html, "sentrix-dashboard-unified-v2") if _script_body(html, "sentrix-dashboard-unified-v2") else False,
            len(html.encode("utf-8")),
        )
        return web.Response(
            text=html,
            status=response.status,
            content_type="text/html",
            headers=headers,
        )

    native_motion_index._sentrix_native_motion_v28 = True
    native_motion_index._sentrix_previous_handler = previous
    dashboard.handle_index = native_motion_index


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False

    # Install this even when the static V14 bundle already exists: the V27 source only
    # appears later in the finalization order and must therefore be bridged at request time.
    _install_late_motion_response_bridge(dashboard)

    if MARKER in html:
        return True

    base_tag = '<script id="sentrix-dashboard-unified-v2">'
    base_start = html.find(base_tag)
    if base_start < 0:
        logger.info("Native Bundle V14 skipped: unified V2 frontend not present.")
        return True
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
        "Dashboard Native Bundle V14 installed=%s: V9/V12/V13 execute inside canonical unified V2 browser script; V28 request bridge armed.",
        ok,
    )
    return ok


__all__ = [
    "install",
    "MARKER",
    "LATE_MOTION_BRIDGE_MARKER",
    "inject_late_motion_into_native_v2",
]
