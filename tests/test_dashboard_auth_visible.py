"""Un échec de connexion Discord doit se VOIR, jamais renvoyer en silence.

handle_login redirige vers "/?auth=missing" quand DISCORD_CLIENT_SECRET n'est
pas configuré. La page "/" réellement servie en production est le Hub de
brand_avatar_v39 (elle intercepte TOUTE requête "/" avant que le HTML de
web/dashboard.py ne soit jamais atteint) : c'est donc CETTE page, pas
INDEX_HTML, qui doit gérer le paramètre — sans quoi cliquer sur "Dashboard"
rechargeait silencieusement la même page, indiscernable de "ça ne s'ouvre pas".
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import web.brand_avatar_v39 as brand_avatar_v39  # noqa: E402
import web.dashboard as dashboard  # noqa: E402


def test_le_hub_reel_affiche_un_message_si_auth_manque():
    import inspect

    source = inspect.getsource(brand_avatar_v39._public_home_html)
    assert 'id="sxAuthNotice"' in source


def test_le_script_du_hub_lit_le_parametre_auth_missing():
    import inspect

    source = inspect.getsource(brand_avatar_v39._public_home_html)
    assert 'params.get("auth")==="missing"' in source
    assert "sxAuthNotice" in source
    # L'URL est nettoyee pour qu'un rechargement ne reaffiche pas le message.
    assert "history.replaceState" in source


def test_le_bandeau_est_visible_pas_juste_present_dans_le_dom():
    import inspect

    source = inspect.getsource(brand_avatar_v39._public_home_html)
    assert "notice.hidden=false" in source


def test_le_gabarit_dashboard_py_reste_coherent_aussi():
    """/app peut aussi recevoir ?auth=missing dans d'autres flux : son propre
    gabarit doit rester coherent, meme si le Hub est le chemin principal."""
    assert '<p id="authMessage"' in dashboard.INDEX_HTML
    assert "reportAuthFailure" in dashboard.INDEX_HTML
