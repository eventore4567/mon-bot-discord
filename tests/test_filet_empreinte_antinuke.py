"""Le filet : restaurer sans avoir vu passer le nuke (21/11/2026).

Les passes de ``restore_burst`` rejouent les dégâts enregistrés au moment où
Discord les a annoncés. Si le bot a redémarré pendant le nuke, était hors ligne,
ou n'a jamais reçu l'événement, cette table est vide : l'auteur est banni mais
il n'y a plus rien à remettre en place.

Le filet compare l'état réel du serveur à la copie préventive
(utils/empreinte_serveur) et recrée la différence.
"""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs.antinuke_emergency_v55 import AntiNukeEmergencyV55  # noqa: E402
from utils import empreinte_serveur as emp  # noqa: E402


class _Db:
    def __init__(self, empreinte=None, pris_le=None):
        self.contenu = empreinte
        # Empreinte prise à l'instant : c'est le cas normal, la boucle de
        # veille la rafraîchit toutes les dix minutes.
        self.pris_le = int(time.time()) if pris_le is None else pris_le

    async def execute(self, requete, params=()):
        return None

    async def fetchone(self, requete, params=()):
        if f"FROM {emp.TABLE}" in requete and self.contenu is not None:
            return {"pris_le": self.pris_le,
                    "contenu_json": json.dumps(self.contenu, ensure_ascii=False)}
        return None


def _cog(db):
    cog = AntiNukeEmergencyV55.__new__(AntiNukeEmergencyV55)
    cog.bot = SimpleNamespace(db=db)
    cog._restore_role = AsyncMock(side_effect=lambda g, s, m: SimpleNamespace(id=s["id"]))
    cog._restore_deleted_channel = AsyncMock(
        side_effect=lambda g, s, cm, rm: SimpleNamespace(id=s["id"])
    )
    return cog


def _guild(roles=(), salons=()):
    r = {int(i): SimpleNamespace(id=i) for i in roles}
    s = {int(i): SimpleNamespace(id=i) for i in salons}
    return SimpleNamespace(id=1, get_role=r.get, get_channel=s.get)


def _empreinte(roles=(), salons=()):
    return {
        "roles": [{"id": i, "name": f"r{i}", "position": i, "managed": False} for i in roles],
        "salons": [
            {"id": i, "name": f"s{i}", "kind": kind, "position": i, "category_id": None}
            for i, kind in salons
        ],
    }


@pytest.mark.asyncio
async def test_tout_ce_qui_manque_est_recree():
    db = _Db(_empreinte(roles=[10, 11], salons=[(20, "category"), (21, "text")]))
    cog = _cog(db)
    # Le serveur a tout perdu, et la table des dégâts est vide.
    bilan = await cog._restaurer_depuis_empreinte(_guild(), {}, {})

    assert bilan == {"roles_restored": 2, "channels_restored": 2, "failed": 0}


@pytest.mark.asyncio
async def test_les_categories_passent_avant_les_salons():
    """Sinon la moitié des salons ressortent à la racine du serveur.

    ``_restore_deleted_channel`` retrouve la catégorie d'un salon dans
    ``channel_map``, qui ne contient que ce qui a DÉJÀ été recréé.
    """
    db = _Db(_empreinte(salons=[(21, "text"), (20, "category")]))
    cog = _cog(db)
    await cog._restaurer_depuis_empreinte(_guild(), {}, {})

    ordre = [appel.args[1]["id"] for appel in cog._restore_deleted_channel.await_args_list]
    assert ordre == [20, 21]


@pytest.mark.asyncio
async def test_ce_qui_a_survecu_n_est_pas_touche():
    """Le filet ne doit pas créer de doublons de ce qui est encore là."""
    db = _Db(_empreinte(roles=[10, 11], salons=[(20, "text")]))
    cog = _cog(db)
    bilan = await cog._restaurer_depuis_empreinte(_guild(roles=[11], salons=[20]), {}, {})

    assert bilan["roles_restored"] == 1
    assert bilan["channels_restored"] == 0
    assert cog._restore_role.await_args.args[1]["id"] == 10


@pytest.mark.asyncio
async def test_sans_empreinte_le_filet_ne_fait_rien_et_ne_plante_pas():
    """Serveur jamais capturé, ou table absente sur une vieille base."""
    cog = _cog(_Db(None))
    bilan = await cog._restaurer_depuis_empreinte(_guild(), {}, {})
    assert bilan == {"roles_restored": 0, "channels_restored": 0, "failed": 0}
    cog._restore_role.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_empreinte_trop_vieille_ne_ressuscite_pas_le_serveur():
    """Le garde-fou qui évite que le filet devienne lui-même un nuke.

    Si le propriétaire a supprimé vingt salons exprès le mois dernier, les
    faire tous revenir serait pire que l'incident qu'on répare.
    """
    db = _Db(_empreinte(roles=[10], salons=[(20, "text")]), pris_le=0)
    cog = _cog(db)
    bilan = await cog._restaurer_depuis_empreinte(_guild(), {}, {})
    assert bilan == {"roles_restored": 0, "channels_restored": 0, "failed": 0}


@pytest.mark.asyncio
async def test_un_echec_de_recreation_est_compte():
    db = _Db(_empreinte(roles=[10], salons=[(20, "text")]))
    cog = _cog(db)
    cog._restore_role = AsyncMock(return_value=None)
    cog._restore_deleted_channel = AsyncMock(return_value=None)
    bilan = await cog._restaurer_depuis_empreinte(_guild(), {}, {})
    assert bilan["failed"] == 2


@pytest.mark.asyncio
async def test_le_filet_partage_la_correspondance_des_roles():
    """Les permissions des salons recréés citent les anciens IDs de rôle.

    ``role_map`` traduit l'ancien ID vers le rôle qui vient d'être recréé. Si
    le filet travaillait avec sa propre table, chaque salon ressortirait avec
    des permissions vides.
    """
    db = _Db(_empreinte(roles=[10], salons=[(20, "text")]))
    cog = _cog(db)
    role_map: dict = {}
    channel_map: dict = {}
    await cog._restaurer_depuis_empreinte(_guild(), channel_map, role_map)

    assert cog._restore_role.await_args.args[2] is role_map
    assert cog._restore_deleted_channel.await_args.args[3] is role_map
    assert cog._restore_deleted_channel.await_args.args[2] is channel_map
