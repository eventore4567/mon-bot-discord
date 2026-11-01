"""Régressions : images explicites, pack applicatif et setup simplifié."""
from __future__ import annotations

import ast
import io
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

ROOT = Path(__file__).resolve().parents[1]


def test_nouveau_pack_emojis_distincts_et_animés(tmp_path):
    from tools.generer_emojis_application_v2 import BASES, BADGES, NOMBRE, generer
    dossier = ROOT / "assets" / "sentrix_emojis"
    for nom in set(BASES) | set(BADGES):
        path = dossier / f"sentrix_{nom}.png"
        assert path.exists(), f"Asset de composition manquant : {path.name}"
        shutil.copy2(path, tmp_path / path.name)
    resultat = generer(tmp_path)
    assert resultat == {"crees": 112, "total_planifies": NOMBRE}
    assert NOMBRE == len(BASES) * (len(BADGES) + 1)
    images = list(tmp_path.glob("sentrix_*_*.png"))
    gifs = list(tmp_path.glob("sentrix_live_*.gif"))
    assert len(gifs) == 16
    assert all(f.stat().st_size < 256 * 1024 for f in gifs)
    for gif in gifs:
        with Image.open(gif) as image:
            assert getattr(image, "n_frames", 1) >= 4
            assert image.size == (128, 128)
    resultat2 = generer(tmp_path)
    assert resultat2["crees"] == 0


@pytest.mark.asyncio
async def test_images_utilisateur_transmises_en_data_uri_et_pas_urls_externes():
    from cogs.ai import _images_from_discord_attachments

    img = Image.new("RGB", (100, 100), (28, 47, 91))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image = SimpleNamespace(
        content_type="image/png", size=len(buf.getvalue()),
        read=AsyncMock(return_value=buf.getvalue()),
    )
    bad = SimpleNamespace(
        content_type="application/pdf", size=42,
        read=AsyncMock(return_value=b"bad"),
    )
    result = await _images_from_discord_attachments([image, bad])
    assert len(result) == 1
    assert result[0].startswith("data:image/jpeg;base64,")
    bad.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_gif_analyse_une_image_pas_le_fichier_anime():
    from cogs.ai import _images_from_discord_attachments

    one = Image.new("RGBA", (48, 48), (250, 40, 30, 255))
    two = Image.new("RGBA", (48, 48), (30, 250, 70, 255))
    buf = io.BytesIO()
    one.save(buf, format="GIF", save_all=True, append_images=[two],
             duration=100, loop=0)
    image = SimpleNamespace(
        content_type="image/gif", size=len(buf.getvalue()),
        read=AsyncMock(return_value=buf.getvalue()),
    )
    result = await _images_from_discord_attachments([image])
    assert len(result) == 1
    assert result[0].startswith("data:image/jpeg;base64,")


def test_rendu_setup_et_ai_sont_statiques_et_sans_doublons():
    home = (ROOT / "cogs/setup_experience_v74.py").read_text()
    marker = home.index("    async def _build_home(self)")
    end = home.index("    async def _build_home_complet", marker)
    region = home[marker:end]
    assert "Logs Soundboard" not in region
    assert "Assistant guidé" not in region
    assert "accent_colour=0x6C57CC" in region
    assert "Actives" in region and "Désactivées" in region
    assert region.count("discord.ui.Select(") == 1
    assert "v73.poser_banniere(container)" in region

    ai = (ROOT / "cogs/ai.py").read_text()
    assert "image_urls=images" in ai
    assert "if not attachments and await self._invoke_natural_command" in ai
    assert "sentrix_emojis.emoji" in ai
    ast.parse(ai)
    ast.parse((ROOT / "utils/ai_service.py").read_text())
