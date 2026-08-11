"""Expose clairement le centre Community depuis le dashboard principal."""
from __future__ import annotations


_OLD_SIMPLE_CARD = '''<article class="sx-simple-card"><div><div class="sx-simple-kicker">Communauté</div><h3>Accueil et tickets</h3><p>Configurez l'arrivée des membres puis le système de support.</p></div><div><button class="btn" type="button" data-sx-destination="welcome">Accueil</button> <button class="btn" type="button" data-sx-destination="tickets">Tickets</button></div></article>'''

_NEW_SIMPLE_CARD = '''<article class="sx-simple-card sx-community-main-card"><div><div class="sx-simple-kicker">Communauté</div><h3>Accueil, tickets et communauté</h3><p>Gérez l'arrivée des membres, le support, les automatisations, les candidatures staff et les vocaux temporaires.</p></div><div class="sx-community-actions"><button class="btn" type="button" data-sx-destination="welcome">Accueil</button><button class="btn" type="button" data-sx-destination="tickets">Tickets</button><a class="btn primary" href="/community">Centre communauté</a></div><div class="sx-community-features"><span>Automatisations</span><span>Candidatures staff</span><span>Vocaux temporaires</span></div></article>'''


def install(dashboard) -> None:
    if getattr(dashboard, "_sentrix_community_card_polish", False):
        return

    css = r'''
<style id="sentrix-community-card-style">
.quick-card{display:flex;flex-direction:column;gap:5px;margin:14px 0;padding:15px 16px;border:1px solid var(--line,#252b3a);border-radius:14px;background:linear-gradient(145deg,rgba(22,27,40,.95),rgba(13,16,24,.95));color:var(--text,#f4f6fb);text-decoration:none;transition:transform .16s ease,border-color .16s ease,background .16s ease}.quick-card:hover{transform:translateY(-1px);border-color:var(--accent,#7d8cff);background:linear-gradient(145deg,rgba(29,35,52,.98),rgba(15,19,28,.98))}.quick-card strong{font-size:14px}.quick-card span{font-size:12px;color:var(--muted,#949caf);line-height:1.45}
.sx-community-actions{display:flex;gap:8px;flex-wrap:wrap}.sx-community-actions a.btn{text-decoration:none;display:inline-flex;align-items:center;justify-content:center}.sx-community-features{display:flex;gap:7px;flex-wrap:wrap;margin-top:1px}.sx-community-features span{font-size:11px;color:var(--muted,#949caf);border:1px solid var(--line,#252b3a);background:#0d111c;border-radius:999px;padding:5px 8px}
</style>
'''
    if 'id="sentrix-community-card-style"' not in dashboard.INDEX_HTML:
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace("</head>", css + "\n</head>", 1)

    # Le mode simple avait encore l'ancienne carte « Accueil et tickets ». On garde ses
    # deux raccourcis et on expose clairement le nouveau centre Community au même endroit.
    if _OLD_SIMPLE_CARD in dashboard.INDEX_HTML:
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(_OLD_SIMPLE_CARD, _NEW_SIMPLE_CARD, 1)

    dashboard._sentrix_community_card_polish = True
