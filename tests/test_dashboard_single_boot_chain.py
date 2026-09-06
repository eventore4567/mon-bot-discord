"""Audit dashboard : trop de couches géraient chacune loadSession/loadGuilds/
selectGuild en parallèle, sans coordination.

Root causes trouvées et corrigées ici :

1. #landing (la vieille page d'accueil intégrée à web/dashboard.py, "Tout votre
   serveur, au même endroit.") était visible par défaut et seulement masquée par
   loadSession() une fois /api/me résolu. Comme / est maintenant entièrement
   pris en charge séparément par brand_avatar_v39.py, cette section n'a plus
   aucune raison d'exister visible sur /app — tout ralentissement de /api/me
   (reconnexion HA, contention DB) la laissait affichée, superposée au
   dashboard : exactement le bug rapporté ("la landing et le dashboard
   s'affichent en même temps").

2. web/dashboard_oxyde_hotfix.py réimplémentait sa propre boucle de
   récupération de /api/guilds/<id> (directLoadGuild/recoverIfNeeded) avec SON
   PROPRE écouteur "change" sur #serverSelect, en plus de celui du dashboard
   canonique (selectGuild). Un changement rapide de serveur pouvait réafficher
   les données de l'ancien serveur si cette requête parallèle revenait après
   celle du nouveau.

3. web/__init__.py (_CORE_RECOVERY_JS) appelait aussi loadGuilds() de façon
   indépendante sur son propre minuteur, sans coordination avec le mécanisme de
   nouvelle tentative déjà intégré à loadGuilds() lui-même (dashboard_recovery_v54.py).

Vérifié séparément (voir NOTES) : web/setup_dashboard.py et
web/design_setup_dashboard.py contiennent des patchs par remplacement de texte
exact ciblant l'ancien texte de selectGuild/renderTab, mais leurs propres
fonctions install() ne sont appelées nulle part dans le dépôt (confirmé par
recherche exhaustive) — les modifications ci-dessous ne les affectent donc pas
en pratique, seulement du code déjà mort.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from web import dashboard  # noqa: E402
from web import dashboard_oxyde_hotfix  # noqa: E402


def test_landing_est_masquee_par_defaut():
    """/app ne doit jamais montrer la landing, même avant que /api/me réponde."""
    assert '<section id="landing" class="hidden">' in dashboard.INDEX_HTML, (
        "#landing doit être masquée dès le HTML de base, pas seulement par "
        "loadSession() une fois /api/me résolu — sinon tout ralentissement de "
        "cet appel la rend visible, superposée au dashboard"
    )


def test_selectGuild_annule_la_requete_obsolete():
    assert "state.guildAbort" in dashboard.INDEX_HTML
    assert "new AbortController()" in dashboard.INDEX_HTML
    assert 'if(state.guildAbort)state.guildAbort.abort();' in dashboard.INDEX_HTML


def test_selectGuild_distingue_les_etats_d_erreur():
    html = dashboard.INDEX_HTML
    assert "e.status===503" in html, "un 503 (Discord pas encore prêt) doit être traité différemment d'une erreur générique"
    assert "Reconnexion Discord en cours" in html
    assert "e.status===401" in html, "une session expirée doit être traitée différemment d'un serveur introuvable"


def test_renderTab_ne_reste_jamais_sur_un_onglet_invalide():
    assert 'if(!tabs[state.tab])state.tab="general";' in dashboard.INDEX_HTML, (
        "sans ce filet, un state.tab invalide fait planter renderTab() en plein "
        "milieu (tab.title sur undefined), laissant #fields vide — l'écran "
        "central noir rapporté après un chargement par ailleurs réussi"
    )


def test_json_conserve_le_code_http_de_l_erreur():
    assert "err.status=res.status" in dashboard.INDEX_HTML, (
        "sans le code HTTP sur l'erreur, impossible de distinguer un 503 "
        "(Discord pas prêt) d'un 401 (session expirée) ou d'une vraie panne"
    )


def test_oxyde_hotfix_n_a_plus_de_boucle_de_recuperation_concurrente():
    """L'ancienne réimplémentation parallèle de selectGuild a été retirée."""
    import inspect

    source = inspect.getsource(dashboard_oxyde_hotfix)
    for removed in ("directLoadGuild", "recoverIfNeeded", "applyGuildData"):
        assert f"function {removed}" not in source, (
            f"{removed} réintroduit une récupération de /api/guilds/<id> parallèle "
            "à selectGuild() — c'est exactement la course qui pouvait réafficher "
            "les données d'un ancien serveur lors d'un changement rapide"
        )
    assert '.addEventListener("change"' not in source, (
        "un second écouteur \"change\" sur #serverSelect, en plus de celui posé par "
        "le dashboard canonique, recrée la même course"
    )


def test_core_recovery_js_n_appelle_plus_loadGuilds():
    """web/__init__.py : le filet de sécurité de démarrage ne doit plus
    redéclencher loadGuilds() de façon indépendante — ce rôle appartient
    uniquement à loadGuilds() lui-même (dashboard_recovery_v54.py)."""
    import inspect

    import web

    source = inspect.getsource(web)
    start = source.find("_CORE_RECOVERY_JS")
    end = source.find('"""', source.find('"""', start) + 3)
    recovery_block = source[start:end]
    for call in ("await loadGuilds()", "loadGuilds().catch", "typeof loadGuilds"):
        assert call not in recovery_block, (
            "un second déclencheur indépendant de loadGuilds() ici recrée la course "
            "avec le mécanisme de nouvelle tentative déjà intégré à loadGuilds()"
        )
