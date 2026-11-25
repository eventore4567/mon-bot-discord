"""25/11/2026 : « ban pp » ne trouvait pas le membre « pp fortnite ».

La recherche n'acceptait qu'un nom exact ou ressemblant à 78 % ; « pp » ne
ressemble qu'à 31 % à « pp fortnite ». Puis la réponse redemandait « Quel
membre voulez-vous viser ? » sans dire que « pp » était introuvable.
"""
from __future__ import annotations

import inspect
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import ai_actions  # noqa: E402


def _membre(i, nom):
    return SimpleNamespace(id=i, name=nom, display_name=nom, global_name=None)


def _serveur(*membres):
    return SimpleNamespace(members=list(membres), get_member=lambda _i: None)


def test_un_debut_de_nom_en_mots_entiers_suffit():
    pp = _membre(1, "pp fortnite")
    serveur = _serveur(pp, _membre(2, "tomioka"), _membre(3, "xDefender"))
    assert ai_actions.resolve_member(serveur, "pp").member is pp
    assert ai_actions.resolve_member(serveur, "fortnite").member is pp


def test_plusieurs_candidats_reste_ambigu_et_un_bout_de_mot_ne_suffit_pas():
    serveur = _serveur(_membre(1, "pp fortnite"), _membre(2, "pp roblox"))
    assert ai_actions.resolve_member(serveur, "pp").member is None
    assert len(ai_actions.resolve_member(serveur, "pp").ambiguous) == 2
    # « tom » n'est pas un mot entier de « tomioka » : pas de devinette.
    assert ai_actions.resolve_member(_serveur(_membre(1, "tomioka")), "tom").member is None


def test_un_nom_introuvable_est_cite_avant_de_redemander():
    from cogs import ai

    source = inspect.getsource(ai)
    i = source.index("Je ne trouve pas de membre correspondant clairement")
    j = source.index('await self._ask_for_missing_action_slot(message, action, "target")', i - 2000)
    assert i < j, "le nom introuvable doit être signalé avant la question générique"
