"""« Activer la sécurité » allume tout, et il n'y a plus de commande (22/11/2026).

« Arrête de faire des putain de commandes, tu dois améliorer pas faire des
commandes, c'est dans sécurité que tu mets ça. »

Le bouton n'allumait que les huit protections affichées. Les dix autres
demandaient une commande chacune, et j'en avais ajouté une dix-neuvième pour
les allumer toutes — exactement le réflexe à ne pas avoir.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import securite_simple  # noqa: E402
from cogs.automod import TOGGLE_FIELDS  # noqa: E402


class _Db:
    def __init__(self):
        self.valeurs: dict[str, int] = {}

    async def execute(self, requete, params=()):
        return None

    async def set_automod(self, guild_id, champ, valeur):
        self.valeurs[champ] = int(valeur)
        # Fidèle à Database.set_automod : les deux champs de liens sont liés.
        if champ in {"antilink", "antilink_strict"}:
            self.valeurs["antilink"] = int(valeur)
            self.valeurs["antilink_strict"] = int(valeur)


def _view(db, actifs=()):
    cog = SimpleNamespace(automod_cache={1: {}})
    return SimpleNamespace(
        bot=SimpleNamespace(db=db, get_cog=lambda _n: cog),
        guild=SimpleNamespace(id=1),
        _cog=cog,
        _actifs=set(actifs),
    )


@pytest.fixture(autouse=True)
def _etat_lu(monkeypatch):
    from cogs import setup_v2_ui as policy

    async def etat(bot, guild_id, cle):
        return (cle in _etat_lu.actifs, None)

    _etat_lu.actifs = set()
    monkeypatch.setattr(policy, "_security_center_state", etat)
    monkeypatch.setattr(securite_simple.config_journal, "record", AsyncMock())
    return _etat_lu


def test_les_dix_protections_qui_demandaient_une_commande_passent_par_le_bouton():
    """C'est le cœur de la demande : plus rien à taper."""
    toutes = set(securite_simple.toutes_les_protections())
    # Les huit affichées, plus les dix qui n'étaient accessibles qu'en commande.
    assert set(securite_simple.RECOMMANDEES) < toutes
    for cle in ("anticaps", "antiemoji", "antiaccount", "security_vanity",
                "security_prune", "security_permissions", "join_gate",
                "risk_engine", "escalation"):
        assert cle in toutes, cle


def test_le_blocage_des_liens_reste_dehors():
    """Il coupe aussi les liens légitimes : c'est un choix, pas une protection.

    Les DEUX noms sont exclus parce que ``Database.set_automod`` les écrit
    ensemble — n'en exclure qu'un laissait l'autre rallumer le blocage total.
    """
    toutes = set(securite_simple.toutes_les_protections())
    assert "antilink" not in toutes
    assert "antilink_strict" not in toutes


@pytest.mark.asyncio
async def test_un_clic_allume_tout_ce_qui_etait_coupe(_etat_lu):
    db = _Db()
    allumees = await securite_simple.activer_recommandees(_view(db))

    attendu = set(securite_simple.toutes_les_protections())
    assert set(allumees) == attendu
    assert {c for c, v in db.valeurs.items() if v} == attendu
    assert db.valeurs.get("antilink", 0) == 0


@pytest.mark.asyncio
async def test_rien_n_est_jamais_eteint(_etat_lu):
    """Deux clics de suite ne doivent pas déshabiller le serveur."""
    _etat_lu.actifs = set(securite_simple.toutes_les_protections())
    db = _Db()
    assert await securite_simple.activer_recommandees(_view(db)) == []
    assert db.valeurs == {}


@pytest.mark.asyncio
async def test_une_protection_illisible_est_traitee_comme_coupee(_etat_lu, monkeypatch):
    """Mieux vaut l'allumer pour rien que laisser un trou sans le savoir."""
    from cogs import setup_v2_ui as policy

    async def etat(bot, guild_id, cle):
        if cle == "antinuke":
            raise RuntimeError("lecture impossible")
        return (True, None)

    monkeypatch.setattr(policy, "_security_center_state", etat)
    db = _Db()
    assert await securite_simple.activer_recommandees(_view(db)) == ["antinuke"]


@pytest.mark.asyncio
async def test_le_cache_du_cog_est_purge(_etat_lu):
    """Sans ça, les protections allumées resteraient inertes une demi-minute.

    ``get_automod_cached`` sert chaque message : tant que l'entrée du serveur
    est en mémoire, le clic n'a aucun effet visible — exactement ce qui fait
    dire que le bouton ne marche pas.
    """
    vue = _view(_Db())
    assert 1 in vue._cog.automod_cache
    await securite_simple.activer_recommandees(vue)
    assert 1 not in vue._cog.automod_cache


def test_plus_aucune_commande_pour_ca():
    """Garde-fou : la demande était explicite, pas une préférence passagère."""
    import io

    source = io.open("cogs/automod.py", encoding="utf-8").read()
    assert 'name="tout-securiser"' not in source
    assert 'name="admin-epargne"' not in source
    assert "TOUT_SECURISER_EXCLUES" not in source

    for registre in ("utils/access_matrix.py", "utils/slash_catalog.py"):
        contenu = io.open(registre, encoding="utf-8").read()
        assert "tout-securiser" not in contenu, registre
        assert "admin-epargne" not in contenu, registre
