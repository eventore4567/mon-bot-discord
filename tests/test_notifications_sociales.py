"""YouTube ne notifiait plus jamais, et rien ne le signalait.

**Le défaut, mesuré.** Une URL de chaîne YouTube nue ne rend pas ses vidéos :
yt-dlp y voit une page à plusieurs onglets et renvoie la CHAÎNE elle-même.

    /@MrBeast          -> id = UCX6OQ3DkcsbYNE6H8uQQuVA   (la chaîne)
    /@MrBeast/videos   -> id = v9QtM6qnG50                (une vidéo)

Le bot enregistre le premier identifiant vu comme « dernière publication »,
puis ne notifie que si l'identifiant CHANGE. Avec celui de la chaîne — qui ne
change jamais — la surveillance s'éteignait définitivement dès le premier
passage, sans erreur, sans log, sans rien.

**Deux garanties ici.** L'URL interrogée vise les vidéos, et un identifiant de
chaîne ne peut plus être pris pour une publication. La seconde est un filet :
elle aurait attrapé le défaut toute seule.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from cogs.notifications import _id_de_publication, _url_a_interroger


# =============================================================================
# L'URL interrogée
# =============================================================================

@pytest.mark.parametrize("entree", [
    "https://www.youtube.com/@MrBeast",
    "https://www.youtube.com/@MrBeast/",
    "https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA",
    "https://www.youtube.com/c/MrBeast",
    "https://www.youtube.com/user/MrBeast",
])
def test_une_chaine_youtube_vise_ses_videos(entree):
    assert _url_a_interroger(entree).endswith("/videos")


@pytest.mark.parametrize("deja_precise", [
    "https://www.youtube.com/@MrBeast/videos",
    "https://www.youtube.com/@MrBeast/streams",
    "https://www.youtube.com/@MrBeast/shorts",
    "https://www.youtube.com/watch?v=v9QtM6qnG50",
    "https://www.youtube.com/playlist?list=PL123",
])
def test_une_url_deja_precise_nest_pas_modifiee(deja_precise):
    """Ajouter « /videos » à une URL de vidéo la casserait."""
    assert _url_a_interroger(deja_precise) == deja_precise


@pytest.mark.parametrize("ailleurs", [
    "https://www.twitch.tv/zerator",
    "https://www.tiktok.com/@khaby.lame",
    "https://kick.com/quelquun",
])
def test_les_autres_plateformes_ne_sont_pas_touchees(ailleurs):
    """« /videos » est une convention YouTube : l'ajouter ailleurs rendrait
    une URL inexistante."""
    assert _url_a_interroger(ailleurs) == ailleurs


def test_une_url_vide_ne_leve_pas():
    assert _url_a_interroger("") == ""
    assert _url_a_interroger(None) == ""


# =============================================================================
# Le filet : un identifiant de chaîne n'est pas une publication
# =============================================================================

def test_un_identifiant_de_chaine_est_refuse():
    """C'est CE filet qui aurait attrapé le défaut : enregistrer un
    identifiant de chaîne comme dernière publication éteint la surveillance
    pour toujours."""
    assert _id_de_publication("UCX6OQ3DkcsbYNE6H8uQQuVA") == ""


def test_un_identifiant_de_video_est_accepte():
    assert _id_de_publication("v9QtM6qnG50") == "v9QtM6qnG50"
    assert _id_de_publication("7691740195418377502") == "7691740195418377502"


@pytest.mark.parametrize("vide", ["", "   ", None, 0])
def test_un_identifiant_vide_est_refuse(vide):
    assert _id_de_publication(vide) == ""


def test_un_identifiant_qui_commence_par_uc_mais_nest_pas_une_chaine_passe():
    """La règle est la FORME exacte d'un identifiant de chaîne — 24
    caractères après « UC » — pas le simple préfixe. Un identifiant de vidéo
    qui commencerait par « UC » ne doit pas être rejeté."""
    assert _id_de_publication("UCourt") == "UCourt"
