"""Page « Commandes & accès » du dashboard (02/11/2026)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ops_access_n_est_servi_que_par_le_dashboard_unifie():
    # L'ancienne route d'Operations Center passait devant et répondait 503
    # (cog non chargé en production) : la page Accès ne s'ouvrait jamais.
    legacy = (ROOT / "web" / "operations_center.py").read_text(encoding="utf-8")
    assert 'add_get("/api/guilds/{guild_id}/ops/access"' not in legacy
    plus = (ROOT / "web" / "dashboard_ops_suite_plus.py").read_text(encoding="utf-8")
    assert 'add_get("/api/guilds/{guild_id}/ops/access", access_list)' in plus


def test_liste_des_commandes_courte_par_defaut_et_prefixe_honnete():
    js = (ROOT / "web" / "dashboard_ui" / "js" / "40_tools.js").read_text(encoding="utf-8")
    assert "items.slice(0, 20)" in js and "commandShowAll" in js
    assert "Les commandes + ont été supprimées" not in js
