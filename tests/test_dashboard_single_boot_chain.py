"""Audit du boot unique du dashboard SentriX unifié.

Les invariants historiques restent obligatoires : aucune landing ne flashe pendant /api/me,
une ancienne requête serveur ne peut pas gagner après la nouvelle, les codes HTTP restent
disponibles et un onglet invalide retombe sur la vue d'ensemble.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from web import dashboard  # noqa: E402
from web import dashboard_oxyde_hotfix  # noqa: E402


def test_landing_est_masquee_par_defaut():
    html = dashboard.INDEX_HTML
    assert 'class="landing hidden" id="landing"' in html, (
        "#landing doit être masquée dans le HTML reçu ; elle n'est révélée qu'après un 401"
    )


def test_selectGuild_annule_la_requete_obsolete():
    html = dashboard.INDEX_HTML
    assert "state.guildAbort" in html
    assert "new AbortController()" in html
    assert "if(state.guildAbort)state.guildAbort.abort();" in html
    assert "controller!==state.guildAbort" in html
    assert "requested!==state.guildId" in html


def test_selectGuild_distingue_les_etats_d_erreur():
    html = dashboard.INDEX_HTML
    assert "e.status===503" in html
    assert "Reconnexion Discord en cours" in html
    assert "e.status===401" in html
    assert "Votre session Discord a expiré" in html


def test_navigation_invalide_retombe_sur_overview():
    html = dashboard.INDEX_HTML
    assert "if(!META[state.tab])state.tab='overview';" in html, (
        "un onglet inconnu doit retomber sur la vue d'ensemble"
    )
    assert "function go(tab){if(!META[tab])tab='overview';" in html


def test_api_conserve_le_code_http_et_le_payload_de_l_erreur():
    html = dashboard.INDEX_HTML
    assert "status:r.status" in html
    assert "Object.assign(new Error" in html
    assert "data});return data" in html


def test_oxyde_hotfix_n_a_plus_de_boucle_de_recuperation_concurrente():
    import inspect

    source = inspect.getsource(dashboard_oxyde_hotfix)
    for removed in ("directLoadGuild", "recoverIfNeeded", "applyGuildData"):
        assert f"function {removed}" not in source
    assert '.addEventListener("change"' not in source


def test_core_recovery_js_n_appelle_plus_loadGuilds():
    import inspect
    import web

    source = inspect.getsource(web)
    start = source.find("_CORE_RECOVERY_JS")
    end = source.find('"""', source.find('"""', start) + 3)
    recovery_block = source[start:end]
    for call in ("await loadGuilds()", "loadGuilds().catch", "typeof loadGuilds"):
        assert call not in recovery_block
