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


def _legacy_feature_ui_present(html: str) -> bool:
    """Détecte une vraie ancienne UI, sans confondre le code de migration V61.

    V61 mentionne encore le mot ``features`` dans sa redirection de compatibilité et dans le
    sélecteur qui supprime un vieux bouton au runtime. Ces chaînes ne créent aucun onglet.
    """
    rendered_markers = (
        'id="sentrix-v60-features-inline"',
        'class="sx-features-shell"',
        'id="sxFeaturesFrame"',
        '<button type="button" data-tab="features"><span class="nav-icon">⚙</span>Fonctions avancées</button>',
        '<button data-tab="features"><span class="nav-icon">⚙</span>Fonctions avancées</button>',
    )
    return any(marker in html for marker in rendered_markers)


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False

    try:
        from . import dashboard_v60_features_inline as legacy
        html = html.replace(legacy.INLINE_CSS, "")
        html = html.replace(legacy.INLINE_JS, "")
    except Exception:
        logger.exception("V61 postfix : constantes Feature Suite indisponibles.")
    html = _remove_script(html, "sentrix-v60-features-inline")

    for exact in (
        '<button type="button" data-tab="features"><span class="nav-icon">⚙</span>Fonctions avancées</button>',
        '<button data-tab="features"><span class="nav-icon">⚙</span>Fonctions avancées</button>',
    ):
        html = html.replace(exact, "")

    old_nav = "const nav=$('navigation');if(!nav)return;\n    nav.innerHTML=groups.map"
    new_nav = "const nav=$('navigation');if(!nav)return;\n    if(nav.dataset.v61Built==='1'){nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.tab));return;}\n    nav.dataset.v61Built='1';\n    nav.innerHTML=groups.map"
    if old_nav in html:
        html = html.replace(old_nav, new_nav, 1)
    elif "v61Built" not in html:
        logger.warning("V61 postfix : garde de navigation introuvable.")

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
    legacy_present = _legacy_feature_ui_present(html)
    logger.info("Dashboard V61 postfix : ancienne UI features=%s, navigation stable=%s.", legacy_present, "v61Built" in html)
    return not legacy_present and 'id="sentrix-v61-unified"' in html


__all__ = ["install", "_legacy_feature_ui_present"]
