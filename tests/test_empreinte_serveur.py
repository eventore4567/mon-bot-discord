"""Copie préventive du serveur : ce qu'elle garde, et quand elle refuse (21/11/2026).

« dès que anti nuke est là, il prend une copie entière du serveur en quelques
secondes, comme ça si y a un nuke ça ban la personne est ressortir tout. »

L'anti-nuke ne savait restaurer que ce qu'il avait VU supprimer. Bot redémarré
pendant le nuke, bot hors ligne, événement perdu par la passerelle : plus rien
à restaurer. L'empreinte comble ce trou.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import empreinte_serveur as emp  # noqa: E402


class _Db:
    """Juste assez de base pour la table de l'empreinte (une ligne par serveur)."""

    def __init__(self):
        self.lignes: dict[int, tuple[int, str]] = {}
        self.ecritures = 0

    async def execute(self, requete, params=()):
        if "CREATE TABLE" in requete:
            return
        if f"INSERT INTO {emp.TABLE}" in requete:
            self.ecritures += 1
            self.lignes[int(params[0])] = (int(params[1]), params[2])

    async def fetchone(self, requete, params=()):
        if f"FROM {emp.TABLE}" in requete:
            ligne = self.lignes.get(int(params[0]))
            if ligne is None:
                return None
            return {"pris_le": ligne[0], "contenu_json": ligne[1]}
        return None


def _role(identifiant, *, nom="staff", managed=False, position=1, permissions=8):
    return SimpleNamespace(id=identifiant, name=nom, managed=managed, position=position,
                           permissions=permissions)


def _instantane_role(role):
    return {"id": int(role.id), "name": role.name, "managed": bool(role.managed),
            "position": int(role.position), "permissions": int(role.permissions)}


def _salon(identifiant, *, nom="general", kind="text", position=0, category_id=None):
    return SimpleNamespace(id=identifiant, name=nom, kind=kind, position=position,
                           category_id=category_id)


def _instantane_salon(salon):
    return {"id": int(salon.id), "name": salon.name, "kind": salon.kind,
            "position": int(salon.position), "category_id": salon.category_id}


def _guild(roles=(), salons=(), identifiant=1):
    presents_roles = {int(r.id): r for r in roles}
    presents_salons = {int(s.id): s for s in salons}
    return SimpleNamespace(
        id=identifiant,
        roles=list(roles),
        channels=list(salons),
        get_role=presents_roles.get,
        get_channel=presents_salons.get,
    )


def _capture(roles=(), salons=()):
    return emp.composer(_guild(roles, salons),
                        instantane_role=_instantane_role,
                        instantane_salon=_instantane_salon)


# --------------------------------------------------------------------- composer

def test_everyone_et_roles_d_integration_ne_sont_pas_gardes():
    """Deux rôles qu'on ne pourra jamais recréer, donc inutiles à mémoriser.

    ``@everyone`` porte l'ID du serveur et ne peut pas être supprimé. Un rôle
    « managed » appartient à un bot ou à un boost : Discord refuse sa création
    par un tiers. Les garder promettrait une restauration impossible.
    """
    contenu = _capture(roles=[_role(1), _role(10), _role(11, managed=True)])
    assert [r["id"] for r in contenu["roles"]] == [10]


def test_un_role_illisible_ne_vide_pas_toute_l_empreinte():
    """Un objet cassé ne doit pas coûter la copie des 40 autres rôles."""
    def instantane(role):
        if role.id == 99:
            raise RuntimeError("rôle illisible")
        return _instantane_role(role)

    contenu = emp.composer(
        _guild([_role(10), _role(99), _role(12)], [_salon(20)]),
        instantane_role=instantane,
        instantane_salon=_instantane_salon,
    )
    assert [r["id"] for r in contenu["roles"]] == [10, 12]
    assert len(contenu["salons"]) == 1


# --------------------------------------------------------------------- capturer

@pytest.mark.asyncio
async def test_deux_captures_rapprochees_n_en_ecrivent_qu_une():
    """Un ménage de salons ne doit pas déclencher une écriture par salon."""
    db = _Db()
    guild = _guild([_role(10)], [_salon(20)])
    kwargs = dict(instantane_role=_instantane_role, instantane_salon=_instantane_salon)

    assert await emp.capturer(db, guild, maintenant=1000, **kwargs) is not None
    assert await emp.capturer(db, guild, maintenant=1001, **kwargs) is None
    assert db.ecritures == 1

    tard = 1000 + emp.DELAI_ENTRE_CAPTURES_S + 1
    assert await emp.capturer(db, guild, maintenant=tard, **kwargs) is not None
    assert db.ecritures == 2


@pytest.mark.asyncio
async def test_forcer_ignore_le_frein():
    db = _Db()
    guild = _guild([_role(10)], [_salon(20)])
    kwargs = dict(instantane_role=_instantane_role, instantane_salon=_instantane_salon)
    await emp.capturer(db, guild, maintenant=1000, **kwargs)
    assert await emp.capturer(db, guild, maintenant=1001, forcer=True, **kwargs) is not None
    assert db.ecritures == 2


