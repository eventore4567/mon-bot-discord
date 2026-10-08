"""Contrats d'identité des journaux canoniques SentriX."""
from types import SimpleNamespace

from cogs.logs import Logs
from utils import log_service


def _identity(display_name: str):
    return SimpleNamespace(
        id=123456789012345678,
        name="nom-de-compte",
        display_name=display_name,
        display_avatar=None,
    )


def test_carte_log_affiche_pseudo_mention_et_identifiant():
    panel = Logs._embed("Membre parti", identity=_identity("Membre Test"))
    description = panel.description or ""
    assert "**Membre Test**" in description
    assert "<@123456789012345678>" in description
    assert "ID : `123456789012345678`" in description


def test_pseudo_mal_formate_ne_casse_pas_la_carte():
    panel = Logs._embed("Membre arrivé", identity=_identity("**faux titre**"))
    description = panel.description or ""
    assert r"\*\*faux titre\*\*" in description
    assert "<@123456789012345678>" in description


def test_journaux_ne_pinguent_pas_la_mention_affichee():
    assert log_service.LOG_ALLOWED_MENTIONS.users is False
    assert log_service.LOG_ALLOWED_MENTIONS.everyone is False
    assert log_service.LOG_ALLOWED_MENTIONS.roles is False
