"""Gameplay GIF regressions: visual-only changes, Components V2 remain interactive."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from utils import game_visuals, sentrix_panels as panels

ROOT = Path(__file__).resolve().parents[1]


def test_curated_media_are_real_direct_animated_gif_links():
    assert len(game_visuals.GIFS) >= 7
    assert len(set(game_visuals.GIFS.values())) == len(game_visuals.GIFS)
    assert all(
        "giphy.com/media/" in url and url.endswith("/giphy.gif")
        for url in game_visuals.GIFS.values()
    )


def test_each_game_family_chooses_relevant_anime_scene():
    cases = {
        "Duel": "fight",
        "Zombie": "fight",
        "Course à l'emoji": "race",
        "Quiz de culture": "think",
        "Memory": "think",
        "Pile ou face": "coin",
        "Coinflip": "coin",
        "SLAP": "slap",
        "Bombes": "fight",
        "Puissance 4": "arcade",
    }
    for game, expected in cases.items():
        assert game_visuals.scene_for(game, "La partie commence.") == expected, game


def test_win_loss_and_invalid_input_scenes_are_not_confused():
    assert game_visuals.scene_for("Bombes", "🏆 Vous avez gagné !", "success") == "win"
    assert game_visuals.scene_for("Bombes", "💥 Vous avez perdu.", "danger") == "loss"
    assert game_visuals.scene_for("Quiz", "✅ Bonne réponse, victoire !") == "win"
    assert game_visuals.scene_for("Quiz", "Mauvais choix, vous avez perdu.") == "loss"
    assert game_visuals.scene_for("Quiz", "Ce choix est invalide", "warning") is None
    assert game_visuals.scene_for("Bombes", "Pas assez d'argent", "danger") is None
    assert game_visuals.scene_for("Historique des jeux", "Vous avez gagné", "success") is None
    assert game_visuals.scene_for("Classement", "Voici les gagnants") is None


def test_animation_is_in_same_components_v2_panel_as_content_and_buttons():
    # Simule un GIF déjà téléchargé (pas de dépendance réseau en CI).
    data = b"GIF89a" + b"frame-test-data" + b";"
    game_visuals._MEDIA_BYTES["fight"] = data
    try:
        original = discord.Embed(title="🎮 Duel", description="⚔️ Choisissez votre attaque.")
        result = game_visuals.decorate_embed(
            original, title="Duel", description=original.description,
        )
        assert result is original
        assert result.image.url == "attachment://sentrix_game_fight.gif"
        panel = panels.depuis_embed(result)
        content = repr(panel.to_components())
        assert result.image.url in content
        assert "Choisissez votre attaque" in content
        assert "Duel" in content
        files = panel.fichiers()
        assert len(files) == 1
        assert files[0].filename == "sentrix_game_fight.gif"
        assert files[0].fp.read() == data
        files[0].close()
        # Les discord.File doivent être créés à neuf pour chaque édition.
        again = panel.fichiers()
        assert again[0].fp is not files[0].fp
        again[0].close()
    finally:
        game_visuals._MEDIA_BYTES.pop("fight", None)


def test_invalid_command_does_not_show_a_heavy_gif():
    embed = discord.Embed(title="Minesweeper", description="Permission manquante.")
    game_visuals.decorate_embed(
        embed, title="Minesweeper", description=embed.description,
        kind="warning",
    )
    assert not embed.image.url


def test_game_modules_use_same_single_visual_resolver():
    economy = (ROOT / "cogs/games_economy.py").read_text(encoding="utf-8")
    mini = (ROOT / "cogs/minigames.py").read_text(encoding="utf-8")
    arcade = (ROOT / "cogs/games_arcade.py").read_text(encoding="utf-8")
    for name, source in (("economy", economy), ("mini", mini)):
        assert "game_visuals.decorate_embed_checked(" in source, name
    assert "from cogs.games_economy import _embed" in arcade
    assert 'if "gagne la partie" in status.casefold() else None' in economy
    assert "verified_image_for" in economy


def test_verified_media_skips_broken_html_and_never_creates_blank_gallery(monkeypatch):
    """A Tenor-like 200/HTML response must not make a black rectangle."""
    async def fail(_url):
        return None
    monkeypatch.setattr(game_visuals, "_fetch_gif_bytes", fail)
    game_visuals._MEDIA_STATE.clear()
    game_visuals._MEDIA_BYTES.clear()

    async def run():
        failed = discord.Embed(title="Pile ou face", description="PILE — vous aviez vu juste !")
        await game_visuals.decorate_embed_checked(
            failed, title="Pile ou face", description=failed.description,
        )
        assert failed.image.url is None
        assert game_visuals.verified_image_for is not None
        clean = panels.depuis_embed(failed)
        assert all(x not in repr(clean.to_components()) for x in game_visuals.GIFS.values())
    asyncio.run(run())
    game_visuals._MEDIA_STATE.clear()


def test_verified_media_uses_only_checked_gif_and_caches_good_result(monkeypatch):
    calls = []
    async def works(url):
        calls.append(url)
        return b"GIF89a" + b"test-data" + b";"
    monkeypatch.setattr(game_visuals, "_fetch_gif_bytes", works)
    game_visuals._MEDIA_STATE.clear()
    game_visuals._MEDIA_BYTES.clear()

    async def run():
        for _ in range(3):
            embed = discord.Embed(title="Pile ou face", description="PILE — vous aviez vu juste !")
            result = await game_visuals.decorate_embed_checked(
                embed, title="Pile ou face", description=embed.description,
            )
            assert result.image.url == "attachment://sentrix_game_coin.gif"
    asyncio.run(run())
    assert calls == [game_visuals.GIFS["coin"]]
    game_visuals._MEDIA_STATE.clear()
    game_visuals._MEDIA_BYTES.clear()


def test_200_html_is_rejected_even_if_http_success(monkeypatch):
    class FakeBody:
        async def read(self, size):
            return b"<html>"[:size]
    class Response:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        content = FakeBody()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr(game_visuals.aiohttp, "ClientSession", lambda **kwargs: Session())
    assert asyncio.run(game_visuals._probe_gif(game_visuals.GIFS["win"])) is False


def test_real_gif_signature_is_accepted(monkeypatch):
    class FakeBody:
        async def read(self, size):
            return b"GIF89a"[:size]
    class Response:
        status = 206
        headers = {"Content-Type": "image/gif"}
        content = FakeBody()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr(game_visuals.aiohttp, "ClientSession", lambda **kwargs: Session())
    assert asyncio.run(game_visuals._probe_gif(game_visuals.GIFS["win"])) is True


def test_panel_edit_sends_validated_gif_as_attachment_not_remote_link():
    from unittest.mock import AsyncMock

    async def run():
        raw = b"GIF89a" + b"test-data" + b";"
        game_visuals._MEDIA_BYTES["think"] = raw
        try:
            embed = discord.Embed(
                title="❓ Question de culture générale",
                description="Quelle est la capitale de la France ?",
            )
            embed.set_image(url="attachment://sentrix_game_think.gif")
            panel = panels.depuis_embed(embed)
            target = type("Message", (), {})()
            target.edit = AsyncMock()
            await panels.editer(target, panel)
            kwargs = target.edit.await_args.kwargs
            assert kwargs["view"] is panel
            assert len(kwargs["attachments"]) == 1
            file = kwargs["attachments"][0]
            assert file.filename == "sentrix_game_think.gif"
            assert file.fp.read() == raw
            assert "giphy" not in repr(panel.to_components())
            file.close()
        finally:
            game_visuals._MEDIA_BYTES.pop("think", None)

    asyncio.run(run())


def test_fetch_rejects_html_and_excessive_media(monkeypatch):
    """Even a 200 response with HTML or a too-large GIF is never attached."""
    class Body:
        def __init__(self, data):
            self.data = data
        async def iter_chunked(self, _size):
            yield self.data

    class Response:
        status = 200
        def __init__(self, mime, data, size=None):
            self.headers = {"Content-Type": mime}
            self.content = Body(data)
            self.content_length = size if size is not None else len(data)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False

    class Session:
        response = None
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def get(self, *args, **kwargs): return self.response

    session = Session()
    monkeypatch.setattr(game_visuals.aiohttp, "ClientSession", lambda **kwargs: session)
    session.response = Response("text/html", b"<html>no gif</html>")
    assert asyncio.run(game_visuals._fetch_gif_bytes("https://cdn.example/g.gif")) is None
    session.response = Response("image/gif", b"GIF89a" + b"123" + b";", size=game_visuals.MAX_GIF_BYTES + 1)
    assert asyncio.run(game_visuals._fetch_gif_bytes("https://cdn.example/g.gif")) is None
    session.response = Response("image/gif", b"GIF89a" + b"12345678" + b";")
    assert asyncio.run(game_visuals._fetch_gif_bytes("https://cdn.example/g.gif")) == b"GIF89a12345678;"
