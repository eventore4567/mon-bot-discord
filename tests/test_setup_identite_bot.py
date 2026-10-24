"""Changer l'avatar ou la bannière de SentriX depuis /setup — propriétaire SEUL.

L'avatar et la bannière d'un bot sont GLOBAUX : ils valent pour les 36
serveurs à la fois. Si le bouton apparaissait à tout administrateur, un seul
d'entre eux changerait l'apparence de SentriX pour tous les autres. C'est la
raison d'être de la garde testée ici.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import setup_experience_v74 as v74  # noqa: E402


class _Db:
    def __init__(self, createurs=()):
        self._createurs = set(createurs)

    async def is_bot_creator(self, uid):
        return uid in self._createurs


def _vue(author_id, createurs=()):
    vue = v74.SentriXSetupV74.__new__(v74.SentriXSetupV74)
    vue.author_id = author_id
    vue.bot = type("Bot", (), {"db": _Db(createurs)})()
    return vue


def test_un_createur_enregistre_est_reconnu():
    assert asyncio.run(_vue(4242, createurs={4242})._est_proprietaire_du_bot()) is True


def test_un_simple_administrateur_ne_l_est_pas():
    # Le cas qui compte : un admin de serveur ne doit pas voir le bouton.
    assert asyncio.run(_vue(999)._est_proprietaire_du_bot()) is False


def test_une_base_en_panne_refuse_plutot_que_d_ouvrir():
    # En cas de doute on ferme : mieux vaut cacher le bouton au propriétaire
    # que de l'offrir à un administrateur.
    vue = _vue(999)

    class _Casse:
        async def is_bot_creator(self, _uid):
            raise RuntimeError("base indisponible")

    vue.bot.db = _Casse()
    assert asyncio.run(vue._est_proprietaire_du_bot()) is False


def test_la_modale_ne_change_que_les_champs_remplis():
    modale = v74.IdentiteBotModal.__new__(v74.IdentiteBotModal)
    champs = {"username": None, "avatar": None, "banner": None}

    class _User:
        async def edit(self, **kwargs):
            champs.update(kwargs)

    class _Reponse:
        async def send_message(self, *a, **k):
            pass

    class _Interaction:
        client = type("C", (), {"user": _User()})()
        response = _Reponse()

    modale.nom = type("T", (), {"value": "NouveauNom"})()
    modale.avatar = type("T", (), {"value": ""})()
    modale.banniere = type("T", (), {"value": ""})()

    envoyes = []
    origine = v74.panels.envoyer

    async def _envoyer(_cible, panneau, **_k):
        envoyes.append(panneau)

    v74.panels.envoyer = _envoyer
    try:
        asyncio.run(modale.on_submit(_Interaction()))
    finally:
        v74.panels.envoyer = origine

    assert champs["username"] == "NouveauNom"
    assert champs["avatar"] is None and champs["banner"] is None, (
        "un champ laissé vide ne doit RIEN écraser"
    )
    assert envoyes, "le propriétaire doit recevoir un compte rendu"


def test_une_url_invalide_ne_bloque_pas_les_autres_champs():
    modale = v74.IdentiteBotModal.__new__(v74.IdentiteBotModal)
    vus = {}

    class _User:
        async def edit(self, **kwargs):
            vus.update(kwargs)

    class _Interaction:
        client = type("C", (), {"user": _User()})()
        response = type("R", (), {})()

    modale.nom = type("T", (), {"value": "Nom"})()
    modale.avatar = type("T", (), {"value": "https://exemple.invalide/x.png"})()
    modale.banniere = type("T", (), {"value": ""})()

    import cogs.owner as owner_mod

    origine_fetch = owner_mod.fetch_image_bytes
    origine_envoyer = v74.panels.envoyer
    textes = []

    async def _rien(_url):
        return None

    async def _envoyer(_cible, panneau, **_k):
        textes.append(str(getattr(panneau, "titre", "")) + str(panneau))

    owner_mod.fetch_image_bytes = _rien
    v74.panels.envoyer = _envoyer
    try:
        asyncio.run(modale.on_submit(_Interaction()))
    finally:
        owner_mod.fetch_image_bytes = origine_fetch
        v74.panels.envoyer = origine_envoyer

    assert vus.get("username") == "Nom", "le nom devait passer malgré l'avatar en échec"
    assert textes, "le compte rendu doit dire ce qui a échoué"
