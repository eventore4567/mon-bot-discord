"""Verrouiller les salons derrière le règlement, sans bloquer le serveur.

L'action touche TOUS les salons d'un coup. Le piège mortel : cacher aussi le
salon du règlement — plus personne ne peut l'accepter, et le serveur devient
inaccessible à tout nouveau membre. C'est ce que ce fichier verrouille.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import setup_experience_v74 as v74  # noqa: E402


class _Perms:
    def __init__(self, gere=True):
        self.manage_permissions = gere


class _Salon:
    def __init__(self, sid, nom, gere=True):
        self.id = sid
        self.name = nom
        self.mention = f"<#{sid}>"
        self._gere = gere
        self.poses = {}
        self._deja = {}

    def permissions_for(self, _membre):
        return _Perms(self._gere)

    def overwrites_for(self, cible):
        return self._deja.setdefault(cible, discord.PermissionOverwrite())

    async def set_permissions(self, cible, *, overwrite=None, reason=None):
        self.poses[getattr(cible, "name", cible)] = overwrite


class _Role:
    def __init__(self, nom):
        self.name = nom
        self.mention = f"@{nom}"


class _Guild:
    def __init__(self, salons):
        self.id = 1
        self.me = object()
        self.channels = salons
        self.default_role = _Role("@everyone")


def _lancer(salons, salon_reglement, role, saisie="VERROUILLER"):
    vue = type("V", (), {"guild": _Guild(salons)})()
    modale = v74.VerrouillerSalonsModal.__new__(v74.VerrouillerSalonsModal)
    modale.vue = vue
    modale.salon_reglement = salon_reglement
    modale.role = role
    modale.confirmation = type("T", (), {"value": saisie})()

    envoyes = []

    class _Reponse:
        def is_done(self):
            return True

        async def defer(self, **k):
            pass

    class _Interaction:
        response = _Reponse()
        followup = object()

    origine = v74.panels.envoyer

    async def _envoyer(_cible, panneau, **_k):
        envoyes.append(panneau)

    v74.panels.envoyer = _envoyer
    try:
        asyncio.run(modale.on_submit(_Interaction()))
    finally:
        v74.panels.envoyer = origine
    return envoyes


def test_le_salon_du_reglement_reste_visible():
    # LE piège : le cacher rend le serveur inaccessible à tout nouveau membre.
    reglement = _Salon(10, "reglement")
    general = _Salon(11, "general")
    role = _Role("Vérifié")
    _lancer([reglement, general], reglement, role)

    assert reglement.poses["@everyone"].view_channel is True
    assert general.poses["@everyone"].view_channel is False


def test_le_role_du_reglement_recoit_l_acces():
    reglement, general = _Salon(10, "reglement"), _Salon(11, "general")
    role = _Role("Vérifié")
    _lancer([reglement, general], reglement, role)
    assert general.poses["Vérifié"].view_channel is True


def test_les_derogations_existantes_sont_fusionnees_pas_remplacees():
    """Un rôle déjà restreint ailleurs doit le rester.

    `set_permissions(cible, **perms)` REMPLACE la dérogation ; seul
    `overwrite=` après `overwrites_for()` la fusionne. Ce test vise ce
    piège-là, pas le fonctionnement nominal.
    """
    reglement, general = _Salon(10, "reglement"), _Salon(11, "general")
    guild = _Guild([reglement, general])
    # Semer l'état AVEC l'objet que le code utilisera réellement.
    deja = general.overwrites_for(guild.default_role)
    deja.send_messages = False

    vue = type("V", (), {"guild": guild})()
    modale = v74.VerrouillerSalonsModal.__new__(v74.VerrouillerSalonsModal)
    modale.vue, modale.salon_reglement, modale.role = vue, reglement, _Role("Vérifié")
    modale.confirmation = type("T", (), {"value": "VERROUILLER"})()

    class _Interaction:
        response = type("R", (), {"is_done": lambda s: True})()
        followup = object()

    origine = v74.panels.envoyer

    async def _envoyer(*_a, **_k):
        pass

    v74.panels.envoyer = _envoyer
    try:
        asyncio.run(modale.on_submit(_Interaction()))
    finally:
        v74.panels.envoyer = origine

    pose = general.poses["@everyone"]
    assert pose.view_channel is False
    assert pose.send_messages is False, "l'ancien réglage a été écrasé"


def test_un_salon_hors_de_portee_est_nomme_pas_ignore():
    reglement = _Salon(10, "reglement")
    interdit = _Salon(12, "prive-direction", gere=False)
    envoyes = _lancer([reglement, interdit], reglement, _Role("Vérifié"))
    assert interdit.poses == {}, "aucune tentative sur un salon ingérable"
    assert envoyes, "le compte rendu doit exister"


def test_sans_confirmation_exacte_rien_n_est_touche():
    reglement, general = _Salon(10, "reglement"), _Salon(11, "general")
    _lancer([reglement, general], reglement, _Role("Vérifié"), saisie="oui")
    assert general.poses == {} and reglement.poses == {}


def test_la_confirmation_accepte_la_casse_et_les_espaces():
    reglement, general = _Salon(10, "reglement"), _Salon(11, "general")
    _lancer([reglement, general], reglement, _Role("Vérifié"), saisie="  verrouiller ")
    assert general.poses["@everyone"].view_channel is False
