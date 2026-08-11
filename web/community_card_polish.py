"""Ajoute une entrée Community cohérente avec le dashboard principal."""
from __future__ import annotations


def install(dashboard) -> None:
    if getattr(dashboard, "_sentrix_community_card_polish", False):
        return
    css = r'''
<style id="sentrix-community-card-style">
.quick-card{display:flex;flex-direction:column;gap:5px;margin:14px 0;padding:15px 16px;border:1px solid var(--line,#252b3a);border-radius:14px;background:linear-gradient(145deg,rgba(22,27,40,.95),rgba(13,16,24,.95));color:var(--text,#f4f6fb);text-decoration:none;transition:transform .16s ease,border-color .16s ease,background .16s ease}.quick-card:hover{transform:translateY(-1px);border-color:var(--accent,#7d8cff);background:linear-gradient(145deg,rgba(29,35,52,.98),rgba(15,19,28,.98))}.quick-card strong{font-size:14px}.quick-card span{font-size:12px;color:var(--muted,#949caf);line-height:1.45}
</style>
'''
    if 'id="sentrix-community-card-style"' not in dashboard.INDEX_HTML:
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace("</head>", css + "\n</head>", 1)
    dashboard._sentrix_community_card_polish = True
