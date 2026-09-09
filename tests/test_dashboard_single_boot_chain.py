"""Audit du boot unique du dashboard SentriX V60.

Les invariants restent les mêmes que lors des corrections historiques : aucune landing ne
flashe pendant /api/me, une ancienne requête serveur ne peut pas gagner après la nouvelle,
les codes HTTP restent disponibles et un onglet invalide retombe sur Général. Les tests
visent désormais le frontend V60 final au lieu des noms d'objets des anciennes générations.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from web import dashboard  # noqa: E402
from web import dashboard_oxyde_hotfix  # noqa: E402


def test_landing_est_masquee_par_defaut():
    assert '<section id="landing" class="landing hidden">' in dashboard.INDEX_HTML, (
        "#landing doit être masquée dans le HTML reçu ; elle n'est révélée qu'après un 401"
    )


def test_selectGuild_annule_la_requete_obsolete():
    html = dashboard.INDEX_HTML
    assert "state.guildAbort" in html
    assert "new AbortController()" in html
    assert "if(state.guildAbort)state.guildAbort.abort();" in html
    assert "controller!==state.guildAbort" in html


def test_selectGuild_distingue_les_etats_d_erreur():
    html = dashboard.INDEX_HTML
    assert "e.status===503" in html
    assert "Reconnexion Discord en cours" in html
    assert "e.status===401" in html
    assert "Votre session Discord a expiré" in html


def test_renderTab_ne_reste_jamais_sur_un_onglet_invalide():
    html = dashboard.INDEX_HTML
    assert 'if(!special.has(state.tab)&&!tabMeta[state.tab])state.tab="general";' in html, (
        "un onglet V60 inconnu doit retomber sur Général au lieu de laisser le centre vide"
    )


def test_json_conserve_le_code_http_de_l_erreur():
    html = dashboard.INDEX_HTML
    # api() attache le status HTTP à l'Error utilisée ensuite par le bootguard 401/503.
    assert "status:r.status" in html
    assert "Object.assign(new Error" in html


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
