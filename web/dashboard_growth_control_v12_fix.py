"""Final syntax guard for the additive Growth Control V12 browser bundle.

V12 is injected as a late HTML layer. Keep this tiny guard separate so the finalizer can reject
an invalid browser bundle before Railway ever serves it.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-growth-control-v12-fix")
MARKER = "__sentrixGrowthV12SyntaxGuard"

# The affected strings are intentionally explicit: this guard must never rewrite arbitrary JS.
_REPLACEMENTS = {
    '`${fmt(d.items.length)} liens","blue"': '`${fmt(d.items.length)} liens`,"blue"',
    '`${fmt(d.items.length)} règle(s)","blue"': '`${fmt(d.items.length)} règle(s)`,"blue"',
    '`${fmt(d.items.filter(x=>x.enabled).length)} active(s)","blue"': '`${fmt(d.items.filter(x=>x.enabled).length)} active(s)`,"blue"',
    '`${fmt(r.items.filter(x=>x.enabled).length)} réactions actives","blue"': '`${fmt(r.items.filter(x=>x.enabled).length)} réactions actives`,"blue"',
    '`${fmt(policies.length)} politique(s)",""': '`${fmt(policies.length)} politique(s)`,""',
    '`${fmt(total)} actions","blue"': '`${fmt(total)} actions`,"blue"',
    '`${fmt(staff.length)} membre(s) actif(s)","ok"': '`${fmt(staff.length)} membre(s) actif(s)`,"ok"',
    '`${fmt(h.length)} version(s)","blue"': '`${fmt(h.length)} version(s)`,"blue"',
    '`${fmt(h.length)} version(s) récentes","blue"': '`${fmt(h.length)} version(s) récentes`,"blue"',
    '`${fmt(p.length)} politique(s)","blue"': '`${fmt(p.length)} politique(s)`,"blue"',
    '`${fmt(d.items.length)} webhook(s)","blue"': '`${fmt(d.items.length)} webhook(s)`,"blue"',
}


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-growth-v12-js"' not in html:
        return True
    changed = 0
    for bad, good in _REPLACEMENTS.items():
        if bad in html:
            html = html.replace(bad, good)
            changed += 1
    if MARKER not in html:
        html = html.replace(
            'if(window.__sentrixGrowthV12)return;window.__sentrixGrowthV12=true;',
            'if(window.__sentrixGrowthV12)return;window.__sentrixGrowthV12=true;window.__sentrixGrowthV12SyntaxGuard=true;',
            1,
        )
    dashboard.INDEX_HTML = html
    remaining = [bad for bad in _REPLACEMENTS if bad in html]
    ok = not remaining and MARKER in html
    logger.info("Growth Control V12 syntax guard installed=%s replacements=%s remaining=%s", ok, changed, len(remaining))
    return ok


__all__ = ["install", "MARKER"]