@pytest.mark.asyncio
async def test_un_serveur_vu_vide_n_ecrase_pas_une_bonne_empreinte():
    """Le cas qui rendrait l'empreinte pire que rien.

    Au démarrage, le cache de discord.py peut être encore vide : le serveur
    « n'a » alors ni salon ni rôle. Écrire cette copie-là remplacerait la vraie
    par du vide, et le filet ne restaurerait plus rien du tout.
    """
    db = _Db()
    kwargs = dict(instantane_role=_instantane_role, instantane_salon=_instantane_salon)
    await emp.capturer(db, _guild([_role(10)], [_salon(20)]), maintenant=1000, **kwargs)

    tard = 1000 + emp.DELAI_ENTRE_CAPTURES_S + 1
    assert await emp.capturer(db, _guild([], []), maintenant=tard, **kwargs) is None

    garde = await emp.lire(db, 1)
    assert [r["id"] for r in garde["roles"]] == [10]


@pytest.mark.asyncio
async def test_relire_rend_exactement_ce_qui_a_ete_ecrit():
    db = _Db()
    guild = _guild([_role(10, nom="modo")], [_salon(20, nom="annonces")])
    await emp.capturer(db, guild, maintenant=4242,
                       instantane_role=_instantane_role, instantane_salon=_instantane_salon)
    relu = await emp.lire(db, 1)
    assert relu["pris_le"] == 4242
    assert relu["roles"][0]["name"] == "modo"
    assert relu["salons"][0]["name"] == "annonces"


@pytest.mark.asyncio
async def test_lire_sans_empreinte_ou_avec_json_casse_rend_none():
    db = _Db()
    assert await emp.lire(db, 1) is None
    db.lignes[1] = (10, "{pas du json")
    assert await emp.lire(db, 1) is None
    db.lignes[1] = (10, json.dumps(["liste", "au", "lieu", "d'objet"]))
    assert await emp.lire(db, 1) is None


# --------------------------------------------------------------------- disparus

def test_disparus_ne_liste_que_ce_qui_manque_vraiment():
    empreinte = dict(_capture([_role(10), _role(11)],
                              [_salon(20), _salon(21), _salon(30, kind="category")]),
                     pris_le=1000)
    # Le rôle 11 et le salon 21 ont survécu.
    vivant = _guild([_role(11)], [_salon(21)])
    absents = emp.disparus(empreinte, vivant, maintenant=1100)

    assert [r["id"] for r in absents["roles"]] == [10]
    assert [s["id"] for s in absents["categories"]] == [30]
    assert [s["id"] for s in absents["salons"]] == [20]
    assert emp.total(absents) == 3


def test_les_categories_sont_rendues_a_part_des_salons():
    """Ordre de restauration : un salon ne peut pas rejoindre une catégorie absente.

    ``_restore_deleted_channel`` retrouve la catégorie par ``channel_map``, qui
    n'est rempli que par les restaurations déjà faites. Rendre les deux listes
    mélangées ferait ressortir la moitié des salons à la racine du serveur.
    """
    empreinte = dict(_capture([], [_salon(40, kind="category"), _salon(41, category_id=40)]),
                     pris_le=1000)
    absents = emp.disparus(empreinte, _guild(), maintenant=1100)
    assert emp.ORDRE.index("categories") < emp.ORDRE.index("salons")
    assert [s["id"] for s in absents["categories"]] == [40]
    assert [s["id"] for s in absents["salons"]] == [41]


def test_une_empreinte_trop_vieille_ne_restaure_rien():
    """Recréer un serveur d'il y a un mois ferait plus de mal que le nuke.

    Entre-temps le propriétaire a pu supprimer exprès vingt salons. Un filet
    qui les ferait tous revenir serait un nuke à son tour.
    """
    empreinte = dict(_capture([_role(10)], [_salon(20)]), pris_le=1000)
    tard = 1000 + emp.AGE_MAX_S + 1
    assert emp.trop_vieille(empreinte, maintenant=tard) is True
    assert emp.total(emp.disparus(empreinte, _guild(), maintenant=tard)) == 0
    # Juste avant la limite, en revanche, le filet fonctionne.
    assert emp.total(emp.disparus(empreinte, _guild(), maintenant=1000 + emp.AGE_MAX_S - 1)) == 2


def test_les_roles_sont_recrees_du_bas_vers_le_haut():
    """Discord refuse de placer un rôle au-dessus de celui du bot.

    En partant du plus bas, chaque rôle recréé reste sous le précédent et la
    hiérarchie se reconstruit dans le bon sens.
    """
    empreinte = dict(
        _capture([_role(10, position=7), _role(11, position=2), _role(12, position=5)], []),
        pris_le=1000,
    )
    absents = emp.disparus(empreinte, _guild(), maintenant=1100)
    assert [r["id"] for r in absents["roles"]] == [11, 12, 10]
