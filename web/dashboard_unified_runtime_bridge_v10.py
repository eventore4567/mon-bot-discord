"""Expose the unified V2 runtime to late dashboard adapters.

The unified dashboard keeps its state and helpers inside a strict IIFE. Late presentation
layers such as V9 run in a separate script and therefore cannot resolve those lexical names.
This bridge is applied to the final HTML and publishes only the minimal runtime surface V9
needs; it does not duplicate any dashboard state or backend action.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-unified-runtime-bridge-v10")

BRIDGE_MARKER = "__sentrixUnifiedRuntimeV10"
_STATE_TAIL = "sanctionsPage:0};"
_BRIDGE_JS = (
    "window.__sentrixUnifiedRuntimeV10={state,go,refreshAll,v62Action,toast};"
    "window.state=state;window.go=go;window.refreshAll=refreshAll;"
    "window.v62Action=v62Action;window.toast=toast;"
)


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False
    # Some registry/command CI boots run the dashboard finalizer against a legacy test HTML.
    # In that context there is no unified V2 lexical runtime to bridge, so this layer is a no-op.
    if 'id="sentrix-dashboard-unified-v2"' not in html:
        logger.info("Dashboard unified runtime bridge V10 skipped: unified V2 frontend not present.")
        return True
    if BRIDGE_MARKER in html:
        return True
    if _STATE_TAIL not in html:
        logger.error("Unified V2 runtime bridge: state anchor not found.")
        return False
    html = html.replace(_STATE_TAIL, _STATE_TAIL + _BRIDGE_JS, 1)
    dashboard.INDEX_HTML = html
    ok = all(
        marker in html
        for marker in (
            BRIDGE_MARKER,
            "window.state=state",
            "window.go=go",
            "window.refreshAll=refreshAll",
            "window.v62Action=v62Action",
            "window.toast=toast",
        )
    )
    logger.warning(
        "Dashboard unified runtime bridge V10 installed=%s: state/navigation/actions exposed to late adapters.",
        ok,
    )
    return ok


__all__ = ["install", "BRIDGE_MARKER"]
