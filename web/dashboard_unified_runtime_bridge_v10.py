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
_STATE_HEAD = "const state="
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
    script_marker = 'id="sentrix-dashboard-unified-v2"'
    script_pos = html.find(script_marker)
    if script_pos < 0:
        logger.info("Dashboard unified runtime bridge V10 skipped: unified V2 frontend not present.")
        return True
    if BRIDGE_MARKER in html:
        return True

    # Do not depend on the exact set/order of state fields: late production layers can extend
    # the object before this finalizer runs. Find the declaration inside the unified V2 script,
    # then inject immediately after its terminating semicolon. Function declarations used by
    # the bridge are hoisted within the same IIFE.
    script_end = html.find("</script>", script_pos)
    state_pos = html.find(_STATE_HEAD, script_pos, script_end if script_end >= 0 else None)
    if state_pos < 0:
        logger.error("Unified V2 runtime bridge: state declaration not found.")
        return False
    state_end = html.find(";", state_pos, script_end if script_end >= 0 else None)
    if state_end < 0:
        logger.error("Unified V2 runtime bridge: state declaration terminator not found.")
        return False

    insert_at = state_end + 1
    html = html[:insert_at] + _BRIDGE_JS + html[insert_at:]
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
