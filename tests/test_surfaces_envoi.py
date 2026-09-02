"""Les quatre surfaces par lesquelles SentriX repond.

Un bouton repond via ``interaction.response`` — un InteractionResponse, qui
expose ``send_message`` et PAS ``send``. 267 appels a panels.envoyer visaient
cette surface et levaient tous une AttributeError au clic, sans qu'aucun test
d'import ne bronche : le code s'importe, il echoue a l'usage.

Ce test tient le contrat des quatre surfaces, dans les deux sens (envoi et
edition), pour que ce trou ne puisse pas se rouvrir.
"""
from __future__ import annotations

import asyncio
import os

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "x")

from utils import sentrix_panels as panels  # noqa: E402


class _Journal:
    def __init__(self):
        self.appels: list[tuple[str, dict]] = []


class _Salon(_Journal):
    """ctx, un salon, un membre : tout ce qui est Messageable."""

    async def send(self, **kw):
        self.appels.append(("send", kw))


class _Followup(_Journal):
    """interaction.followup : un Webhook, qui expose send()."""

    async def send(self, **kw):
        self.appels.append(("followup.send", kw))


class _Reponse(discord.InteractionResponse):
    def __init__(self, parent=None, fini=False):
        self._parent = parent
        self._fini = fini
        self.appels: list[tuple[str, dict]] = []

    def is_done(self):
        return self._fini

    async def send_message(self, **kw):
        self.appels.append(("send_message", kw))

    async def edit_message(self, **kw):
        self.appels.append(("edit_message", kw))


class _Interaction:
    def __init__(self, fini=False):
        self.response = _Reponse(self, fini)
        self.followup = _Followup()
        self.appels: list[tuple[str, dict]] = []

    async def edit_original_response(self, **kw):
        self.appels.append(("edit_original_response", kw))


def _panneau():
    return panels.Panneau(titre="Titre", kind="info")


def test_envoi_vers_un_salon():
    cible = _Salon()
    asyncio.run(panels.envoyer(cible, _panneau()))
    nom, kw = cible.appels[0]
    assert nom == "send"
    assert isinstance(kw["view"], discord.ui.LayoutView)


def test_envoi_vers_une_reponse_d_interaction():
    """La surface qui plantait : InteractionResponse n'a pas de send()."""
    cible = _Reponse()
    asyncio.run(panels.envoyer(cible, _panneau(), ephemere=True))
    nom, kw = cible.appels[0]
    assert nom == "send_message"
    assert kw["ephemeral"] is True


def test_envoi_vers_une_reponse_deja_consommee_bascule_sur_le_followup():
    """Deux reponses sur la meme interaction : Discord refuse la seconde."""
    parent = _Interaction(fini=True)
    asyncio.run(panels.envoyer(parent.response, _panneau()))
    assert parent.followup.appels and parent.followup.appels[0][0] == "followup.send"


def test_envoi_vers_un_followup():
    cible = _Followup()
    asyncio.run(panels.envoyer(cible, _panneau()))
    assert cible.appels[0][0] == "followup.send"


@pytest.mark.parametrize(
    "fabrique,attendu",
    [
        (lambda: _Reponse(), "edit_message"),
        (lambda: _Interaction(), "edit_original_response"),
    ],
)
def test_edition_sur_chaque_surface(fabrique, attendu):
    cible = fabrique()
    asyncio.run(panels.editer(cible, _panneau()))
    assert cible.appels[0][0] == attendu
    assert "attachments" in cible.appels[0][1]


def test_le_panneau_ne_porte_jamais_de_content():
    """Discord renvoie 400 : le texte doit vivre DANS une section."""
    cible = _Salon()
    asyncio.run(panels.envoyer(cible, _panneau(), content="interdit"))
    assert "content" not in cible.appels[0][1]


def test_les_fichiers_de_l_appelant_cohabitent_avec_la_banniere():
    """Une transcription de ticket, une carte de profil, une image generee :
    ces fichiers doivent partir AVEC la banniere, pas a sa place. Sans la
    fusion, `files=` ecrasait la banniere et le panneau affichait une galerie
    pointant vers une piece jointe absente."""
    import io as _io

    cible = _Salon()
    fichier = discord.File(_io.BytesIO(b"x"), filename="transcription.txt")
    asyncio.run(panels.envoyer(cible, _panneau(), files=[fichier]))
    noms = [f.filename for f in cible.appels[0][1]["files"]]
    assert noms == ["banner_info.webp", "transcription.txt"], noms


def test_un_fichier_unique_est_accepte_aussi():
    import io as _io

    cible = _Salon()
    asyncio.run(
        panels.envoyer(
            cible, _panneau(), file=discord.File(_io.BytesIO(b"y"), filename="carte.png")
        )
    )
    noms = [f.filename for f in cible.appels[0][1]["files"]]
    assert "carte.png" in noms and "banner_info.webp" in noms
