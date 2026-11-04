"""04/11/2026 : musique — identification par API, lecteur unique, Opus, « +music <titre> »."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils.music import catalog  # noqa: E402
from utils.music.models import Track  # noqa: E402
from utils.music.providers.search import SearchProvider  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_titre_video_et_duree_youtube():
    assert catalog.depuis_titre_video("SAÏF - Le taf du loup (Clip officiel)", "Saïf") == ("Le taf du loup", "SAÏF")
    assert catalog.depuis_titre_video("Le taf du loup", "Saif - Topic") == ("Le taf du loup", "Saif")
    assert catalog.duree_iso("PT3M32S") == 212
    assert catalog.duree_iso("PT1H2M") == 3720
    assert catalog.duree_iso("") is None


def test_identification_par_ordre_youtube_puis_spotify_puis_deezer(monkeypatch):
    monkeypatch.setenv("SENTRIX_MUSIC_CATALOG", "1")
    catalog._CACHE.clear()
    appels = []

    async def youtube(session, requete, cle):
        appels.append(("youtube", cle))
        return None

    async def spotify(session, requete, sp):
        appels.append("spotify")
        return None

    async def deezer(session, requete):
        appels.append("deezer")
        return Track(title="Le taf du loup", artist="Saïf", duration=200, provider="deezer")

    monkeypatch.setattr(catalog, "_youtube", youtube)
    monkeypatch.setattr(catalog, "_spotify", spotify)
    monkeypatch.setattr(catalog, "_deezer", deezer)
    monkeypatch.setattr(catalog, "cle_youtube", lambda: "CLE")
    piste = asyncio.run(catalog.identifier("saif taf du loup"))
    assert (piste.title, piste.artist) == ("Le taf du loup", "Saïf")
    assert appels == [("youtube", "CLE"), "spotify", "deezer"]
    # Deuxième fois : depuis le cache, aucun appel.
    asyncio.run(catalog.identifier("SAIF taf du loup"))
    assert len(appels) == 3
    catalog._CACHE.clear()


def test_sans_cle_youtube_on_passe_directement_au_catalogue_suivant(monkeypatch):
    monkeypatch.setenv("SENTRIX_MUSIC_CATALOG", "1")
    catalog._CACHE.clear()
    monkeypatch.setattr(catalog, "cle_youtube", lambda: "")

    async def interdit(*a, **k):
        raise AssertionError("YouTube sans clé")

    async def panne(*a, **k):
        raise RuntimeError("réseau")

    async def deezer(session, requete):
        return None

    monkeypatch.setattr(catalog, "_youtube", interdit)
    monkeypatch.setattr(catalog, "_spotify", panne)
    monkeypatch.setattr(catalog, "_deezer", deezer)
    assert asyncio.run(catalog.identifier("rien du tout")) is None
    assert "rien du tout" not in catalog._CACHE  # un échec n'est pas mémorisé


class _Lecture:
    name = "soundcloud"
    is_temporarily_unavailable = False

    def __init__(self, resultats):
        self.resultats, self.recherches = resultats, []

    async def search_playable(self, *, title, artist, duration, limit=5):
        self.recherches.append((title, artist, duration))
        return list(self.resultats)

    def mark_available(self):
        pass

    def mark_unavailable(self, reason):
        pass


def test_la_recherche_utilise_le_titre_identifie(monkeypatch):
    bonne = Track(title="Saïf - Le taf du loup", artist="Saïf", duration=201,
                  playable_url="https://x/bon", playback_provider="soundcloud", provider="soundcloud")
    mauvaise = Track(title="Le loup (cover piano)", artist="Quelqu'un", duration=95,
                     playable_url="https://x/mauvais", playback_provider="soundcloud", provider="soundcloud")
    lecture = _Lecture([mauvaise, bonne])

    async def identifier(requete, *, spotify=None):
        return Track(title="Le taf du loup", artist="Saïf", duration=200, thumbnail="https://img", provider="deezer")

    monkeypatch.setattr(catalog, "identifier", identifier)
    pistes = asyncio.run(SearchProvider([lecture]).resolve_metadata("saif taf du loup", requested_by=7))
    assert lecture.recherches == [("Le taf du loup", "Saïf", 200)]
    assert pistes[0].playable_url == "https://x/bon"
    assert (pistes[0].title, pistes[0].artist, pistes[0].requested_by) == ("Le taf du loup", "Saïf", 7)


def test_opus_installe_et_charge():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "libopus0" in docker
    musique = (ROOT / "cogs/music.py").read_text(encoding="utf-8")
    assert "assurer_opus()" in musique and "discord.opus.OpusNotLoaded" in musique
    from utils import opus_loader

    assert isinstance(opus_loader.assurer_opus(), bool)  # ne lève jamais


def test_music_suivi_d_un_mot_est_une_recherche():
    from cogs.music import _recherche_apres_groupe

    class Vue:
        def __init__(self, reste):
            self.reste = reste

        def read_rest(self):
            return self.reste

    # Groupe en invoke_without_command : le mot reste dans la lecture.
    ctx = SimpleNamespace(interaction=None, subcommand_passed=None, view=Vue(" saif le taf"))
    assert _recherche_apres_groupe(ctx) == "saif le taf"
    ctx = SimpleNamespace(interaction=None, subcommand_passed="saif", view=Vue(" le taf"))
    assert _recherche_apres_groupe(ctx) == "saif le taf"
    ctx = SimpleNamespace(interaction=None, subcommand_passed=None, view=Vue(""))
    assert _recherche_apres_groupe(ctx) == ""
    assert _recherche_apres_groupe(SimpleNamespace(interaction=object())) == ""


@pytest.mark.asyncio
async def test_un_membre_qui_arrive_reutilise_le_lecteur_du_salon():
    from cogs.music import Music

    music = Music.__new__(Music)
    music._join_panel_delete_tasks = {}
    music._join_panel_messages = {}
    lecteur = SimpleNamespace(id=50)
    music._lecteurs_par_salon()[(1, 10)] = lecteur
    music._delete_saved_member_panel = AsyncMock()
    membre = SimpleNamespace(id=7, guild=SimpleNamespace(id=1))
    await music._ensure_member_music_panel(membre, SimpleNamespace(id=10))
    assert music._join_panel_messages[(1, 7)] is lecteur
    music._delete_saved_member_panel.assert_not_awaited()  # rien supprimé, rien reposté
