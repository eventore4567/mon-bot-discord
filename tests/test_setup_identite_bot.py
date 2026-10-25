"""Le profil de SentriX se personnalise PAR SERVEUR, avatar et banniere seulement.

Un administrateur ne doit jamais modifier l'identite globale du bot.
Le champ bio n'est plus propose dans /setup et ne doit pas etre modifie.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from cogs import setup_experience_v74 as v74  # noqa: E402


def _executer(avatar="", banniere="", image=b"octets"):
    appels_membre, appels_globaux = [], []

    class _Moi:
        async def edit(self, **kwargs):
            appels_membre.append(kwargs)

    class _User:
        async def edit(self, **kwargs):
            appels_globaux.append(kwargs)

    class _Reponse:
        def is_done(self):
            return True

        async def defer(self, **k):
            pass

    class _Interaction:
        guild = type("G", (), {"me": _Moi()})()
        client = type("C", (), {"user": _User()})()
        response = _Reponse()
        followup = object()

    modale = v74.IdentiteBotModal.__new__(v74.IdentiteBotModal)
    modale.vue = None
    modale.avatar = type("T", (), {"value": avatar})()
    modale.banniere = type("T", (), {"value": banniere})()

    import cogs.owner as owner_mod

    o_fetch, o_env = owner_mod.fetch_image_bytes, v74.panels.envoyer
    rendus = []

    async def _fetch(_url):
        return image

    async def _envoyer(_cible, panneau, **_k):
        rendus.append(panneau)

    owner_mod.fetch_image_bytes = _fetch
    v74.panels.envoyer = _envoyer
    try:
        asyncio.run(modale.on_submit(_Interaction()))
    finally:
        owner_mod.fetch_image_bytes = o_fetch
        v74.panels.envoyer = o_env
    return appels_membre, appels_globaux, rendus


def test_l_identite_globale_n_est_jamais_touchee():
    membre, globaux, _ = _executer(avatar="https://x/a.png", banniere="https://x/b.png")
    assert globaux == [], "bot.user.edit ne doit jamais etre appele depuis /setup"
    assert membre


def test_seuls_avatar_et_banniere_sont_modifies():
    membre, _, _ = _executer(avatar="https://x/a.png", banniere="https://x/b.png")
    cles = {c for appel in membre for c in appel}
    assert cles == {"avatar", "banner"}
    assert "bio" not in cles


def test_la_bio_n_est_plus_dans_le_formulaire():
    modale = v74.IdentiteBotModal(None)
    labels = {item.label for item in modale.children}
    assert labels == {"URL de l'avatar (vide = inchangé)", "URL de la bannière"}


def test_aucun_champ_rempli_ne_declenche_aucun_appel():
    membre, globaux, rendus = _executer()
    assert membre == [] and globaux == []
    assert rendus


def test_une_image_introuvable_ne_modifie_pas_le_profil():
    membre, _, rendus = _executer(avatar="https://x/a.png", image=None)
    assert membre == []
    assert rendus


def test_le_compte_rendu_dit_que_c_est_local():
    _, _, rendus = _executer(avatar="https://x/a.png")
    assert rendus
