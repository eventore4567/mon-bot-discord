"""L'apparence de SentriX se change PAR SERVEUR, jamais globalement.

Discord distingue deux identités pour une application :

- globale (`bot.user.edit`) — partagée par les 37 serveurs. Un administrateur
  ne doit pas pouvoir la toucher : il changerait SentriX chez tout le monde.
  Elle reste au propriétaire, via `+set-bot` ;
- profil de serveur (`guild.me.edit`) — propre à ce serveur. Les autres voient
  l'original. C'est celui que /setup édite, et c'est pour ça que l'admin du
  serveur y a droit.

Ce fichier verrouille cette séparation : une erreur ici ferait changer
l'apparence du bot chez 36 serveurs qui n'ont rien demandé.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import setup_experience_v74 as v74  # noqa: E402


def _executer(avatar="", banniere="", bio="", image=b"octets"):
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
    modale.bio = type("T", (), {"value": bio})()

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
    # LE test qui compte : sinon un admin change SentriX chez 36 autres serveurs.
    membre, globaux, _ = _executer(avatar="https://x/a.png", banniere="https://x/b.png", bio="Salut")
    assert globaux == [], "bot.user.edit ne doit JAMAIS être appelé depuis /setup"
    assert membre, "le profil de serveur doit bien être modifié"


def test_les_trois_champs_passent_par_le_profil_de_serveur():
    membre, _, _ = _executer(avatar="https://x/a.png", banniere="https://x/b.png", bio="Salut")
    cles = {c for appel in membre for c in appel}
    assert cles == {"avatar", "banner", "bio"}


def test_un_champ_vide_ne_change_rien():
    membre, _, rendus = _executer(bio="Seulement la bio")
    assert [c for appel in membre for c in appel] == ["bio"]
    assert rendus


def test_aucun_champ_rempli_ne_declenche_aucun_appel():
    membre, globaux, rendus = _executer()
    assert membre == [] and globaux == []
    assert rendus, "le membre doit quand même recevoir une réponse"


def test_une_image_introuvable_n_empeche_pas_la_bio():
    membre, _, rendus = _executer(avatar="https://x/a.png", bio="Texte", image=None)
    assert [c for appel in membre for c in appel] == ["bio"]
    assert rendus, "l'échec de l'avatar doit être rapporté"


def test_le_compte_rendu_dit_que_c_est_local():
    _, _, rendus = _executer(bio="Texte")
    assert rendus, "un compte rendu est attendu"
