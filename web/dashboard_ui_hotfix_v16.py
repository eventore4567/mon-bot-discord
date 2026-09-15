"""SentriX Dashboard V16 — browser-visible navigation and compact switch hotfix.

This layer runs after Live Response V15.  It intentionally fixes only two presentation
regressions that are visible in the real /app response:
- keep the Discord verification page explicit in the native sidebar;
- prevent generic ``.field input { width: 100% }`` rules from stretching checkbox
  switches across the whole card.

V16 wraps V15's request-time patch function instead of creating another dashboard or
changing backend/API behaviour.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-ui-hotfix-v16")

BUILD = "v16-verification-nav-switch"
MARKER = "sentrix-dashboard-ui-hotfix-v16"

_STYLE = f'''<style id="{MARKER}">
/* A switch is a compact control, never a full-width form input. */
.field input.switch,
.switch-row input.switch,
.row-actions input.switch {{
  width:38px !important;
  min-width:38px !important;
  max-width:38px !important;
  height:22px !important;
  min-height:22px !important;
  padding:0 !important;
  margin:0 !important;
  flex:0 0 38px !important;
}}
.switch-row.field.full {{
  display:flex !important;
  grid-column:1 / -1;
  width:100%;
  min-width:0;
}}
.switch-row .switch-copy {{
  flex:1 1 auto;
  min-width:0;
}}
</style>'''


def patch_html(html: str) -> str:
    """Patch the exact browser HTML while remaining idempotent."""
    source = str(html or "")

    # The route already exists in Unified V2; make its purpose explicit.  If a late
    # frontend layer ever drops it, restore it directly beside Logs.
    old_nav = '["verification","Vérification","VE"]'
    new_nav = '["verification","Vérification Discord","VE"]'
    if old_nav in source:
        source = source.replace(old_nav, new_nav, 1)
    elif new_nav not in source:
        logs_nav = '["logs","Logs","LG"]'
        if logs_nav in source:
            source = source.replace(logs_nav, logs_nav + ',' + new_nav, 1)

    old_meta = 'verification:["Vérification","Écrivez votre règlement et publiez le panneau de vérification réel."]'
    new_meta = 'verification:["Vérification Discord","Configurez le règlement, le rôle et le CAPTCHA Discord réel."]'
    if old_meta in source:
        source = source.replace(old_meta, new_meta, 1)

    if MARKER not in source and "</head>" in source:
        source = source.replace("</head>", _STYLE + "\n</head>", 1)
    return source


def install(dashboard) -> bool:
    """Wrap V15's request-time authority so the fix reaches the real /app response."""
    from web import dashboard_live_response_v15

    current = dashboard_live_response_v15.patch_html
    if getattr(current, "_sentrix_ui_hotfix_v16", False):
        dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
        return MARKER in dashboard.INDEX_HTML and "Vérification Discord" in dashboard.INDEX_HTML

    previous_patch = current

    def v16_patch(html: str) -> str:
        return patch_html(previous_patch(html))

    v16_patch._sentrix_ui_hotfix_v16 = True
    v16_patch._sentrix_previous_patch = previous_patch
    dashboard_live_response_v15.patch_html = v16_patch

    dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
    ok = MARKER in dashboard.INDEX_HTML and "Vérification Discord" in dashboard.INDEX_HTML
    logger.warning(
        "Dashboard UI Hotfix V16 installed=%s: verification nav explicit + compact switches.",
        ok,
    )
    return ok


__all__ = ["install", "patch_html", "BUILD", "MARKER"]
