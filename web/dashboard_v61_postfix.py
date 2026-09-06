"""Post-condition V61 appliquée juste avant le snapshot immuable.

Cette couche ne crée aucune nouvelle fonctionnalité. Elle retire les restes de l'ancienne
Feature Suite qui peuvent avoir été injectés par une couche antérieure et corrige deux détails
UX du script V61 : ne pas reconstruire la sidebar à chaque clic, et utiliser le vrai sélecteur
du champ de couleur dans l'aperçu Design.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v61-postfix")


def _remove_script(html: str, script_id: str) -> str:
    marker = f'<script id="{script_id}">'
    start = html.find(marker)
    if start < 0:
        return html
    end = html.find("</script>", start)
    if end < 0:
        return html[:start]
    return html[:start] + html[end + len("</script>"):]


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False

    # Retire le script et le CSS historiques de « Fonctions avancées » quel que soit l'ordre
    # ayant mené à leur injection. Le backend V37 reste intact et ses API restent utilisables.
    try:
        from . import dashboard_v60_features_inline as legacy
        html = html.replace(legacy.INLINE_CSS, "")
        html = html.replace(legacy.INLINE_JS, "")
    except Exception:
        logger.exception("V61 postfix : constantes Feature Suite indisponibles.")
    html = _remove_script(html, "sentrix-v60-features-inline")

    # Les boutons statiques/dynamiques éventuellement présents dans le document final sont
    # éliminés. Le nouveau tableau de navigation V61 ne comporte volontairement pas ce tab.
    for exact in (
        '<button type="button" data-tab="features"><span class="nav-icon">⚙</span>Fonctions avancées</button>',
        '<button data-tab="features"><span class="nav-icon">⚙</span>Fonctions avancées</button>',
    ):
        html = html.replace(exact, "")

    # V61 reconstruisait toute la navigation à chaque renderTab(). Ça remplaçait les noeuds
    # DOM pendant un clic et faisait perdre focus/scroll/état actif. On la construit une fois.
    old_nav = "const nav=$('navigation');if(!nav)return;\n    nav.innerHTML=groups.map"
    new_nav = "const nav=$('navigation');if(!nav)return;\n    if(nav.dataset.v61Built==='1'){nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.tab));return;}\n    nav.dataset.v61Built='1';\n    nav.innerHTML=groups.map"
    if old_nav in html:
        html = html.replace(old_nav, new_nav, 1)
    else:
        logger.warning("V61 postfix : garde de navigation introuvable.")

    # Aperçu Design : $() est getElementById, pas querySelector.
    html = html.replace(
        "const primary=$('[data-design=\"primary_color\"]')?.value||'#d66f55';",
        "const primary=document.querySelector('[data-design=\"primary_color\"]')?.value||'#d66f55';",
        1,
    )
    html = html.replace(
        "$('sxDesignFooter').textContent=$('[data-design=\"footer\"]')?.value||'SentriX'",
        "$('sxDesignFooter').textContent=document.querySelector('[data-design=\"footer\"]')?.value||'SentriX'",
        1,
    )

    dashboard.INDEX_HTML = html
    dashboard._sentrix_dashboard_version = "v61-draft-unified-final"
    legacy_present = 'data-tab="features"' in html or 'id="sentrix-v60-features-inline"' in html
    logger.info("Dashboard V61 postfix : legacy features=%s, navigation stable=%s.", legacy_present, "v61Built" in html)
    return not legacy_present and 'id="sentrix-v61-unified"' in html


__all__ = ["install"]
